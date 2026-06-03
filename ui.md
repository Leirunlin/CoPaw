# QwenPaw Generative UI Design

This branch uses A2UI as the single abstraction for agent-generated,
interactive UI.

## Philosophy

A2UI is the UI content protocol, not a persistence format. Agents emit JSON
messages that describe surfaces, components, data model updates, and actions.
The client renders those messages with trusted native components. Domain state
belongs to each feature and is projected into A2UI.

For task plans, that means:

```text
tasks/<name>.task.json   # canonical domain state
        ↓
TaskDoc -> A2UI envelopes
        ↓
GenUiSurface native renderer
```

HTML, iframes, and feature-specific REST/postMessage paths are not part of the
task plan implementation.

## A2UI Layer

The reusable GenUI layer owns:

* `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface`
* a server-side surface mirror for cold-load/reconnect
* `/genui/emit` for agent/skill subprocesses
* `/genui/surface` for late-mounted renderers
* `/genui/stream` for live A2UI SSE deltas
* `/genui/action` for client-to-server A2UI actions

Every interactive feature should register a surface provider/action handler
rather than adding feature-specific frontend API modules or REST endpoints.

## Task Plan Consumer

Task plans are one consumer of the GenUI layer.

* Durable files are `tasks/<name>.task.json`.
* Workspace marks them as `kind: "task_plan"`.
* The surface id is `task:tasks/<name>.task.json`.
* `task_plan.render` projects the task JSON into A2UI components and data.
* `task_plan.update` is the only mutation layer for task domain state.

User edits flow through A2UI:

```text
TextField change -> local data model write
blur / enter     -> task.patch action
handler          -> validates + writes tasks/<name>.task.json
handler          -> returns updateDataModel patch
agent read.py    -> sees the same JSON state
```

Agent progress uses the same source of truth:

```text
scripts/update.py -> writes tasks/<name>.task.json
                  -> emits A2UI surface update
Workspace board   -> updates live or cold-loads from JSON
```

## Rules

* Do not persist generated UI as HTML.
* Do not add per-feature REST + postMessage interaction paths.
* Do not treat the in-memory A2UI surface mirror as durable state.
* Do make each feature expose domain mutations through a GenUI action handler.
* Do reread domain state before agent execution steps, because the user may have
  edited the UI.

## Current Renderer Scope

The in-repo renderer is a compact A2UI v0.10 subset. It supports the vendored
Basic catalog subset and local write-through for `TextField`, `CheckBox`, and
`ChoicePicker`. It intentionally remains protocol-compatible with upstream A2UI
so it can be replaced or expanded later without changing task plan semantics.
