/**
 * A2UI v0.10 wire types (the subset qwenpaw speaks).
 *
 * This is a compact native renderer for the pinned A2UI v0.10 envelope format —
 * it consumes the exact same envelopes the backend (`qwenpaw.agents.genui`)
 * emits, so it is swappable for the upstream A2UI React renderer later without
 * changing the protocol. See `src/genui/components.tsx` for the catalog.
 */

export const A2UI_VERSION = "v0.10";

/** A data-binding: `{ path }` is an RFC-6901 pointer into the data model. */
export type DynamicValue =
  | string
  | number
  | boolean
  | { path: string }
  | Record<string, unknown>;

export interface Component {
  id: string;
  component: string;
  [prop: string]: unknown;
}

export interface CreateSurface {
  surfaceId: string;
  catalogId: string;
  theme?: Record<string, unknown>;
}
export interface UpdateComponents {
  surfaceId: string;
  components: Component[];
}
export interface UpdateDataModel {
  surfaceId: string;
  path?: string;
  value?: unknown;
}
export interface DeleteSurface {
  surfaceId: string;
}

export interface Envelope {
  version: string;
  createSurface?: CreateSurface;
  updateComponents?: UpdateComponents;
  updateDataModel?: UpdateDataModel;
  deleteSurface?: DeleteSurface;
  actionResponse?: unknown;
}

/** Client -> server user action (matches genui ClientAction). */
export interface ClientAction {
  name: string;
  surfaceId: string;
  sourceComponentId: string;
  timestamp: string;
  context: Record<string, unknown>;
  actionId?: string;
}

/** The SSE `data:` payload carrying an A2UI envelope (object="a2ui_response"). */
export interface A2uiSseData {
  object?: string;
  data?: {
    a2ui?: Envelope;
    surfaceId?: string;
    runKey?: string;
  };
}

export function isPathRef(v: unknown): v is { path: string } {
  return (
    !!v &&
    typeof v === "object" &&
    typeof (v as { path?: unknown }).path === "string"
  );
}

export function surfaceIdOf(env: Envelope): string {
  return (
    env.createSurface?.surfaceId ??
    env.updateComponents?.surfaceId ??
    env.updateDataModel?.surfaceId ??
    env.deleteSurface?.surfaceId ??
    ""
  );
}
