# Vendored catalog subset (v0.10 Basic)

Only these Basic components render today. The validator rejects anything else (the
deferred Basic components — Image, Video, AudioPlayer, Tabs, Modal,
DateTimeInput, Slider — are not vendored yet). Keep this list in sync with
`qwenpaw.agents.genui.catalog.BASIC_COMPONENTS`.

`Dyn` = a DynamicValue (literal or `{"path":"…"}`).

| component | required props | optional props | notes |
|---|---|---|---|
| `Text` | `text: Dyn` | `variant: h1..h5 \| caption \| body` | Display text. Simple Markdown ok. |
| `Row` | — | `children: [id]`, `align: start\|center\|end\|stretch` | Horizontal layout. |
| `Column` | — | `children: [id]`, `align: …` | Vertical layout. |
| `List` | — | `children: [id]` | Vertical list of child ids. |
| `Card` | `child: id` | — | Wraps a single child (use a Row/Column to hold many). |
| `Divider` | — | — | Horizontal rule. |
| `Button` | `child: id`, `action: {event:{name, context}}` | `variant: default\|primary\|borderless` | Fires an action on click. `child` is usually a `Text`. |
| `CheckBox` | `label: Dyn`, `value: Dyn(boolean)` | — | Checkbox with label. |
| `TextField` | — | `label: Dyn`, `value: Dyn` | Single-line input (display/seed value). |
| `ChoicePicker` | — | `value: Dyn`, `options: [{label,value}]` | Dropdown selection. |
| `Icon` | — | `name`/`icon: string` | Renders a glyph/emoji string. |

## Composition tips

- A labeled button = `Button{child: someText}` + a `Text` with the label.
- A titled panel = `Card{child: col}` where `col` is a `Column` of rows.
- Group form fields in a `Column`; put a submit `Button` at the end whose
  `action.context` carries the field `{path}` bindings you need.
