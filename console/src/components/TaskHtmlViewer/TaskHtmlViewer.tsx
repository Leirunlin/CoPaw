import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Space, Tooltip, message as antdMessage } from "antd";
import { ExportOutlined, ReloadOutlined } from "@ant-design/icons";
import { taskHtmlApi, type TaskState } from "../../api/modules/taskHtml";
import styles from "./TaskHtmlViewer.module.less";

export interface TaskHtmlViewerProps {
  /** Path under the workspace, e.g. `tasks/add-login.html`. */
  path: string;
  /** Height for the inline (compact) variant. Defaults to 480px. */
  height?: number | string;
  /** Compact = inline-in-chat; otherwise full-bleed. */
  compact?: boolean;
}

interface EditFullPayload {
  taskId: string;
  title: string;
  description: string;
  outcome: string;
  criteria: string;
  test: string;
  state: TaskState;
}

interface AddPayload {
  parentId: string;
  title: string;
  description: string;
  outcome: string;
  criteria: string;
  test: string;
}

type IframeMessage =
  | { type: "task-action"; action: "refresh" }
  | { type: "task-state-cycle"; taskId: string; nextState: TaskState }
  | { type: "task-edit-full"; payload: EditFullPayload }
  | { type: "task-delete"; taskId: string }
  | { type: "task-add"; payload: AddPayload };

const TASK_STATES: ReadonlySet<TaskState> = new Set<TaskState>([
  "todo",
  "in_progress",
  "done",
  "skipped",
  "blocked",
  "failed",
]);

function asTaskState(v: unknown): TaskState | null {
  return typeof v === "string" && TASK_STATES.has(v as TaskState)
    ? (v as TaskState)
    : null;
}

function isEditFullPayload(p: unknown): p is EditFullPayload {
  if (!p || typeof p !== "object") return false;
  const o = p as Record<string, unknown>;
  return (
    typeof o.taskId === "string" &&
    typeof o.title === "string" &&
    typeof o.description === "string" &&
    typeof o.outcome === "string" &&
    typeof o.criteria === "string" &&
    typeof o.test === "string" &&
    asTaskState(o.state) !== null
  );
}

function isAddPayload(p: unknown): p is AddPayload {
  if (!p || typeof p !== "object") return false;
  const o = p as Record<string, unknown>;
  return (
    typeof o.parentId === "string" &&
    typeof o.title === "string" &&
    typeof o.description === "string" &&
    typeof o.outcome === "string" &&
    typeof o.criteria === "string" &&
    typeof o.test === "string"
  );
}

function isIframeMessage(d: unknown): d is IframeMessage {
  if (!d || typeof d !== "object") return false;
  const m = d as Record<string, unknown>;
  if (m.type === "task-action") {
    return m.action === "refresh";
  }
  if (m.type === "task-state-cycle") {
    return typeof m.taskId === "string" && asTaskState(m.nextState) !== null;
  }
  if (m.type === "task-edit-full") {
    return isEditFullPayload(m.payload);
  }
  if (m.type === "task-delete") {
    return typeof m.taskId === "string";
  }
  if (m.type === "task-add") {
    return isAddPayload(m.payload);
  }
  return false;
}

export const TaskHtmlViewer: React.FC<TaskHtmlViewerProps> = ({
  path,
  height = 480,
  compact = true,
}) => {
  const [html, setHtml] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const newTabHref = useMemo(
    () => `/task-html?path=${encodeURIComponent(path)}`,
    [path],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setHtml(await taskHtmlApi.getFile(path));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const dispatch = async (msg: IframeMessage) => {
      if (msg.type === "task-action" && msg.action === "refresh") {
        await reload();
        return;
      }
      if (msg.type === "task-state-cycle") {
        await taskHtmlApi.patch({
          path,
          task_id: msg.taskId,
          state: msg.nextState,
        });
        await reload();
        return;
      }
      if (msg.type === "task-edit-full") {
        const p = msg.payload;
        await taskHtmlApi.patch({
          path,
          task_id: p.taskId,
          title: p.title,
          description: p.description,
          outcome: p.outcome,
          criteria: p.criteria,
          test: p.test,
          state: p.state,
        });
        await reload();
        return;
      }
      if (msg.type === "task-delete") {
        await taskHtmlApi.deleteTask({ path, task_id: msg.taskId });
        await reload();
        return;
      }
      if (msg.type === "task-add") {
        const p = msg.payload;
        await taskHtmlApi.addTask({
          path,
          parent_id: p.parentId,
          title: p.title,
          description: p.description,
          outcome: p.outcome,
          criteria: p.criteria,
          test: p.test,
        });
        await reload();
        return;
      }
    };

    const handler = (ev: MessageEvent) => {
      const iframe = iframeRef.current;
      // sandbox="allow-scripts" (no allow-same-origin) gives the iframe
      // a null origin, so source-identity is the right primary guard.
      if (!iframe || ev.source !== iframe.contentWindow) return;
      if (!isIframeMessage(ev.data)) return;
      void dispatch(ev.data).catch((e) =>
        antdMessage.error(
          `task_html: ${e instanceof Error ? e.message : String(e)}`,
        ),
      );
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [path, reload]);

  return (
    <div
      className={styles.viewer}
      style={{ height: compact ? height : "100%" }}
      data-task-html-path={path}
    >
      <div className={styles.toolbar}>
        <span className={styles.path} title={path}>
          {path}
        </span>
        <Space size={4}>
          <Tooltip title="Reload">
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              onClick={reload}
              loading={loading}
            />
          </Tooltip>
          <Tooltip title="Open in new tab">
            <Button
              type="text"
              size="small"
              icon={<ExportOutlined />}
              href={newTabHref}
              target="_blank"
              rel="noreferrer"
            />
          </Tooltip>
        </Space>
      </div>
      {error ? (
        <div className={styles.error}>Failed to load: {error}</div>
      ) : (
        <iframe
          ref={iframeRef}
          className={styles.iframe}
          sandbox="allow-scripts"
          srcDoc={html}
          title={`task: ${path}`}
        />
      )}
    </div>
  );
};
