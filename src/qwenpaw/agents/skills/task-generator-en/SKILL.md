---
name: task-generator
description: "Use this skill to plan a multi-step task as a structured task plan and execute it step by step. Triggers on 'plan a task', 'make a task list and run it', 'do this task', 'continue the task', 'resume the task', and any /task-generator [arg] invocation. Creates <workspace>/tasks/<name>.task.json; the Workspace pane renders it as a native A2UI board, users can edit it there, and the agent rereads the same JSON before each execution step."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📋"
    requires: {}
---

> **Important:** all `scripts/` paths are relative to this skill directory.
> Run them with `cd {this_skill_dir} && python scripts/<name>.py ...`, or pass
> the skill directory as `cwd` to `execute_shell_command`.

# Task Generator

This skill has two phases, with exactly one user gate between them:

* **Phase 1 - Create.** Build a `task_doc` JSON object and call `scripts/materialize.py`. The script writes `<workspace>/tasks/<name>.task.json`, projects it as an A2UI board into the current run, then the agent yields.
* **Phase 2 - Execute.** After the user says "execute" / "go" / "start" / "continue", the agent rereads the same task JSON each loop, executes `next_runnable`, and writes status back.

The board is an A2UI surface using the task-plan domain template documented in
`references/task_board_template.md`. **The JSON task plan is the only source of
truth**: agent writes update the UI; user edits in the UI write back through
`task.patch`; the next `read.py` call sees those edits.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/materialize.py <name> [--summary "..."]` (JSON from stdin) | Create `tasks/<name>.task.json`, write manifest metadata, emit the A2UI surface |
| `scripts/read.py <name-or-path>` | Read task JSON and print tasks + next_runnable |
| `scripts/update.py <name-or-path> <task_id> --state X --notes "..."` | Patch one task field and push an A2UI update |
| `scripts/list.py` | List task file metadata from manifest/stat only |

Scripts print success to stdout. Errors are `ERROR: ...` on stderr with exit 1.

## Dispatch

* `/task-generator <focus>` or natural language "plan a task for X" -> Phase 1.
* `/task-generator` with no args -> run `scripts/list.py`. If the user explicitly asked to execute/continue, confirm the candidate before Phase 2; otherwise show the list and ask which task to operate on.
* `/task-generator <existing-name>` matching `<workspace>/tasks/<name>.task.json` -> ask whether to refine (create `-v2`) or execute.
* User says "execute" / "go" / "start" -> execute the just-created or confirmed task.
* User says "resume" / "continue" / "status" -> run `scripts/list.py`, confirm the target, then `scripts/read.py <name>`.

Never auto-resume from memory. Cross-session resume starts with `list.py`.

## Phase 1 - Create

1. Derive `task_name`: `"-".join(focus.split())`.
2. Build a strictly two-level `task_doc`:

```json
{
  "name": "Human readable task name",
  "version": "2",
  "tasks": [
    {"id": "t-1", "parent_id": "", "title": "Stage", "state": "todo", "description": "", "outcome": "", "criteria": "", "test": "", "notes": ""},
    {"id": "t-1.1", "parent_id": "t-1", "title": "Sub-task", "state": "todo", "description": "...", "outcome": "...", "criteria": "...", "test": "", "notes": ""}
  ]
}
```

3. Pipe JSON to `scripts/materialize.py`; prefer `--summary`:

```bash
python scripts/materialize.py add-login --summary "Implement login" <<'EOTASKDOC'
{
  "name": "Implement login",
  "version": "2",
  "tasks": []
}
EOTASKDOC
```

Success includes `[task-plan:tasks/<name>.task.json]` on stdout. Tell the user the file path and ask them to reply **"execute"/"go"**. Always yield after creation; do not start execution in the same turn.

## Phase 2 - Execute

Start every loop by rereading:

```bash
python scripts/read.py <name-or-path>
```

`read.py` returns:

```json
{
  "path": "tasks/<name>.task.json",
  "name": "...",
  "version": "2",
  "tasks": [{ "id": "t-1", "parent_id": "", "title": "...", "state": "todo", "description": "", "outcome": "", "criteria": "", "test": "", "notes": "" }],
  "next_runnable": { "...": "..." } | null
}
```

Execution rules:

* `next_runnable === null` -> all leaf tasks are terminal; report completion.
* If `next_runnable.state === "in_progress"`, a prior run was interrupted; continue from notes.
* If the user edits title / description / notes / state in the board, the reread sees it. The file wins.
* Mark start: `python scripts/update.py <name> <task_id> --state in_progress`.
* On success: `python scripts/update.py <name> <task_id> --state done --notes "short summary"`.
* On failure: `python scripts/update.py <name> <task_id> --state failed --notes "error + short hypothesis"`, then yield.
* If `task.test` is non-empty, run that shell command after the main work.

## Schema Rules

* ids are `t-N` or `t-N.M`; max depth is 2.
* ids are globally unique.
* child `parent_id` must point to a top-level task.
* states: `todo` / `in_progress` / `done` / `skipped` / `blocked` / `failed`.
* `title` is required and should be a short verb phrase.
* `description` / `outcome` / `criteria` / `test` / `notes` are strings; use `""` when absent.
* Do not invent `test` commands unless the user or repo makes them clear.

## Anti-Patterns

* Do not generate or paste HTML. The task plan is JSON; the UI is an A2UI projection.
* Do not skip the per-loop `read.py`; the user may have edited the board.
* Do not auto-resume; use `list.py` and confirm.
* Do not create `t-1.1.1` or deeper ids.
* Do not add tasks automatically during execution. If scope grows, write notes and let the user decide.
