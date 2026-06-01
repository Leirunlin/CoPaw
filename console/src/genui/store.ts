/**
 * Singleton generative-UI store.
 *
 * Holds one `SurfaceModel` per `(runKey, surfaceId)` and, per `runKey`, a single
 * SSE connection to `/genui/stream` (fan-out to all surfaces of that run) — the
 * same singleton pattern as `useWorkspaceWatch`. Frames with
 * `object === "a2ui_response"` are routed to the matching surface model and
 * folded in incrementally (no full-file reload).
 */
import { getApiUrl } from "../api/config";
import { buildAuthHeaders } from "../api/authHeaders";
import { SurfaceModel } from "./surfaceModel";
import { A2uiSseData, Envelope, surfaceIdOf } from "./types";

const _models = new Map<string, SurfaceModel>();

function key(runKey: string, surfaceId: string): string {
  return `${runKey}::${surfaceId}`;
}

export function getModel(runKey: string, surfaceId: string): SurfaceModel {
  const k = key(runKey, surfaceId);
  let m = _models.get(k);
  if (!m) {
    m = new SurfaceModel(surfaceId);
    _models.set(k, m);
  }
  return m;
}

function routeEnvelope(runKey: string, env: Envelope): void {
  const sid = surfaceIdOf(env);
  if (!sid) return;
  const m = _models.get(key(runKey, sid));
  if (m) m.apply(env);
}

// ---------------------------------------------------------------------------
// Per-runKey SSE connection (ref-counted)
// ---------------------------------------------------------------------------

interface Conn {
  controller: AbortController;
  refs: number;
}
const _conns = new Map<string, Conn>();

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function runLoop(runKey: string, signal: AbortSignal): Promise<void> {
  const url = getApiUrl(`/genui/stream?runKey=${encodeURIComponent(runKey)}`);
  let retry = 2_000;

  while (!signal.aborted) {
    try {
      const res = await fetch(url, {
        method: "GET",
        headers: buildAuthHeaders(),
        signal,
      });

      const ctype = res.headers.get("content-type") || "";
      if (!res.ok || !res.body || !ctype.includes("text/event-stream")) {
        // No live run yet (JSON {live:false}); retry so we connect when an
        // agent run starts and begins emitting surface deltas.
        await sleep(retry);
        retry = Math.min(retry * 1.5, 15_000);
        continue;
      }

      retry = 2_000;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const parsed = JSON.parse(raw) as A2uiSseData;
            if (parsed.object === "a2ui_response" && parsed.data?.a2ui) {
              routeEnvelope(runKey, parsed.data.a2ui);
            }
          } catch {
            /* ignore non-JSON / unrelated frames */
          }
        }
      }
    } catch (err) {
      if (signal.aborted) break;
      if (err instanceof DOMException && err.name === "AbortError") break;
      await sleep(retry);
      retry = Math.min(retry * 1.5, 15_000);
    }
  }
}

/** Subscribe to live deltas for a run. Returns an unsubscribe fn. */
export function subscribeStream(runKey: string): () => void {
  if (!runKey) return () => undefined;
  let conn = _conns.get(runKey);
  if (!conn) {
    const controller = new AbortController();
    conn = { controller, refs: 0 };
    _conns.set(runKey, conn);
    void runLoop(runKey, controller.signal);
  }
  conn.refs += 1;

  return () => {
    const c = _conns.get(runKey);
    if (!c) return;
    c.refs -= 1;
    if (c.refs <= 0) {
      c.controller.abort();
      _conns.delete(runKey);
    }
  };
}
