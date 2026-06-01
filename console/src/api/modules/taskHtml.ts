import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export type TaskState =
  | "todo"
  | "in_progress"
  | "done"
  | "skipped"
  | "blocked"
  | "failed";

export interface TaskFileMeta {
  path: string;
  size: number;
  mtime: number;
}

export interface TaskFileListResponse {
  files: TaskFileMeta[];
}

export interface TaskPatchBody {
  path: string;
  task_id: string;
  state?: TaskState;
  title?: string;
  description?: string;
  outcome?: string;
  criteria?: string;
  test?: string;
  notes?: string;
}

export interface TaskAddBody {
  path: string;
  parent_id: string;
  title: string;
  description?: string;
  outcome?: string;
  criteria?: string;
  test?: string;
  state?: TaskState;
}

export const taskHtmlApi = {
  /** Raw HTML body of a task file. */
  getFile: async (path: string): Promise<string> => {
    const response = await fetch(
      getApiUrl(`/task_html/file?path=${encodeURIComponent(path)}`),
      { headers: buildAuthHeaders() },
    );
    if (!response.ok) {
      throw new Error(
        `task_html/file failed: ${response.status} ${response.statusText}`,
      );
    }
    return response.text();
  },

  /** List task HTML files in workspace (newest first). */
  listFiles: () => request<TaskFileListResponse>("/task_html/list"),

  /** Patch one task: any combination of state / title / description /
   *  outcome / criteria / test / notes. */
  patch: (body: TaskPatchBody) =>
    request<{ ok: boolean; path: string }>("/task_html/patch", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Delete a task and its descendants. */
  deleteTask: (body: { path: string; task_id: string }) =>
    request<{ ok: boolean; path: string }>("/task_html/delete", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Add a new task (or sub-task when parent_id is given). */
  addTask: (body: TaskAddBody) =>
    request<{ ok: boolean; path: string; task_id: string }>(
      "/task_html/add",
      { method: "POST", body: JSON.stringify(body) },
    ),

  /** Replace the whole HTML file (Workspace source-view save). */
  write: (body: { path: string; html: string }) =>
    request<{ ok: boolean; path: string }>("/task_html/write", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
