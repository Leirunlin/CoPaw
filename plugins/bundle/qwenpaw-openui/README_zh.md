# QwenPaw OpenUI

[English](README.md)

在 QwenPaw Chat 的回答中直接使用交互控件、表单和图表。一条回答可以交替显示文字、图片与 UI。调整本地控件不调用模型，点击明确的提交动作才继续对话。

## 安装

安装已经构建的 `qwenpaw-openui-0.1.0.zip`。普通用户不需要 Node.js、npm、额外 Python 包或 OpenUI API key；插件沿用 QwenPaw 已配置的模型。

**兼容要求：** 宿主需要包含配套接口 PR 提供的 `chat.codeBlock`、`chat.submit` 和 `host.openExternalLink`。manifest 的 `2.2.2b4` 下限不能单独保证接口存在。当前开发版须搭配该宿主改动使用；首次公开发布时，应把最低版本设为实际包含接口的发布版本。插件前端会检查能力后再启用协议。

兼容的 QwenPaw 服务运行时，执行：

```sh
qwenpaw plugin install /path/to/qwenpaw-openui-0.1.0.zip
```

离线安装时，先解压，再安装其中的插件目录，之后启动 QwenPaw：

```sh
python -m zipfile -e /path/to/qwenpaw-openui-0.1.0.zip /path/to/extracted
qwenpaw plugin install /path/to/extracted/qwenpaw-openui
```

安装后刷新 Chat。插件在聊天中生效，不会创建独立的 Apps 页面。可通过 `qwenpaw plugin info qwenpaw-openui` 查看安装信息，通过 `qwenpaw plugin uninstall qwenpaw-openui` 卸载。

## 使用

选择调整参数能带来实际帮助的问题，例如：

> 我们准备周末烧烤，先按 6 人列采购清单，人数还没定，最好能随时调整，不用每次重新问你。

模型自行判断是否需要 UI。开发者可用 [examples/seeds.openui](examples/seeds.openui) 做确定性的基础验证：seeds 从 5 调到 8，总实验次数从 35 变为 56；只有继续按钮会创建新用户消息。

## 行为约定

- 每个 `openui-lang` 代码块都是状态独立的完整程序；前后 Markdown 保持原来的位置。
- UI 在代码块尚未闭合时逐步出现。使用 OpenUI 官方解析器校验更新，只提交完整语法片段；组件参数尚未完成时保留上一帧。围栏闭合或回答结束后完成该块；无效程序显示简短错误提示，不直接展示源码。
- 同一个 Renderer 在生成与完成之间持续挂载。控件遵循 OpenUI 的流式就绪规则，宿主动作在该块完成前保持禁用。协议要求先写 root、再声明状态，最后按显示顺序定义引用组件，让有效内容尽早出现。
- 插件通过轻量组件库扩展，按 OpenUI 语句标识保持具名子组件的身份。前方引用补齐时，已有控件保留局部状态，例如用户选中的标签页。解析、组件规范和状态管理继续使用官方运行时。
- 后续文字到达时，仍挂载的 UI 保留局部值；刷新或重新挂载后恢复源码中的初始值，不写入 workspace 文件。
- `@ToAssistant` 将动作文字、显式 context 和本次表单的值作为可见用户消息提交，其他局部状态不会自动上传。动作使用已有聊天队列，保留输入框草稿和附件。
- `@OpenUrl` 仅允许绝对 HTTP(S) 链接，`@Set`、`@Reset` 本地执行。不启用 Query、Mutation、工具 provider、任意 JavaScript 或历史 UI patch。
- 协议仅注入具备能力标记、使用原生 QwenPaw backend 的 Console 请求。其他渠道、外部 harness 和自动任务不通过本插件获得该协议。
- 禁用插件后，历史 UI fence 恢复为普通代码。启用期间若要展示不执行的 DSL 示例，用四个反引号的 `text` 外层代码块包住它。

## 故障排查

| 现象 | 处理方式 |
| --- | --- |
| 插件提示缺少宿主接口 | 使用包含配套接口改动的宿主构建，并刷新 Console。 |
| 回答只有文字 | UI 是可选表达方式。尝试确实需要交互的问题，并确认前端插件加载成功。 |
| 显示源码而非 UI | 确认插件已加载，围栏语言为 `openui-lang`；本插件不会直接展示活动 UI 的源码。 |
| 显示界面错误提示 | 请助手重新生成界面；源码仍保存在消息历史中供调试。 |
| 按钮提交被拒绝 | 回到原 Agent 和会话，等待 Chat 就绪，或清理已满的消息队列。 |
| 刷新后数值重置 | 当前只保存 UI 源码和明确提交的消息，这是预期行为。 |
| 服务停止时无法直接安装本地 ZIP | 按上面的离线步骤解压，安装解压后的插件目录。 |

## 开发与打包

使用 QwenPaw 开发环境中的 Python 3.11+，以及 Node `^20.19.0`、`^22.13.0` 或 `>=24.0.0`。在主仓库根目录执行：

```sh
npm --prefix plugins/bundle/qwenpaw-openui/frontend ci
npm --prefix plugins/bundle/qwenpaw-openui/frontend test
python -m pytest tests/unit/plugins/test_openui.py -q
python scripts/pack/generate_plugin_metadata.py --only qwenpaw-openui
```

产物位于 `dist/plugins/bundle/qwenpaw-openui/qwenpaw-openui-0.1.0.zip`。安装该 ZIP 或其解压目录。不要在运行 `npm ci` 后直接安装源码目录：目录安装会复制开发文件，`pack_exclude` 只作用于 ZIP 打包。

构建使用同一锁定版本的官方组件目录生成 `dist/index.js` 和 `dist/system-prompt.txt`。前端共享宿主 React/ReactDOM，嵌入限定作用范围的 CSS，不留下未解析 import。完整目录约带来 3.7 MB 未压缩 JavaScript 和 3.5 万协议字符；只有安装并加载插件的前端才加载该模块。

`frontend/src/qwenpaw-host.d.ts` 按宿主插件规范保存公开 SDK 的类型快照。当宿主包含所需接口时，构建会检查它与 `console/src/plugins/types/qwenpaw.d.ts` 一致。采用新版 SDK 时同步更新快照；插件独立构建无需宿主源码。

宿主提供的 Python 依赖不重复放进 requirements。仅在引入额外 Python 包时新增 `requirements.txt`；npm 依赖在前端 package 和 lockfile 中管理。

公开发布前须合入宿主接口 PR，并用实际发布版本校准最低宿主版本。当前沿用主仓库 bundle 插件发布流程；后续可以迁往独立插件仓库或增加独立版本发布，而无需改变运行时契约。
