/** HTTP surface for the generative-UI (A2UI) endpoints. */
import { request } from "../api/request";
import { useAgentStore } from "../stores/agentStore";
import { ClientAction, Envelope } from "./types";

interface ActionResponse {
  ok: boolean;
  errors: unknown[];
  envelopes: Envelope[];
}

interface SurfaceResponse {
  envelopes: Envelope[];
}

/** Resolve the current run key (chat id) for live surface delta routing. */
export function getRunKey(): string {
  try {
    const raw =
      sessionStorage.getItem("qwenpaw-agent-storage") ||
      localStorage.getItem("qwenpaw-agent-storage");
    const selectedAgent = raw
      ? JSON.parse(raw)?.state?.selectedAgent
      : undefined;
    if (!selectedAgent) return "";
    return useAgentStore.getState().getLastChatId(selectedAgent) || "";
  } catch {
    return "";
  }
}

/** Report a user action; returns the resulting envelopes to apply locally. */
export async function postAction(
  action: ClientAction,
  runKey: string,
): Promise<Envelope[]> {
  const res = await request<ActionResponse>("/genui/action", {
    method: "POST",
    body: JSON.stringify({ ...action, runKey }),
  });
  return res.envelopes || [];
}

/** Cold-load the current state of a surface (server mirror or derived). */
export async function fetchSurface(
  runKey: string,
  surfaceId: string,
): Promise<Envelope[]> {
  const qs = `runKey=${encodeURIComponent(runKey)}&surfaceId=${encodeURIComponent(
    surfaceId,
  )}`;
  const res = await request<SurfaceResponse>(`/genui/surface?${qs}`);
  return res.envelopes || [];
}
