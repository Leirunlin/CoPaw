---
name: genui
description: "Use this skill to show the user an interactive UI surface — a form, a confirmation dialog, a choice picker, a dashboard, a board — that they can act on (click, choose, edit) and have the result come back to you. Triggers on 'show an interactive form', 'render buttons/choices the user can click', 'ask the user to confirm/choose in the UI', 'build a small dashboard/panel', and on any /genui invocation. Emits a declarative A2UI (v0.10) surface over the existing stream; the in-app renderer draws it natively (no iframe) and routes user actions back to you."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🎛️"
    requires: {}
---

> **Important:** All `scripts/` paths are relative to this skill directory.
> Run via: `cd {this_skill_dir} && python scripts/<name>.py ...`
> Or pass `cwd` to `execute_shell_command`.

# GenUI — agent-authored interactive surfaces (A2UI v0.10)

You describe a UI as a **declarative JSON surface** (the A2UI format); the
in-app renderer draws it with native components and posts the user's actions
back to you. You never write HTML or React — you emit a flat list of components
+ a data model, and read back action results.

This is the reusable "agent produces interactive UI + user acts on it" layer.
Use it for ad-hoc surfaces (forms, confirmations, pickers, dashboards). For
domain-specific workflows, use the dedicated consumer skill for that workflow;
it can reuse this same interface while owning its own template and state rules.

## The loop

1. **Author** a surface as A2UI envelopes (see `references/a2ui_protocol.md`
   and the worked examples in `references/examples/`). Only use components from
   the vendored catalog in `references/catalog.md` — anything else is rejected.
2. **Emit** it: pipe the envelopes (a JSON array) to `scripts/emit_surface.py`.
   The script validates against the catalog and pushes the surface onto the
   current run stream; the user sees it immediately.
3. **React** to actions: when the user clicks a `Button` (or another action
   component), the renderer POSTs an action back. You receive it as normal
   input describing `{name, surfaceId, context}` — handle it, then optionally
   emit an updated surface (a small `updateDataModel` patch or replaced
   components) to reflect the result.

## Scripts at a glance

| Script | Purpose |
|--------|---------|
| `scripts/emit_surface.py` (JSON array of envelopes via stdin) | Validate against the catalog + push the surface onto the live run stream |

Success goes to stdout (`OK: ...`); validation errors print
`VALIDATION_FAILED at <path>: <message>` to stderr with exit 1 — fix the
reported field and re-emit.

## Authoring rules (read `references/` for detail)

* A surface is a **flat list of components**, each `{id, component, ...props}`,
  referenced by id. Exactly one component must have `id: "root"`.
* Bind text/values to a **data model** with `{"path": "/some/pointer"}`
  (RFC-6901). Update data with `updateDataModel {path, value}`; replace a
  component by re-sending it with the same `id`.
* Put interactivity on `Button.action.event = {name, context}`. The `context`
  is what you receive back when the user clicks — include the ids/values you
  need to act on.
* Pick a stable `surfaceId` (e.g. `confirm:deploy-prod`) so updates target the
  same surface.

## Minimal example

```bash
cd {this_skill_dir}
python scripts/emit_surface.py <<'EOF'
[
  {"version":"v0.10","createSurface":{"surfaceId":"confirm:deploy","catalogId":"https://a2ui.org/specification/v0_10/catalogs/basic/catalog.json"}},
  {"version":"v0.10","updateComponents":{"surfaceId":"confirm:deploy","components":[
    {"id":"root","component":"Column","children":["q","yes"]},
    {"id":"q","component":"Text","text":"Deploy to production?","variant":"h4"},
    {"id":"yes","component":"Button","child":"yeslbl","action":{"event":{"name":"confirm.deploy","context":{"env":"prod"}}},"variant":"primary"},
    {"id":"yeslbl","component":"Text","text":"Deploy"}
  ]}}
]
EOF
```
