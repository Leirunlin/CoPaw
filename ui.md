# UI / Agent 交互架构 —— AG-UI、A2UI 探索与 qwenpaw 对比

> **这是什么。** 一份压缩、可复用的调研记录:评估是否把 **AG-UI / A2UI** 的思路引入 qwenpaw 的
> "交互式 UI" 能力(今天是 `task_html`;未来是 human-in-the-loop 审批、HTML 点击式反馈、表单、
> 仪表盘等)。记录了 *AG-UI 本质上要求什么*、*A2UI 是什么*、*qwenpaw 当前怎么实现*(带具体代码定位)、
> *差距在哪*、*最便宜的弥补缝隙*,以及**最终的中文落地评估**(见 §9)。
>
> **何时查阅。** 在新建任何"agent 产出交互式 UI + 用户对其操作"的功能前,或重构 `task_html` 前。
> 目标:一套统一抽象,而不是每个功能一套定制实现。
>
> ### 结论速览(一句话)
> - **AG-UI 与 A2UI 不是竞品,是两层,可叠加。** AG-UI = 传输/事件协议(*怎么*把一次 run 流式推给 UI);
>   A2UI = 声明式 UI 内容格式(*UI 长什么样、数据怎么绑、用户怎么操作*)。A2UI 官方 README 明确把
>   AG-UI / A2A / MCP 列为它的**传输层**。
> - **qwenpaw 不需要换核心,也不需要引入 AG-UI SDK。** 它已经有传输(SSE)、run 生命周期+断线重连、
>   多通道输出。它缺的恰好是 AG-UI/A2UI 本质上的两件事:(1) **状态同步进流**(快照+增量);
>   (2) **统一的双向操作契约**。
> - **A2UI 正好就是这两件缺失的事**,而且已被官方规范化、自带 React 渲染器。因此最终建议(§8/§9):
>   **采用 A2UI 的*格式*(走 qwenpaw 现有 SSE 或 MCP 工具结果传输)+ 移植它的 React 渲染器**,而不是
>   自己从零设计一套协议或硬搬 AG-UI 的 JSON Patch 状态模型。

外部仓库(均为本仓库的同级/邻近目录):
- AG-UI 协议 + SDK:`/Users/runlin/Desktop/ag-ui`
- A2UI 官方项目(Google,Apache-2.0):`/Users/runlin/a2ui`
- "michael" 个人助理参考(把 AG-UI 包装成 skill + 有一个能跑的早期 **A2UI** 移植):
  `/Users/runlin/Desktop/michael-main`

---

## 1. AG-UI —— 是什么、本质上要求什么

AG-UI(Agent-User Interaction Protocol,CopilotKit 出品)是一个**开放的、基于事件的协议**,标准化
"AI agent 后端 ↔ 面向用户的前端"之间怎么对话。在 agent 协议栈里:**MCP** 给 agent 工具,**A2A** 让
agent 互相对话,**AG-UI** 把 agent 接进 UI。MIT 许可。传输无关(SSE / WebSocket / 二进制),带一层
中间件做事件格式的宽松适配。

### 它要求的"工作流"本质 —— 三大支柱
把 *"agent 跑一次 → 出最终结果"* 变成 *"围绕一份共享状态的、带类型的、增量的、双向的事件流"*。

1. **一次 run 是一个有边界、可观测、带类型的事件序列。** `RUN_STARTED … RUN_FINISHED / RUN_ERROR`
   (带 `runId` / `threadId`)。agent 做的每件事都作为细粒度流式事件发出,而不是最后甩一个大 blob:
   - 文本:`TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT(delta) → TEXT_MESSAGE_END`
   - 工具(一等公民):`TOOL_CALL_START → TOOL_CALL_ARGS(delta) → TOOL_CALL_END → TOOL_CALL_RESULT`
   - 思考:`THINKING_* / REASONING_*`
2. **状态是一等流式概念,通过 快照 + 增量 同步。** `STATE_SNAPSHOT`(全量)后接 `STATE_DELTA`
   (**JSON Patch,RFC 6902**)做增量;`MESSAGES_SNAPSHOT` 存历史。agent 与 UI 收敛到**同一份共享状态对象**,
   双向保持同步。
3. **UI 是参与者,不是输出汇。** 前端可以声明 agent 能调用的**前端工具**(`TOOL_CALL_REQUEST` →
   客户端执行 → 把结果 POST 回去)、做 **HITL 审批**、补充上下文。交互是双向的,且用同一套统一语义。

### 事件分类法定位(在 `/Users/runlin/Desktop/ag-ui`)
- 事件枚举(~16+ 种):`sdks/typescript/packages/core/src/events.ts`
  (`TEXT_MESSAGE_*`、`TOOL_CALL_*`、`THINKING_*`、`REASONING_*`、`STATE_SNAPSHOT`、`STATE_DELTA`、
  `MESSAGES_SNAPSHOT`、`RUN_STARTED/FINISHED/ERROR`、`STEP_*`、`RAW`、`CUSTOM`…)
- 核心类型/抽象:`sdks/typescript/packages/core/src/{types.ts,index.ts}`
  - `AbstractAgent` —— 基类;`run(input: RunAgentInput) -> Observable<BaseEvent>`(RxJS)。
  - `HttpAgent` —— 标准 HTTP/SSE/二进制客户端,用于连一个 agent 端点。
- 包:`core`、`client`、`encoder`、`proto`、`cli`、**`a2ui-toolkit`**。
- 一个流里允许多个**连续 run**;消息累积,状态跨 run 保留(除非用新 `STATE_SNAPSHOT` 重置)。

### 关键 takeaway
值得借鉴的是**状态模型(快照+增量)**和**双向操作模型**,*而不是* RxJS 的 `HttpAgent` 客户端。
SDK 假设前端自己持有 agent 连接,这跟 qwenpaw 的沙箱 iframe 渲染冲突(见 §3D)。

---

## 2. A2UI —— 声明式 UI 内容层(Google 官方项目)

调研对象:**`/Users/runlin/a2ui`** —— Google 官方 **A2UI** 仓库(Apache-2.0)。完整规范
(`v0_8 → v0_9 → v0_9_1 → v0_10`)、多个渲染器(`react`、`web_core`、`lit`、`angular`、`flutter`、
`markdown`)、agent SDK(`python`、`kotlin`)、MCP 示例、conformance + eval。
这才是那个"真东西";`michael-main/src/a2ui`(见 §2.补)只是它早期的一个手工移植。

### 2.1 重新定位:A2UI 不是 AG-UI 的竞品 —— 二者叠加
- **AG-UI = 传输/事件协议** —— *怎么*把一次 run 流式推给 UI(run 生命周期、`TEXT_MESSAGE_*`、
  `TOOL_CALL_*`、`STATE_SNAPSHOT`/`STATE_DELTA`)。
- **A2UI = 声明式 UI 内容格式** —— agent 生成的 *surface(界面)长什么样、数据怎么绑、用户怎么操作*。
- A2UI 自己的 README(`/Users/runlin/a2ui/README.md:96`)把 **A2A、AG-UI、MCP** 列为它的*传输层*。
  所以"AG-UI vs A2UI"是个伪命题 —— **A2UI 跑在 AG-UI 这类传输之上**。本文前面几节用 AG-UI 的词汇
  描述了那个 gap(状态快照+增量 + 操作契约);**A2UI 就是那个 gap**,而且已规范化、安全优先。

| | **AG-UI**(§1) | **A2UI**(本节) |
|---|---|---|
| 层 | 传输 / 事件流 | UI 内容载荷 |
| 单位 | ~16 种带类型事件 | 一个 *surface* = 扁平组件列表 + 数据模型 |
| 状态同步 | `STATE_DELTA` = **RFC 6902 JSON Patch** | `updateDataModel{path,value}` = **RFC 6901 JSON Pointer 路径 upsert**(更简单) |
| UI 变更 | (随便它载什么) | `updateComponents` = **按 `id` 整体替换组件** |
| 安全 | 不管 | **一等公民**:客户端持有可信*组件目录(catalog)*,agent 只能请求目录里的组件 → "像数据一样安全,像代码一样有表现力";无代码执行 |
| 渲染 | 前端自己定 | 原生渲染器(React/Lit/Angular/Flutter),**不需要 iframe** |
| 客户端耦合 | RxJS `HttpAgent`(前端持有连接) | 传输无关;只需要"成帧的 JSON"能送达 |

### 2.2 A2UI v0.10 数据模型(已对照真实 schema 核验)
规范目录:`/Users/runlin/a2ui/specification/v0_10/`。最新是 **v0.10**。

- **6 种 server→client 消息**(核验自 `specification/v0_10/json/server_to_client.json`):
  `createSurface`(用 `surfaceId` + `catalogId` 初始化 surface)、`updateComponents`(增/替换组件)、
  `updateDataModel`(`{path, value}`)、`deleteSurface`、`callFunction`(调用客户端注册的函数)、
  `actionResponse`(回应一个设置了 `wantResponse` 的客户端 action)。
- **组件 = 扁平列表 + id 引用**,不是嵌套树(对 LLM 友好 + 可增量打补丁)。每个组件:
  `{ id, component: "<Type>", ...props }`,`id:"root"` 是入口。子节点要么 `["id1","id2"]`,要么是
  模板 `{ componentId, path }`(绑定到数据模型里的一个数组)。基础目录 = **18 个组件**
  (`specification/v0_10/catalogs/basic/catalog.json`):Text、Image、Icon、Video、AudioPlayer、Row、
  Column、List、Card、Tabs、Divider、Modal、Button、CheckBox、TextField、DateTimeInput、
  ChoicePicker、Slider。
- **数据绑定 = `DynamicValue` / `DynamicString|Number|Boolean`**(`common_types.json`):任何可绑定的
  属性可接受 (a) **字面量**;(b) **`{path}`** = JSON Pointer(RFC 6901)指向 surface 数据模型;
  (c) **`{call,args,returnType}`** 函数调用。(`a2ui_protocol.md:129`、`:440`。)
- **增量更新不用 JSON Patch。** 两种更简单的机制:
  - *组件:* 重发 `updateComponents`,带一个已存在 `id` 的组件 → 该组件被**整体替换**。渐进式渲染 =
    先发占位,再替换。
  - *数据:* `updateDataModel{path,value}` = **按 JSON Pointer 做 upsert**(存在则替换、不存在则创建、
    省略 `value` 则删除)。`path` 默认 `/`。(`a2ui_protocol.md:245`、`:576`。)
  - (`fast-json-patch` 只出现在 `specification/v*/test/` 测试工具里,**协议本身不用**。)
  - → 这对 qwenpaw **比 AG-UI 的 RFC-6902 增量更契合**:它跟现有的
    `set_task_field(html, task_id, **fields)` 风格(§3D)一致 —— 设一个 path / 替换一个节点。
- **操作契约(client→server)**(`client_to_server.json`):`Button`/输入组件的
  `action.event = { name, context, wantResponse?, responsePath? }`;触发时客户端发
  `{ name, surfaceId, sourceComponentId, timestamp, context, actionId? }`,其中 **`context` 里的
  path 已被解析成真实值**。输入组件本地双向绑定,仅在 action 触发时同步(不是每次按键)。这正是 §5
  里说 qwenpaw 缺的**那套统一双向操作语义** —— 取代 5 个临时的 `task-*` postMessage 类型(§3D)。

### 2.3 渲染器 + 传输集成事实
- **React 渲染器是页面内原生(不用 iframe),~350KB。** `renderers/react`(薄 React 绑定)+
  `renderers/web_core`(共享逻辑;响应式状态用 **Preact signals**,按 path 细粒度重渲)。v0.9 入口
  `A2uiSurface`(`renderers/react/src/v0_9/A2uiSurface.tsx`);宿主提供一个 **Catalog/注册表**,把组件
  类型映射到 React 组件(`renderers/react/src/v0_9/catalog/basic/index.ts`)。自定义组件和
  **"smart wrapper"**(包括把 **iframe** 包起来承载遗留/不可信内容)接入同一套数据绑定/事件系统 ——
  安全由宿主掌控。依赖:`@preact/signals-core`、`zod`、`date-fns`、`markdown-it`;peer `react`/`react-dom`。
- **MCP 传输**(核验自 `samples/mcp/a2ui-over-mcp-recipe/server.py`):A2UI 载荷(一个 v0.x 消息数组)
  作为 **`EmbeddedResource(mimeType="application/a2ui+json")`** 放进工具结果里(`server.py:32,162-166`);
  用户点击则**作为 MCP 工具调用回传** `action(name, context)`(`server.py:172`、`:219`)。→ 对 qwenpaw
  这种"工具中心 ReAct + 重度 MCP"的循环,这是**最自然的集成方式**:把 UI 当工具/资源发出去,把点击
  当工具调用收回来 —— *不需要新增 SSE 事件类型*。
- **Python agent SDK 强耦合 Google ADK**(`agent_sdks/python`,依赖 `google-adk`、`a2a-sdk`、
  `google-genai`):暴露一个 `SendA2uiToClientToolset` 工具,LLM 用 A2UI JSON 调它,按 catalog 校验。
  **不能**直接塞进 agentscope-runtime —— 但*格式*、**validator**、**流式解析器**
  (`a2ui/parser/streaming_v09.py`,能容忍 token 中途被截断)是可复用的概念。conformance 套件在
  `agent_sdks/conformance/suites/*.yaml`。

### 2.补 michael-main 里的早期 A2UI(供交叉参考)
`michael-main` 做了**两件不同的事**,别混:
- **`agui` skill = 纯文档。** `/Users/runlin/Desktop/michael-main/.claude/skills/agui/SKILL.md` 是一篇
  长 markdown,教 Claude 怎么写 AG-UI 的 server/client 代码。它是*agent 知识*,不是运行时基础设施。
- **`src/a2ui/types.ts`(~650 行)= 真正可复用的声明式抽象** —— 一个早期 A2UI 移植:组件 JSON、
  `BoundValue`(字面量 or `/path` 引用)、`Action({name,context})`、消息(`SurfaceUpdate`/
  `DataModelUpdate`/`BeginRendering`/`DeleteSurface`,这是 v0.8 的旧命名)、一份 spec 多渲染器
  (Web React + Telegram)。对照官方 v0.10,概念一致但命名已演进(见 §2.2)。

---

## 3. qwenpaw 现状 —— agent → UI 架构(带代码定位)

后端:**FastAPI + SSE**,基于 `agentscope-runtime`。前端:`console/` 下的 **React 控制台**,聊天用
`@agentscope-ai/chat`。

### A. 事件流 / SSE 传输
- 事件对象来自 `agentscope_runtime` —— schema 是 `Event(object, status, type, …)`,由 **`object`
  字符串**区分(`"message"` / `"content"` / `"response"`),*不是*丰富的枚举。`status` ∈
  `in_progress / completed / created / failed / …`。
- SSE 序列化 + 发送:[src/qwenpaw/app/channels/base.py](src/qwenpaw/app/channels/base.py)
  - `_serialize_event_for_sse()` 在 base.py:879(用 `event.model_dump_json()` base.py:881-882)
  - 以 `yield f"data: {data}\n\n"` 发出(base.py:768-770)
  - 每通道出站回调 `self._enqueue`(base.py:152,经 `set_enqueue` base.py:461 设置)
- Console 通道把一次 run 变成 SSE 串:
  [src/qwenpaw/app/channels/console/channel.py](src/qwenpaw/app/channels/console/channel.py)
  - `async def stream_one(...)` channel.py:333 → `yield f"data: {data}\n\n"` channel.py:404-405
- HTTP 端点:[src/qwenpaw/app/routers/console.py](src/qwenpaw/app/routers/console.py)
  - `POST /console/chat` → `post_console_chat` console.py:142,返回 `StreamingResponse(...,
    media_type="text/event-stream")` console.py:217-219。
  - run 生命周期经 tracker:`attach_or_start` console.py:197、`stream_from_queue` console.py:206;
    `POST /console/chat/stop` console.py:232。

### B. Run 生命周期 + 断线重连(这块 qwenpaw 已经很接近 AG-UI)
[src/qwenpaw/app/runner/task_tracker.py](src/qwenpaw/app/runner/task_tracker.py)
- `_RunState`(task_tracker.py:27)持有每个 run 的 `queues` + `buffer`(缓冲的 SSE 串)。
- 生产者在锁内把每条 SSE 广播给所有订阅队列:
  `async for sse in stream_fn(payload): run.buffer.append(sse); for q in run.queues: q.put_nowait(sse)`
  (task_tracker.py:288-295)。重连时回放 `buffer`;断开后 run 在后台继续。
- 这实际上就是 AG-UI 的"有边界 run + 重连"支柱,已经做好了。

### C. Skills 机制(对"把 UI 能力包成 skill"很重要)
[src/qwenpaw/agents/react_agent.py](src/qwenpaw/agents/react_agent.py)
- 解析 + 注册:`ensure_skills_initialized`(react_agent.py:150)、`resolve_effective_skills`
  (react_agent.py:153)、`_register_skills`(react_agent.py:411)→ `toolkit.register_agent_skill(skill_dir)`
  (react_agent.py:430)。
- **只有 SKILL.md 的 frontmatter(`name` / `description` / `dir`)被注入系统提示。** SKILL.md 正文和
  `references/` **不会**自动加载 —— agent 在需要时**自己用文件工具读**。所以"agent 在需要产出交互式
  内容时自动读取 UI 协议"可以干净地映射成:发一个 description 能在交互式 UI 意图上触发的 skill,把协议
  放进 `references/`。
- `references/` 是**既有惯例** —— `task-generator-{en,zh}` 和 `himalaya-{en,zh}` 都用。skills 在
  [src/qwenpaw/agents/skills/](src/qwenpaw/agents/skills/)(每个 `<name>-en` / `<name>-zh`)。

### D. `task_html` —— 当前的交互功能(也是薄弱点)
**后端库** [src/qwenpaw/agents/task_html/](src/qwenpaw/agents/task_html/) —— 干净、可复用:
- `schema.py`:`Task` dataclass(schema.py:46 —— 字段 `id, parent_id, title, state, description,
  outcome, criteria, test, notes`)、`TaskDoc`(schema.py:59)、`TaskState` 枚举(schema.py:33)、
  常量 `TASK_DOC_SCRIPT_ID = "task-doc"`(schema.py:30)、`DOC_VERSION = "2"`(schema.py:21)、
  `MAX_HTML_BYTES = 2MiB`(schema.py:27)、`TASK_ID_RE`(schema.py:24,`t-N` / `t-N.M`,2 级上限)。
- `parse.py`:规范状态是嵌在 `<script type="application/json" id="task-doc">` 里的 JSON,由
  `_SCRIPT_RE`(parse.py:27)抽取;`parse_task_doc(html) -> TaskDoc`(parse.py:61);
  `find_next_runnable(doc)`(parse.py:120,祖先未阻塞的叶子 todo)。
- `update.py`:字节稳定的变更(解析 JSON → 改扁平列表 → 重新序列化回 script 标签)。
  `set_task_field(html, task_id, **fields)`(update.py:96)、`set_task_state`(update.py:135)、
  `set_task_title`(update.py:148)、`delete_task`(update.py:152)、`add_task`(update.py:200)→
  `(new_html, new_task_id)`、`validate(html) -> list[str]`(update.py:258)。可打补丁字段:
  `_PATCHABLE_FIELDS`(update.py:36)= `{title, state, description, outcome, criteria, test, notes}`。
- `paths.py`:`resolve_task_path` / `tasks_dir` / `rel_to_workspace`(拒绝逃逸,把 `add-login` 映射到
  `<workspace>/tasks/add-login.html`)。`manifest.py`:每工作区软元数据缓存(`tasks/manifest.json`),
  HTML 仍是权威。
- 公共 API 出口:[src/qwenpaw/agents/task_html/__init__.py](src/qwenpaw/agents/task_html/__init__.py)。

**REST 路由** [src/qwenpaw/app/routers/task_html.py](src/qwenpaw/app/routers/task_html.py)
(注册于 routers/__init__.py:34,66)。**头部注释明确写着"通过 iframe 内的 Refresh 按钮拉取更新
(no SSE)"**(task_html.py:6)。
- `GET /task_html/file?path=`(task_html.py:115,裸 HTML)、`GET /task_html/list`(task_html.py:121)、
  `POST /task_html/patch`(task_html.py:150)、`POST /task_html/delete`(task_html.py:189)、
  `POST /task_html/add`(task_html.py:210)、`POST /task_html/write`(task_html.py:249,整文件)。

**前端 viewer**
[console/src/components/TaskHtmlViewer/TaskHtmlViewer.tsx](console/src/components/TaskHtmlViewer/TaskHtmlViewer.tsx)
- 用 `<iframe sandbox="allow-scripts" srcDoc={html}>` 渲染(TaskHtmlViewer.tsx:241-242)。没有
  `allow-same-origin` ⇒ **不透明 origin ⇒ iframe 自己开不了 SSE/WebSocket**(这正是该功能拉取式的原因)。
- 入站消息联合 `IframeMessage`(TaskHtmlViewer.tsx:35-40):`task-action(refresh)`、`task-state-cycle`、
  `task-edit-full`、`task-delete`、`task-add` —— **task 专用,5 个临时类型**。
- `message` 处理器校验 `ev.source === iframe.contentWindow`(TaskHtmlViewer.tsx:191),注册于
  TaskHtmlViewer.tsx:199。
- **每次变更都调 `reload()`**(TaskHtmlViewer.tsx:120)→ `taskHtmlApi.getFile(path)`
  (TaskHtmlViewer.tsx:124)→ **重新拉取并重建整文件的 `srcDoc`**(dispatch 处理 TaskHtmlViewer.tsx:137-185)。
  ← **这个整文件重拉就是薄弱点。**
- API 模块 [console/src/api/modules/taskHtml.ts](console/src/api/modules/taskHtml.ts):`getFile`(:48)、
  `listFiles`(:62)、`patch`(:66)、`deleteTask`(:73)、`addTask`(:80)、`write`(:87)。

**在 iframe 里跑的模板**(归 skill 所有,LLM 从不直接写它):
[src/qwenpaw/agents/skills/task-generator-en/references/task_plan_template.html](src/qwenpaw/agents/skills/task-generator-en/references/task_plan_template.html)
(+ `-zh` 变体)。`__TASK_DOC_JSON__` 注入 `<script id="task-doc">`(template:466)。
- iframe 在内存里持状态:`loadDoc()`(template:485)把内嵌 JSON 解析成 `tasks` 数组;`state = loadDoc()`
  (template:506);refresh 时重读(template:875)。
- 通过 `post()` → `window.parent.postMessage(msg, "*")`(template:549-551)发出 action:
  `task-state-cycle`(template:793)、`task-edit-full`(template:808)、`task-add`(template:846)、
  `task-delete`(template:864)、`task-action/refresh`(template:870)。

**前端的聊天 SSE**(与 task viewer 分离):聊天页通过 `@agentscope-ai/chat` 的 `customFetch`
(`stream: true`)订阅 `/console/chat`(`console/src/pages/Chat/index.tsx`)。`TaskHtmlViewer` 活在
**Workspace 面板**,与这条流**解耦**(纯拉取)。

---

## 4. AG-UI 要求 vs qwenpaw 现状

| 维度 | AG-UI 要求 | qwenpaw 今天 | 差距 |
|---|---|---|---|
| 传输 | 事件流,传输无关 | FastAPI + SSE(agentscope-runtime) | ✅ 对齐 |
| Run 生命周期 | 显式 RUN_*;多 run;重连 | `task_tracker` attach/buffer/replay/stop,后台续跑 | ✅ **已接近** |
| 事件粒度 | ~16 种带类型事件;start/delta/end;工具一等公民 | 粗粒度 `Event(object/status/type)`;工具结果嵌在 message 事件里;无离散 `TOOL_CALL_*` | ⚠️ 更粗 |
| **状态同步** | `STATE_SNAPSHOT` + `STATE_DELTA`(JSON Patch),双向 | **无状态事件**;task 状态在磁盘,UI **重拉整文件**("no SSE") | ❌ **最大差距** |
| **UI 角色** | 同伴:前端工具 / HITL / 上下文,统一语义 | 渲染器 + 旁路 REST;HITL 有但是阻塞式旁路;每功能各接各的 REST + postMessage | ❌ **每功能定制,不统一** |
| 多前端 | 一条流喂所有客户端,中间件适配 | 聊天=SSE;task=REST+iframe;飞书等各自渲染 | ⚠️ 并行管道 |

HITL 现状:工具守卫 / 审批流(`tool_guard_mixin._acting`、`app/approvals.py`)—— 阻塞式异步审批,
没有建模成 UI 声明式响应的流事件。

---

## 5. 本质差距(到底该借什么)

结构上 qwenpaw **离 AG-UI 不远**:有传输、有 run 生命周期+重连、有多通道输出。它缺的恰好是 AG-UI/A2UI
本质上的两件事:

1. **状态进流** —— 用 `快照 + 增量` 在现有 SSE 上同步状态,而不是"存文件 + UI 拉整文件 + 重解析"。这直接
   干掉 `TaskHtmlViewer.reload()` 的整文件重拉。
2. **统一双向操作契约** —— 把 `task-state-cycle / task-edit-full / …`(以及未来的审批 / 点击反馈)收敛成
   **一套**"前端 action / 前端工具"语义,跑在一条流上,这样新交互功能不必各自重造 REST + postMessage。

用户的目标("统一抽象,而不是每功能一套实现")在 AG-UI/A2UI 的词汇里**就等于**这两件事。
**借思路,不吞框架。** —— 而 A2UI(§2)正好把这两件事规范化好了。

---

## 6. 在现有 SSE 上发 `state_delta` 的最便宜缝隙

已确认无需并行基础设施即可实现:
- `Event.object` 是**自由字符串** —— 没有枚举挡着自定义事件类型。console 通道 + HTTP 响应原样序列化并
  yield 任意事件(`_serialize_event_for_sse` base.py:879;`stream_one` channel.py:404)。
- 广播点:`task_tracker` 已经把 SSE 串扇出给所有 run 订阅队列(`run.buffer.append(sse)` +
  `q.put_nowait(sse)` task_tracker.py:293-295)。一个 helper 可以为自定义 `a2ui` / `state_delta`
  事件构造 SSE 串,同样推进 `_runs[run_key].queues`。
- 工具/agent 的"我在哪个 run/session"上下文:
  [src/qwenpaw/app/agent_context.py](src/qwenpaw/app/agent_context.py) —— `get_current_session_id()`
  (agent_context.py:181)、`get_current_agent_id()`(agent_context.py:165)(ContextVar)。

统一流程草图(取代整文件重拉):
```
iframe action  ─postMessage→  宿主(React)
宿主           ─持久化→       后端(改内嵌 JSON 状态,如 set_task_field)
后端           ─state_delta / a2ui 事件(path-upsert)走 run SSE→ 宿主订阅
宿主           ─postMessage {type:"apply-patch", patch}→ iframe
iframe         把 patch 应用到内存 doc(loadDoc 状态)→ 只重渲受影响节点
```
两个方向、两种难度:
- **用户操作的本地 patch(便宜,无需后端/SSE):** 宿主已知刚发出的变更 → 本地应用 + `apply-patch` 注入
  iframe,而不是 `reload()`。纯前端 + 模板改动。
- **agent 执行期推送(需要 §6 缝隙):** Phase-2 推进时,agent 在 run SSE 上发 `a2ui`/`state_delta`;
  Workspace viewer 需要订阅(搭车聊天 SSE 经共享 store,或单独按文件订阅)。

---

## 7. 早期考虑过的设计方向(会话中途的决定,留档)

> **已被 §8 取代。** 下面"自己设计声明式组件 schema + 手搓渲染器"的分支,现在被 **A2UI** 具体回答了:
> A2UI *就是*那套 schema(Google 背书、已规范、自带原生 React 渲染器),它的 **smart-wrapper** 机制还
> 解决了下面 A/B/C 那个悬而未决的渲染目标分叉 —— 保留 `task_html` 的 iframe 并把它*包*成一个 A2UI 组件
> (不迁移)。直接看 §8 / §9 的修订方案。

- **协议范围** —— 两档:
  - *仅管道(低风险):* 只标准化 宿主↔iframe 信封(`<script id="surface-state">` 内嵌 + 统一入站
    `{type:"action", action, params}` + 出站 `{type:"apply-patch", patch}`)。HTML 仍按功能自由写;
    `task_html` 适配。
  - *声明式组件 schema(A2UI 式):* 组件目录 + 通用渲染器 + 数据绑定;agent 发组件 JSON,不发 HTML。
    统一度更高,工作量大得多。
  - **用户选了:声明式组件 schema。**(→ 现在由 A2UI 现成提供。)
- **实时范围** —— *仅用户操作的本地 patch* vs *再加 agent 执行期推送*。
  **用户选了:也要 agent 执行期推送**(双向,经 §6 `state_delta` 缝隙)。
- **悬而未决的分叉(已被 §8 解决):** 声明式 surface 怎么渲染、现有的 `task_html` UI 怎么办 ——
  (A) `console/` 里写原生 React 渲染器跑新 surface,`task_html` **保留** iframe;
  (B) 把组件 JSON → HTML 渲染进现有 iframe;(C) 全声明式,把 `task_html` 也迁成组件。
  → §8.4 的 **smart-wrapper** 给出答案:**包,不迁。**

---

## 8. A2UI → qwenpaw 的修订建议(取代 §7)

采用 **A2UI 的*格式*** 作为 qwenpaw 单一的"agent 产出交互式 UI"抽象 —— 而不是自己设计 schema 或手搬
AG-UI 的 JSON-Patch 状态模型。具体:

1. **协议即 skill**(§7 的 point-1 目标):把 A2UI 消息格式 + 基础 catalog 子集写进某 skill 的
   `references/`(一份精简的 `a2ui_protocol.md` + 几个示例载荷),在交互式 UI 意图上触发。agent 发 A2UI
   JSON;一个小的移植 **validator** 校验。(别搬 ADK toolset。)
2. **走已有传输** —— 不要 AG-UI SDK、不要新管道:
   - *agent 执行期推送:* 把每条 A2UI 消息作为自定义 SSE 事件 `Event.object="a2ui"` 发在现有 run 流上
     (§6 缝隙:`object` 自由字符串,经 `task_tracker` 队列广播)。`updateComponents`(按 id 替换)+
     `updateDataModel`(path upsert)干掉 `TaskHtmlViewer.reload()` 整文件重拉(§3D 薄弱点)。
   - *工具循环变体(新功能首选):* 把 A2UI 作为 MCP/工具结果返回,用户 action 作为工具调用回传 ——
     对齐 recipe 示例,契合 ReAct。
3. **渲染器:** 把 A2UI 的 `react` + `web_core` 渲染器移植进 `console/`,作为新 `surface` 内容的原生
   (无 iframe)渲染路径。新交互功能 = 发 A2UI、收点击 —— 不再每功能一套 REST + postMessage。
4. **`task_html` 原样保留**,之后注册为一个 **smart-wrapper 组件**(它现有的沙箱 iframe + 1100 行模板),
   只采用共享的 状态同步 + action 管道。→ 这解决了 §7 悬而未决的 A/B/C 渲染目标分叉:**包,不迁。**
   一套协议,两个渲染后端(新 surface 用 A2UI 原生组件;task_html 用 iframe-wrapper)。

**不要采用:** Python ADK agent SDK(耦合)、AG-UI 的 RxJS `HttpAgent` 客户端(§3D 的沙箱 iframe 约束
仍在,且 A2UI 原生渲染器本就绕开了它)。

### 8.5 "可纳入内容"清单
| 采用 | 取代 / 启用 | 落在哪 |
|---|---|---|
| A2UI 消息格式(6 类)作为 UI 协议 | "自己写协议"那个任务 | skill `references/` |
| 扁平组件 + JSON-Pointer path-upsert 增量模型 | `TaskHtmlViewer.reload()` 整文件重拉(§3D) | 后端发 + 前端 apply |
| 统一 action 契约 `{name,surfaceId,sourceComponentId,context}` | 5 个临时 `task-*` postMessage;未来 HITL/点击反馈 | 一套语义 |
| A2UI React 渲染器(`react`+`web_core`) | *新* surface 的 iframe 沙箱 / XSS 折腾 | 移植进 `console/` |
| MCP/工具结果传输 + `action` 工具调用 | 为双向 UI 新增 SSE 事件 | 契合 ReAct 循环 |
| 基础 catalog(18 组件)+ **smart-wrapper** | 从零造组件;迁移 task_html | 包住 task_html iframe |
| validator + 流式解析器*概念* | 手搓校验 | 小移植,不要整个 ADK SDK |

### 8.6 `/Users/runlin/a2ui` 关键文件锚点
- 规范(最新):`specification/v0_10/json/{server_to_client,client_to_server,common_types}.json`;
  正文 `specification/v0_10/docs/a2ui_protocol.md`;catalog `specification/v0_10/catalogs/basic/catalog.json`;
  演进 `…/docs/evolution_guide.md`。
- 渲染器:`renderers/react/src/v0_9/{A2uiSurface.tsx,catalog/basic/index.ts}`;
  共享 `renderers/web_core/src/v0_9/state/{surface-model,data-model,component-model}.ts`。
- MCP:`samples/mcp/a2ui-over-mcp-recipe/server.py`(嵌入资源发出 + `action` 工具);
  `samples/mcp/a2ui-in-mcpapps/server/{server.py,smart_editor_agent.py}`。
- Python SDK:`agent_sdks/python/src/a2ui/{adk/send_a2ui_to_client_toolset.py,parser/streaming_v09.py}`;
  conformance `agent_sdks/conformance/suites/*.yaml`。
- README / 理念:`/Users/runlin/a2ui/README.md`(传输层在 `:96`)。

---

## 9. 中文落地评估(本次新增的核心结论)

### 9.0 三个框架/层的区别(一图概览)

| | **AG-UI** | **A2UI** | **qwenpaw 现状** |
|---|---|---|---|
| 本质 | 传输/事件协议("怎么流") | 声明式 UI 内容格式("UI 长啥样、怎么操作") | 自研:SSE 传输 + task_html 内嵌 JSON + iframe 拉取 |
| 解决的问题 | run 流式、状态快照+增量、双向工具 | 安全声明式 UI、跨框架渲染、增量更新 | 任务可视化 + 人工编辑,单一功能定制 |
| 状态模型 | RFC 6902 JSON Patch | RFC 6901 JSON Pointer upsert(更简单) | 无状态事件;UI 重拉整文件 |
| 渲染 | 不管(前端自定) | 原生渲染器,无需 iframe | 沙箱 iframe + srcDoc |
| 与对方关系 | A2UI 的传输层之一 | 跑在 AG-UI/A2A/MCP 之上 | 已具备 AG-UI 的传输/生命周期,缺 A2UI 的内容层 |
| 对 qwenpaw 价值 | **低**(已自有等价物) | **高**(正好补缺口) | —— |

**一句话:** qwenpaw 在"传输层"上已经≈AG-UI,所以 **不值得**为 AG-UI 重构;它缺的是"内容层",
而 **A2UI 正好是内容层**,所以**值得**有选择地纳入 A2UI 的格式与渲染器。

### 9.1 迁移到 qwenpaw 重构前后端逻辑的难度 & 可能性

**结论:整体重构"不值得";有选择地纳入 A2UI 内容层"值得"。** 分层看:

| 重构对象 | 难度 | 值不值得 | 原因 |
|---|---|---|---|
| 后端传输层换成 AG-UI SDK | 高 | ❌ 不值得 | qwenpaw 的 SSE + `task_tracker`(§3A/B)已经覆盖 run 生命周期、缓冲、重连。换 SDK 是平替+破坏稳定性。 |
| 后端"状态进流"(发 A2UI 消息) | **低–中** | ✅ 值得 | `Event.object` 自由字符串(§6),沿用 `task_tracker` 广播即可;新增一个 helper + 一个 validator,**纯增量、可灰度**。 |
| 后端 agent 产出 A2UI(LLM 生成 JSON) | 低 | ✅ 值得 | 走 skill `references/`(§3C 既有机制),不改 agent 内核;不引入 ADK SDK。 |
| 前端引入 A2UI React 渲染器 | **中** | ✅(对*新*功能)值得 | `react`+`web_core` 原生、无 iframe、~350KB(§2.3);`console/` 本就是 React,移植成本可控。 |
| 前端聊天/工作区改造成"一条流喂所有" | 中–高 | ⚠️ 可选 | 收益是统一,但聊天 SSE 与 task 拉取现已能跑;按需做,不阻塞。 |
| 把现有功能(飞书等多通道)全迁声明式 | 高 | ❌ 暂不 | 多通道各自渲染,统一渲染收益不抵成本;A2UI 的多渲染器理念可作长期方向,非当前。 |

**"qwenpaw 的生成式 UI 是否值得?" —— 值得,但要分清"做什么"。**
- 值得的是:**为"agent 即时生成一个可交互界面(表单/审批/仪表盘/确认)"建立一套统一抽象**,用 A2UI 的
  格式 + 渲染器,而不是每个功能再造一遍 `task_html` 那种 REST+postMessage 管道。这正是用户反复强调的
  "统一抽象,不是每功能一个实现"。
- 不值得的是:为了"生成式 UI"去推倒重来后端,或追求"全部 UI 都声明式化"。task_html 这种已经打磨好的
  富交互(1100 行模板)迁成组件,UX 保真风险高、收益低。
- 关键判断:**新功能用 A2UI 原生组件;老功能(task_html)用 smart-wrapper 包住 iframe**,共享同一套
  状态同步 + action 契约。一套协议、两个渲染后端 —— 增量、低风险、可回退。

**前置风险提示:** A2UI 仍是早期预览(v0.8 public,演进到 v0.10),规范明确"expect changes"。若采用,
**锁定一个版本**,把移植的 validator/渲染器当作 vendored 快照,不要追上游。

### 9.2 用 A2UI 重构本 branch 上 `task_html` 的难度 & 建议改动

**总难度:中等;但可拆成"先低后高"两步,第一步几乎零风险。** task_html 的后端库(§3D)已经是干净的
"扁平任务列表 + 按字段 patch",**天然贴合 A2UI 的 `updateDataModel` path-upsert 语义** —— 这是最大的
有利条件。薄弱点只有一个:前端**每次变更都 `reload()` 整文件重拉**(`TaskHtmlViewer.tsx:120/124`)。

#### 建议改动(按优先级)

**第 1 步(强烈建议,低难度、纯增量、可立刻做):干掉整文件重拉,改成局部 patch。**
不引入任何 A2UI 依赖,只借鉴它的 path-upsert 思路:
- 后端:复用现有 `set_task_field` / `set_task_state`(`update.py:96/135`)在改完后,额外返回一条
  **变更描述**(形如 `{path:"/tasks/3/state", value:"done"}`),而不是只回整文件。
- 前端宿主:`TaskHtmlViewer` 在收到 iframe action 后,**不再 `reload()`**,而是把这条 patch
  `postMessage({type:"apply-patch", patch})` 注入 iframe(替换 `TaskHtmlViewer.tsx:137-185` 的
  reload 分支)。
- iframe 模板:`task_plan_template.html` 增加一个 `apply-patch` 消息处理,按 JSON Pointer 改内存
  `state`(`loadDoc()` 结果,template:485/506)并**只重渲受影响节点**,而不是 `loadDoc()` 全量重读
  (template:875)。
- 收益:消除整文件来回 + 重解析 + iframe 重建闪烁;为第 2 步打好"局部更新"地基。
- 风险:**几乎为零** —— 后端 mutation 不变,只是前端少拉一次、模板多一个 handler;失败可回退到 reload。

**第 2 步(可选,中难度):接 agent 执行期推送 + 统一 action 契约。**
- 后端:Phase-2 推进任务时,agent 改字段后经 §6 缝隙发一条 `Event.object="a2ui"` 的
  `updateDataModel` 到 run SSE。
- 前端:让 Workspace 的 `TaskHtmlViewer` 订阅该 run 的 SSE(搭车聊天流经共享 store,或按文件单独订阅),
  收到后走第 1 步同一个 `apply-patch` 通道注入 iframe。
- 同时把 5 个临时 postMessage 类型(`task-state-cycle` 等,§3D)收敛成 A2UI 统一 action 信封
  `{name, surfaceId, sourceComponentId, context}`,为后续 HITL/点击反馈复用同一语义。
- 收益:agent 自动推进时,看板**实时**变化,无需手动 Refresh;且为未来交互功能统一了入口。
- 风险:中 —— 需要前端订阅流的改造 + 模板/宿主的 action 重命名;建议在第 1 步稳定后再做。

**第 3 步(不建议在本 branch 做):把 task_html 整体迁成 A2UI 声明式组件。**
- 即 §7 的方案 C / §8.4 的"不要"。1100 行定制模板迁成 18 组件 catalog,UX 保真风险高、收益低。
- 正确姿势是 §8.4 的 **smart-wrapper**:保留 iframe + 模板,把它注册为一个 A2UI 自定义组件,只让它
  接入共享的状态同步 + action 管道。这样 task_html 既"纳入"了统一抽象,又不动它经过打磨的交互细节。

#### 一句话给本 branch
> **现在就做第 1 步**(局部 patch 替代整文件重拉,纯前端+模板,零风险);**第 2 步**(SSE 推送 + 统一
> action)作为下一个增量;**第 3 步整体迁移不要做**,用 smart-wrapper 把 task_html 包进统一协议即可。
