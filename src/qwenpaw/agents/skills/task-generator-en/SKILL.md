---
name: task-generator
description: "Use this skill to plan a multi-step task as a structured HTML task graph and step through it. Triggers on 'plan a task', 'make a task list and run it', 'do this task', 'continue the task', 'resume the task', and on any /task-generator [arg] invocation. Creates <workspace>/tasks/<name>.html (horizontal stages of task cards) from a server-side template; the user reviews / edits it in the Workspace pane; once they say 'execute' the agent steps through the file."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📋"
    requires: {}
---

> **Important:** All `scripts/` paths are relative to this skill directory.
> Run via: `cd {this_skill_dir} && python scripts/<name>.py ...`
> Or pass `cwd` to `execute_shell_command`.

# Task Generator

Two distinct phases, **one user gate** between them:

* **Phase 1 — Create.** Build a task JSON, call `scripts/materialize.py`.
  The script merges that JSON into the server template and writes
  `<workspace>/tasks/<name>.html`. Tell the user where the file is and
  **yield**.
* **Phase 2 — Execute.** When the user says "execute" / "go" / "执行" /
  "开始" / "继续", step through the file.

UI shape, buttons, cards are owned by the template — the LLM **emits
JSON data only**. Don't read any template, don't echo HTML.

## Scripts at a glance

| Script | Purpose |
|--------|---------|
| `scripts/materialize.py <name> [--summary "..."]` (JSON via stdin) | Create the task HTML + record manifest metadata |
| `scripts/read.py <name>` | Parse HTML; print JSON (tasks + next_runnable) to stdout |
| `scripts/update.py <name> <task_id> --state X --notes "..."` | Patch fields on one task |
| `scripts/list.py` | JSON: every task's path / name / summary / created / modified (manifest read, no HTML parse) |

All scripts: success goes to stdout, errors `ERROR: ...` to stderr with
exit 1.

## References

| File | Purpose |
|------|---------|
| `references/task_plan_template.html` | UI template (CSS + horizontal card JS + DOM modal). `materialize.py` reads it automatically and substitutes `__TASK_NAME__` / `__TASK_DOC_JSON__`. **The LLM does NOT need to `read_file` it actively, and must NOT echo it into chat or paste it into a prompt** — only open it when the user asks about UI specifics (e.g. button labels, modal structure). |

## Step 0. Decide the invocation path

* `/task-generator <focus>` (or natural language "plan a task to do X")
  → **Phase 1 (Create)**.
* `/task-generator` with no arg → run `scripts/list.py`; if the user
  previously said "execute", jump to **Phase 2** on the newest file.
  Otherwise tell them which files exist and ask which to act on.
* `/task-generator <existing-name>` matching an existing
  `<workspace>/tasks/<name>.html` → ask the user: refine (Phase 1
  re-create with `-v2` name) or execute (Phase 2)?
* "execute" / "go" / "execute the task" after a recent Create →
  **Phase 2** on the most recent file.
* On any user message implying state inquiry on existing tasks —
  "resume", "continue", "what's left", "做到哪了", "status", "继续
  task" — **call `scripts/list.py` FIRST**, even if you feel you
  remember from earlier turns. The manifest gives every task's
  identifier + summary in one call; pick the resume candidate from
  that JSON, ask the user to confirm, then `scripts/read.py <name>`
  to load full state before stepping through Phase 2. Never resume
  silently — the user gate is the same as Phase 1 → Phase 2.

## Phase 1 — Create

### Step 1.1 Derive `task_name`

```
task_name = "-".join(focus.split())
```

Examples: `add login feature` → `add-login-feature`;
`重构 登录 流程` → `重构-登录-流程`.

### Step 1.2 Build `task_doc`

`task_doc` is a JSON object (**strict 2-level hierarchy**):

```json
{
  "name": "<human-facing task name>",
  "version": "2",
  "tasks": [
    {"id": "t-1",   "parent_id": "",    "title": "Pre-trip research",          "description": "", "outcome": "", "criteria": "", "test": "", "state": "todo"},
    {"id": "t-1.1", "parent_id": "t-1", "title": "Visa + entry requirements",  "description": "...", "outcome": "...", "criteria": "...", "test": "", "state": "todo"},
    {"id": "t-2",   "parent_id": "",    "title": "Lodging research",           "state": "todo"}
  ]
}
```

### Step 1.3 Call `scripts/materialize.py`

**Sole entrypoint: stdin via HEREDOC.** Pipe the `task_doc` JSON into
the script using a single-quoted HEREDOC marker. Use `EOTASKDOC` (not
`EOF`) so that a literal `EOF` line inside the JSON can't terminate
the heredoc early. Pass `--summary "..."` with a single-sentence
intent string derived from the user's prompt — the manifest stores it
so future `list.py` calls (and a possible cross-session resume) can
surface the task without parsing the HTML:

```bash
python scripts/materialize.py <task_name> --summary "Add email/password login to the dashboard" <<'EOTASKDOC'
{
  "name": "...",
  "version": "2",
  "tasks": [...]
}
EOTASKDOC
```

Invoke via `execute_shell_command(command=<whole block>, cwd="<this_skill_dir>")`.
The single-quoted marker (`<<'EOTASKDOC'`) disables shell variable
expansion so `$` characters inside the JSON survive intact. **Do NOT**
write a temp file first and then call the script — that's two tool
calls and pollutes `/tmp`. `--summary` is optional but strongly
recommended; without it the manifest entry's `summary` is empty and
the agent loses the cross-session resume hint.

**Success**: stdout contains `[task-html:tasks/<name>.html]`. Tell the
user the file is at `<workspace>/tasks/<task_name>.html`, surface it in
the Workspace pane, and ask them to reply **"execute" / "go"**.
**YIELD.**

**Failure**: stderr has `ERROR: ...` (e.g. schema validation, file
exists). Fix the dict and retry. Don't surface raw errors to the user
unless trivial.

After yielding, do NOT do any further work. The user's NEXT message
("execute" / "go" / "looks good, run it") triggers Phase 2.

## Phase 2 — Execute

Single iterative loop. No extra confirmation inside the loop except on
failure or explicit user stop.

### Step 2.1 Re-read the file

```bash
python scripts/read.py <task_name>
```

stdout JSON shape:

```json
{
  "path": "tasks/<name>.html",
  "name": "...",
  "version": "2",
  "tasks": [
    {"id":"t-1","parent_id":"","title":"...","state":"todo",
     "description":"...","outcome":"...","criteria":"...","test":"...","notes":"..."},
    ...
  ],
  "next_runnable": {…} | null
}
```

**Call this at the start of every iteration.** It picks up user edits
made in the iframe (edits, deletes, adds, badge clicks).

### Step 2.2 Pick next task

* `next_runnable === null` → every leaf is terminal → **Step 2.5
  (Finish)**.
* Otherwise `task = next_runnable`.
* If `task.state === "in_progress"`, you (or a previous run) left it
  mid-execution; acknowledge that and continue from where the notes
  indicate.

### Step 2.3 Detect undo / structural edit

If a previously-done task is now `state=todo` while later tasks are
still `done`, the user clicked the status badge to undo (or hand-edited).
Ask them whether to re-run from that point or skip. **Yield.** Don't
auto-rerun — re-execution risks overwriting work.

If `tasks` shape changed since last iteration (counts differ, new ids
appeared), acknowledge briefly and continue — the user's edits are
authoritative.

### Step 2.4 Run one task

1. Mark in-progress:

   ```bash
   python scripts/update.py <task_name> <task_id> --state in_progress
   ```

2. Execute the task using regular tools (`execute_shell_command`,
   `write_file`, `edit_file`, channel responses, …). Read
   `task.description` / `task.outcome` / `task.criteria` for the
   details and acceptance bar.
3. If `task.test` is a non-empty shell command, run it via
   `execute_shell_command(command=task.test)` after the main work.
   * Exit 0 → success.
   * Non-zero → failure (record truncated output in notes).
4. On success:

   ```bash
   python scripts/update.py <task_name> <task_id> --state done --notes "one-paragraph summary"
   ```

   On failure:

   ```bash
   python scripts/update.py <task_name> <task_id> --state failed --notes "error + short hypothesis"
   ```

   Failure → **yield** — user decides whether to fix and retry, skip,
   or stop.

Go back to **Step 2.1**.

### Step 2.5 Finish

When `next_runnable === null`:

1. Scan `tasks` for any `failed` / `blocked` leaves. Report them with
   their notes so the user knows what didn't finish.
2. Tell the user: file at `<workspace>/tasks/<name>.html`. Done.
3. Do NOT delete the file — the user keeps it as a record.

## task_doc schema rules

* **2-level limit**: ids may only be `t-N` (top-level / stage) or
  `t-N.M` (sub-task). Anything like `t-1.1.1` is **rejected by the
  script**.
* **Unique ids**: every id appears at most once.
* **parent_id**: a sub-task's `parent_id` MUST point to a top-level
  task; it cannot point to another sub-task. Top-level tasks have
  empty `parent_id`.
* **Valid states**: `todo` / `in_progress` / `done` / `skipped` /
  `blocked` / `failed`. Initial drafts always use `todo`.
* **title** is required, short verb phrase.
* `description` / `outcome` / `criteria` / `test` / `notes` are
  optional strings. Use empty string when absent — don't write
  placeholder text like "TBD".
* `test`: don't invent shell commands the user didn't mention.

## Parallelism rules

* **Top-level tasks (`t-1`, `t-2`, `t-3`, …) are SERIAL.** `t-2` does
  not start until every leaf under `t-1` is in a terminal state
  (`done` / `skipped`). Order top-level tasks so each depends only on
  those before it.
* **Same-parent sub-tasks (`t-1.1`, `t-1.2`, `t-1.3` under `t-1`) MAY
  run in parallel** when independent. Group siblings under one parent
  when the work decomposes into side-effect-free chunks. Sequence them
  under separate parents (`t-1.1` → `t-2.1`) when one output feeds
  the next.
* For v1 execution, `next_runnable` still returns one task at a time
  in id order. Treat parallelism as a structural intent — the agent
  may batch `execute_shell_command` calls in a single turn when safe.

## Anti-patterns

* Don't `read_file` any template or echo HTML. **Emit JSON only.**
* Don't paste the rendered HTML into chat. The user views it in the
  Workspace pane (iframe) or "Open in new tab".
* Don't proceed to Phase 2 in the same turn as Phase 1. Always yield
  after materialize. The user gates Phase 2.
* Don't skip the re-read in Step 2.1. That defeats the "user can edit
  the file mid-flight" design.
* Don't auto-add subtasks during Phase 2. If work explodes, log it in
  the current task's notes and ask the user.
* Don't put 3-level ids (`t-1.1.1`) in task_doc; the script rejects.
* Don't loop `read.py` over every file to find the resume target —
  call `list.py` once and pick from its metadata.
