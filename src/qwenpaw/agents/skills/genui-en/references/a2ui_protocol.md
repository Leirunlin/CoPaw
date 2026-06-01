# A2UI v0.10 — the subset qwenpaw speaks

A2UI is a declarative format for agent-generated UIs: you send JSON describing
*intent*, the client renders it with trusted native components. Pinned to
**v0.10**. Every envelope carries `"version": "v0.10"` and exactly one message
key.

## Server -> client envelopes (what you emit)

| Envelope | Shape | Meaning |
|---|---|---|
| `createSurface` | `{surfaceId, catalogId}` | Create a surface and begin rendering. Send once per surface. |
| `updateComponents` | `{surfaceId, components: [...]}` | Add/replace components. Re-sending a component with the same `id` **replaces** it. Exactly one component must have `id:"root"`. |
| `updateDataModel` | `{surfaceId, path, value}` | Upsert `value` at RFC-6901 `path` (omit `value` to delete; `path:"/"` = whole model). |
| `deleteSurface` | `{surfaceId}` | Remove the surface. |

`catalogId` is always
`https://a2ui.org/specification/v0_10/catalogs/basic/catalog.json`.

## Components = a flat adjacency list

Components are **not** a nested tree. Each is `{id, component, ...props}`;
parents reference children **by id**:

```json
{"id":"root","component":"Column","children":["title","row1"]}
{"id":"title","component":"Text","text":"Hello"}
```

`root` is the entry point. Layout components (`Row`/`Column`/`List`) take a
`children` id array; `Card` takes a single `child` id; `Button` takes a `child`
id for its label.

## Data binding — DynamicValue

Any bindable prop accepts either a **literal** or a **`{path}` reference** into
the surface data model:

```json
{"id":"t","component":"Text","text":{"path":"/user/name"}}
```

Resolve order: literal as-is; `{"path":"/a/b"}` reads the data model at that
RFC-6901 pointer. Change the value later with
`updateDataModel {path:"/user/name", value:"Ada"}` and bound components
re-render in place — no need to resend components.

## Incremental updates (cheap)

- **Field changed** -> `updateDataModel {path, value}` (one pointer upsert).
- **Structure changed** (added/removed a component) -> `updateComponents` with
  the affected components (id-replacement); the rest stay.

This is simpler than JSON Patch: you either set a path or replace a component by
id.

## Actions (client -> server)

Put interactivity on a component's `action`:

```json
{"id":"go","component":"Button","child":"golbl",
 "action":{"event":{"name":"order.submit","context":{"sku":{"path":"/cart/sku"}}}}}
```

When the user clicks, you receive an action `{name, surfaceId,
sourceComponentId, context}` where every `{path}` in `context` has been
resolved to its real value. Use `name` to dispatch and `context` for the
payload. Respond by emitting an updated surface (or a data patch).

## Rules / gotchas

- Exactly one `root`. Every referenced child id must exist (or be sent in the
  same/next `updateComponents`).
- Only use catalog components (`references/catalog.md`); unknown or not-yet-
  vendored components are rejected with `VALIDATION_FAILED`.
- Keep `surfaceId` stable across updates so they target the same surface.
- Don't inline child components — define each with its own `id` and reference
  it.
