# QwenPaw OpenUI

[中文](README_zh.md)

Interactive controls, forms and charts inside QwenPaw Chat replies. Text, images and UI can alternate in one answer. Adjusting local controls does not call the model; an explicit submit action continues the conversation.

## Install

Install the built `qwenpaw-openui-0.1.0.zip` package. Node.js and npm are only needed by plugin developers. No additional Python packages or OpenUI API key are required; the plugin uses your existing QwenPaw model configuration.

**Compatibility:** the host must include `chat.codeBlock`, `chat.submit` and `host.openExternalLink` from the companion host API PR. The manifest's `2.2.2b4` floor alone does not guarantee those APIs are present. This development version must be used with that host change; the first public release must set its minimum version to the release that includes the APIs. The frontend checks capabilities before enabling the protocol.

With a compatible QwenPaw service running:

```sh
qwenpaw plugin install /path/to/qwenpaw-openui-0.1.0.zip
```

For offline installation, extract the ZIP and install the contained plugin directory, then start QwenPaw:

```sh
python -m zipfile -e /path/to/qwenpaw-openui-0.1.0.zip /path/to/extracted
qwenpaw plugin install /path/to/extracted/qwenpaw-openui
```

Refresh Chat after installation. This plugin appears in chat; it does not create a separate Apps page. Check installation with `qwenpaw plugin info qwenpaw-openui` and remove it with `qwenpaw plugin uninstall qwenpaw-openui`.

## Try it

Ask a question where changing a value is useful, for example:

> We're planning a barbecue for six people, but the headcount may change. Give me a shopping list whose quantities I can adjust when more friends join.

Your model decides whether to include UI. For a reproducible developer example, [examples/seeds.openui](examples/seeds.openui) provides a slider that updates total experiment runs from 35 to 56 when seeds change from 5 to 8. Only its continue button creates another user message.

## Behavior

- Each `openui-lang` fenced block is an independent program with its own state. Ordinary Markdown stays in its original position.
- UI appears progressively inside an open fence. The official OpenUI parser validates each update; complete constructs are committed while unfinished component arguments keep the previous frame. A closing fence or response completion finalizes the block. Invalid programs show a short error message, never raw source.
- A single Renderer stays mounted through streaming and completion. Controls follow OpenUI’s streaming readiness rules; host actions are blocked until the block finishes. Write root first, declare state next, then define referenced components in display order for early useful output.
- A small library extension keys named child components by their OpenUI statement IDs. When an earlier reference resolves, existing controls keep their identity and local state, including the selected tab. Parsing, component schemas and state management stay with the official runtime.
- Local values survive later text deltas while the block stays mounted. Refreshing or remounting restores the defaults from the saved source. Local changes are not written to workspace files.
- `@ToAssistant` submits its message, explicit context and the submitting form's values as a visible user message. Other local state is not automatically sent. Submissions use the existing queue and preserve composer drafts and attachments.
- `@OpenUrl` allows absolute HTTP(S) links. `@Set` and `@Reset` run locally. Query, Mutation, tool providers, arbitrary JavaScript and patches to previous replies are not enabled.
- The protocol is added only to capable Console requests using the native QwenPaw backend. Other channels, external harnesses and automation do not receive it through this plugin.
- Disabling the plugin restores ordinary code rendering for saved UI fences. To show an inert DSL example while enabled, wrap it in an outer four-backtick `text` fence.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Plugin reports missing host APIs | Install a host build containing the companion API change, then refresh Console. |
| The answer contains only text | UI is optional. Use a task that benefits from interaction and check that the frontend plugin loaded. |
| Source appears instead of a UI | Check that the plugin loaded and the fence language is `openui-lang`. Active UI source is never shown by this plugin. |
| An interface error appears | Ask the assistant to regenerate the interface. Invalid source remains in message history for debugging. |
| A submit action is rejected | Open the original Agent and conversation, wait for Chat to become ready, or make room in the message queue. |
| Local values reset after refresh | Expected: only UI source and explicitly submitted messages are persisted. |
| Local ZIP installation fails while stopped | Extract the archive and install the extracted plugin directory as shown above. |

## Development

Use Python 3.11+ from the QwenPaw development environment and Node `^20.19.0`, `^22.13.0` or `>=24.0.0`. From the QwenPaw repository root:

```sh
npm --prefix plugins/bundle/qwenpaw-openui/frontend ci
npm --prefix plugins/bundle/qwenpaw-openui/frontend test
python -m pytest tests/unit/plugins/test_openui.py -q
python scripts/pack/generate_plugin_metadata.py --only qwenpaw-openui
```

The resulting package is `dist/plugins/bundle/qwenpaw-openui/qwenpaw-openui-0.1.0.zip`. Install that archive or its extracted contents. Installing the source directory after `npm ci` copies development files, because `pack_exclude` applies to ZIP packaging rather than directory installation.

The build emits `dist/index.js` and `dist/system-prompt.txt` from the same pinned OpenUI library. The module shares host React/ReactDOM, embeds scoped CSS and has no unresolved imports. The full catalog costs roughly 3.7 MB of uncompressed JavaScript and 35,000 prompt characters; the package is loaded only for installed frontend plugins.

`frontend/src/qwenpaw-host.d.ts` is a public SDK snapshot, following the host plugin convention. When the host exposes these APIs, the build checks that it matches `console/src/plugins/types/qwenpaw.d.ts`. Refresh the snapshot when adopting an SDK change. Standalone plugin builds do not require the host source tree.

Python dependencies supplied by QwenPaw are not repeated in a requirements file. Add `requirements.txt` only when introducing extra Python packages. npm dependencies belong in the frontend package and lockfile.

Before public release, merge the host API PR and set the minimum host version to its actual release. This plugin currently follows the repository's bundle release pipeline. A separate plugin repository or version-driven release can be introduced later without changing the runtime contract.
