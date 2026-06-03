import React from "react";
import { Button, Input, Popconfirm, Tooltip } from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Component, DynamicValue } from "../../types";
import { SurfaceModel } from "../../surfaceModel";
import styles from "./TaskBoard.module.less";

interface RenderCtx {
  model: SurfaceModel;
  onAction: (
    name: string,
    sourceComponentId: string,
    context: Record<string, unknown>,
  ) => void;
}

interface TaskRecord {
  id: string;
  parent_id: string;
  title: string;
  state: string;
  description?: string;
  outcome?: string;
  criteria?: string;
  test?: string;
  notes?: string;
}

interface TaskBoardData {
  name?: string;
  tasks?: Record<string, TaskRecord>;
  taskOrder?: string[];
  childrenByParent?: Record<string, string[]>;
  progress?: Record<string, number>;
}

const ACTION_KEYS = ["state", "patch", "add", "delete", "refresh"] as const;
type ActionKey = (typeof ACTION_KEYS)[number];

const STATE_LABEL: Record<string, string> = {
  todo: "todo",
  in_progress: "in_progress",
  done: "done",
  skipped: "skipped",
  blocked: "blocked",
  failed: "failed",
};

const STATE_CLASS: Record<string, string> = {
  todo: styles.statusTodo,
  in_progress: styles.statusInProgress,
  done: styles.statusDone,
  skipped: styles.statusSkipped,
  blocked: styles.statusBlocked,
  failed: styles.statusFailed,
};

function path(taskId: string, field: string): { path: string } {
  return { path: `/tasks/${taskId}/${field}` };
}

function actionName(comp: Component, key: ActionKey): string {
  const actions = comp.actions as Record<string, string> | undefined;
  return actions?.[key] || `task.${key}`;
}

function asTaskBoardData(value: unknown): TaskBoardData {
  return value && typeof value === "object" ? (value as TaskBoardData) : {};
}

function orderedChildren(data: TaskBoardData, parentId: string): string[] {
  const children = data.childrenByParent?.[parentId];
  if (children) return children;
  const tasks = data.tasks || {};
  return (data.taskOrder || Object.keys(tasks)).filter(
    (id) => (tasks[id]?.parent_id || "") === parentId,
  );
}

function computeProgress(data: TaskBoardData): Record<string, number> {
  const counts: Record<string, number> = {
    total: 0,
    todo: 0,
    in_progress: 0,
    done: 0,
    skipped: 0,
    blocked: 0,
    failed: 0,
  };
  for (const t of Object.values(data.tasks || {})) {
    counts.total += 1;
    counts[t.state] = (counts[t.state] || 0) + 1;
  }
  return counts.total > 0 ? counts : data.progress || counts;
}

function findCurrentTask(data: TaskBoardData): TaskRecord | null {
  const tasks = data.tasks || {};
  const ordered = data.taskOrder || Object.keys(tasks);
  const isLeaf = (id: string) => orderedChildren(data, id).length === 0;
  const active = ordered.find(
    (id) => tasks[id]?.state === "in_progress" && isLeaf(id),
  );
  if (active) return tasks[active];
  const next = ordered.find((id) => tasks[id]?.state === "todo" && isLeaf(id));
  return next ? tasks[next] : null;
}

export function renderTaskBoard(
  comp: Component,
  ctx: RenderCtx,
): React.ReactNode {
  const data = asTaskBoardData(
    ctx.model.resolve(comp.value as DynamicValue, {}),
  );
  return <TaskBoard comp={comp} ctx={ctx} data={data} />;
}

const TaskBoard: React.FC<{
  comp: Component;
  ctx: RenderCtx;
  data: TaskBoardData;
}> = ({ comp, ctx, data }) => {
  const stages = orderedChildren(data, "");
  const progress = computeProgress(data);
  const current = findCurrentTask(data);
  const total = progress.total || 0;
  const done = progress.done || 0;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

  const fire = (
    key: ActionKey,
    source: string,
    context: Record<string, unknown>,
  ) => ctx.onAction(actionName(comp, key), source, context);

  const commit = (taskId: string, field: keyof TaskRecord) => {
    const value = ctx.model.resolve(path(taskId, field), "");
    fire("patch", `field_${taskId}_${String(field)}`, {
      taskId,
      field,
      value,
    });
  };

  const bind = (taskId: string, field: keyof TaskRecord) => ({
    value: String(ctx.model.resolve(path(taskId, field), "")),
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      ctx.model.setBoundValue(path(taskId, field), e.target.value),
    onBlur: () => commit(taskId, field),
  });

  return (
    <div className={styles.taskBoard}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>
            Task Plan - {data.name || "Untitled"}
          </h1>
          <div className={styles.meta}>
            {stages.length} stages · {progress.in_progress || 0} active ·{" "}
            {progress.blocked || 0} blocked · {progress.failed || 0} failed
          </div>
        </div>
        <div className={styles.controls}>
          {current ? (
            <span className={styles.current}>
              {current.state === "in_progress" ? "Current" : "Next"}:{" "}
              {current.title}
            </span>
          ) : null}
          <div className={styles.progressBar}>
            <div
              className={styles.progressFill}
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className={styles.progressText}>
            {done} / {total}
          </div>
          <Tooltip title="Refresh">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => fire("refresh", "taskboard_refresh", {})}
            />
          </Tooltip>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() =>
              fire("add", "addstage", { parentId: "", title: "新阶段" })
            }
          >
            Add stage
          </Button>
        </div>
      </header>

      {stages.length ? (
        <section className={styles.graph}>
          {stages.map((stageId, idx) => {
            const stage = data.tasks?.[stageId];
            if (!stage) return null;
            return (
              <div key={stageId} className={styles.stageWrap}>
                <StageCard
                  index={idx + 1}
                  stage={stage}
                  childIds={orderedChildren(data, stageId)}
                  data={data}
                  bind={bind}
                  fire={fire}
                />
                {idx < stages.length - 1 ? (
                  <div className={styles.arrow}>→</div>
                ) : null}
              </div>
            );
          })}
        </section>
      ) : (
        <div className={styles.empty}>
          No stages yet. Add a stage to start shaping the plan.
        </div>
      )}
    </div>
  );
};

const StageCard: React.FC<{
  index: number;
  stage: TaskRecord;
  childIds: string[];
  data: TaskBoardData;
  bind: (
    taskId: string,
    field: keyof TaskRecord,
  ) => {
    value: string;
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => void;
    onBlur: () => void;
  };
  fire: (
    key: ActionKey,
    source: string,
    context: Record<string, unknown>,
  ) => void;
}> = ({ index, stage, childIds, data, bind, fire }) => {
  const children = childIds
    .map((id) => data.tasks?.[id])
    .filter(Boolean) as TaskRecord[];
  const done = children.filter((t) => t.state === "done").length;

  return (
    <article className={styles.stage}>
      <header className={styles.stageHeader}>
        <div className={styles.stageTitleWrap}>
          <Input
            className={styles.stageTitleInput}
            {...bind(stage.id, "title")}
          />
          <div className={styles.stageMeta}>
            Stage {index} · {done}/{children.length} subtasks · {stage.state}
          </div>
        </div>
        <div className={styles.stageActions}>
          <BadgeButton
            state={stage.state}
            onClick={() =>
              fire("state", `statebtn_${stage.id}`, { taskId: stage.id })
            }
          />
          <TaskActions task={stage} fire={fire} />
        </div>
      </header>

      <div className={styles.stageBody}>
        {children.map((task) => (
          <TaskItem key={task.id} task={task} bind={bind} fire={fire} />
        ))}
        <Button
          className={styles.addTaskButton}
          icon={<PlusOutlined />}
          onClick={() =>
            fire("add", `addbtn_${stage.id}`, {
              parentId: stage.id,
              title: "新任务",
            })
          }
        >
          Add subtask
        </Button>
      </div>
    </article>
  );
};

const TaskItem: React.FC<{
  task: TaskRecord;
  bind: (
    taskId: string,
    field: keyof TaskRecord,
  ) => {
    value: string;
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => void;
    onBlur: () => void;
  };
  fire: (
    key: ActionKey,
    source: string,
    context: Record<string, unknown>,
  ) => void;
}> = ({ task, bind, fire }) => {
  const cls = [
    styles.task,
    task.state === "in_progress" ? styles.taskActive : "",
    task.state === "done" ? styles.taskDone : "",
  ].join(" ");

  return (
    <div className={cls}>
      <div className={styles.taskHead}>
        <Input className={styles.taskTitleInput} {...bind(task.id, "title")} />
        <BadgeButton
          state={task.state}
          onClick={() =>
            fire("state", `statebtn_${task.id}`, { taskId: task.id })
          }
        />
      </div>
      <Input.TextArea
        className={styles.taskDesc}
        autoSize={{ minRows: 1, maxRows: 5 }}
        placeholder="Description"
        {...bind(task.id, "description")}
      />
      {task.outcome ? (
        <FieldSection
          kind="outcome"
          label="Outcome"
          binding={bind(task.id, "outcome")}
        />
      ) : null}
      {task.criteria ? (
        <FieldSection
          kind="criteria"
          label="Criteria"
          binding={bind(task.id, "criteria")}
        />
      ) : null}
      {task.test ? (
        <FieldSection
          kind="test"
          label="Test"
          binding={bind(task.id, "test")}
        />
      ) : null}
      <div className={styles.notes}>
        <div className={styles.notesLabel}>Notes / execution log</div>
        <Input.TextArea
          className={styles.notesInput}
          autoSize={{ minRows: 1, maxRows: 6 }}
          {...bind(task.id, "notes")}
        />
      </div>
      <div className={styles.cardActions}>
        <TaskActions task={task} fire={fire} />
      </div>
    </div>
  );
};

const TaskActions: React.FC<{
  task: TaskRecord;
  fire: (
    key: ActionKey,
    source: string,
    context: Record<string, unknown>,
  ) => void;
}> = ({ task, fire }) => (
  <Popconfirm
    title="Delete task?"
    okText="Delete"
    cancelText="Cancel"
    onConfirm={() => fire("delete", `delbtn_${task.id}`, { taskId: task.id })}
  >
    <Button danger type="text" size="small" icon={<DeleteOutlined />} />
  </Popconfirm>
);

const BadgeButton: React.FC<{ state: string; onClick: () => void }> = ({
  state,
  onClick,
}) => (
  <Button
    className={`${styles.badgeButton} ${
      STATE_CLASS[state] || styles.statusTodo
    }`}
    onClick={onClick}
  >
    {STATE_LABEL[state] || state}
  </Button>
);

const FieldSection: React.FC<{
  kind: "outcome" | "criteria" | "test";
  label: string;
  binding: {
    value: string;
    onChange: (
      e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => void;
    onBlur: () => void;
  };
}> = ({ kind, label, binding }) => {
  const cls = [
    styles.section,
    kind === "outcome" ? styles.sectionOutcome : "",
    kind === "criteria" ? styles.sectionCriteria : "",
    kind === "test" ? styles.sectionTest : "",
  ].join(" ");

  return (
    <div className={cls}>
      <div className={styles.sectionLabel}>{label}</div>
      <Input.TextArea
        className={styles.sectionInput}
        autoSize={{ minRows: 1, maxRows: 6 }}
        {...binding}
      />
    </div>
  );
};
