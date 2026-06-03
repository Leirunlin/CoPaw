/**
 * GenUiSurface — render an A2UI surface natively (no iframe).
 *
 * Cold-loads the surface (`/genui/surface`), subscribes to live deltas
 * (`/genui/stream`), and folds user actions back via `/genui/action`. This is
 * the unified replacement for bespoke per-feature viewers (the task board is
 * its first consumer); a surface is addressed by `surfaceId`.
 */
import React, { useCallback, useEffect, useState } from "react";
import { message as antdMessage } from "antd";
import { useAgentStore } from "../stores/agentStore";
import { fetchSurface, postAction } from "./api";
import { renderComponent } from "./components";
import { subscribeStream } from "./store";
import { useGenUiSurface } from "./useGenUiSurface";
import { ClientAction } from "./types";

export interface GenUiSurfaceProps {
  /** A2UI surface id, e.g. `task:tasks/add-login.task.json`. */
  surfaceId: string;
  /** Run key (chat id) for live deltas. Defaults to the active chat. */
  runKey?: string;
  height?: number | string;
  compact?: boolean;
}

export const GenUiSurface: React.FC<GenUiSurfaceProps> = ({
  surfaceId,
  runKey,
  height = 480,
  compact = true,
}) => {
  const lastChatId = useAgentStore(
    (s) => s.lastChatIdByAgent[s.selectedAgent] || "",
  );
  const effectiveRunKey = runKey ?? lastChatId;
  const model = useGenUiSurface(effectiveRunKey, surfaceId);
  const [error, setError] = useState<string | null>(null);

  // Cold-load current state + subscribe to live deltas.
  useEffect(() => {
    let cancelled = false;
    fetchSurface(effectiveRunKey, surfaceId)
      .then((envs) => {
        if (!cancelled) model.applyMany(envs);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    const unsub = subscribeStream(effectiveRunKey);
    return () => {
      cancelled = true;
      unsub();
    };
  }, [effectiveRunKey, surfaceId, model]);

  const onAction = useCallback(
    (
      name: string,
      sourceComponentId: string,
      context: Record<string, unknown>,
    ) => {
      const action: ClientAction = {
        name,
        surfaceId,
        sourceComponentId,
        timestamp: new Date().toISOString(),
        context,
      };
      postAction(action, effectiveRunKey)
        .then((envs) => model.applyMany(envs))
        .catch((e) =>
          antdMessage.error(
            `genui: ${e instanceof Error ? e.message : String(e)}`,
          ),
        );
    },
    [surfaceId, effectiveRunKey, model],
  );

  const hasRoot = !!model.get("root");

  return (
    <div
      style={{
        height: compact ? height : "100%",
        overflow: "auto",
        padding: 12,
      }}
      data-genui-surface={surfaceId}
    >
      {error ? (
        <div style={{ color: "#cf1322" }}>Failed to load: {error}</div>
      ) : hasRoot ? (
        renderComponent("root", { model, onAction })
      ) : (
        <div style={{ color: "#888" }}>Loading…</div>
      )}
    </div>
  );
};
