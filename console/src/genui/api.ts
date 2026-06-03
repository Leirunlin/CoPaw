/** HTTP surface for the generative-UI (A2UI) endpoints. */
import { request } from "../api/request";
import { A2UI_VERSION, ClientAction, Envelope } from "./types";

interface ActionResponse {
  ok: boolean;
  errors: unknown[];
  envelopes: Envelope[];
}

interface SurfaceResponse {
  envelopes: Envelope[];
}

/** Report a user action; returns the resulting envelopes to apply locally. */
export async function postAction(
  action: ClientAction,
  runKey: string,
): Promise<Envelope[]> {
  const res = await request<ActionResponse>("/genui/action", {
    method: "POST",
    body: JSON.stringify({ version: A2UI_VERSION, action, runKey }),
  });
  return res.envelopes || [];
}

/** Cold-load the current state of a surface (server mirror or derived). */
export async function fetchSurface(
  runKey: string,
  surfaceId: string,
): Promise<Envelope[]> {
  const qs = `runKey=${encodeURIComponent(
    runKey,
  )}&surfaceId=${encodeURIComponent(surfaceId)}`;
  const res = await request<SurfaceResponse>(`/genui/surface?${qs}`);
  return res.envelopes || [];
}
