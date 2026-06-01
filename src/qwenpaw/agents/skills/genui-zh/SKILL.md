---
name: genui
description: "用这个技能给用户展示一个可交互的 UI 界面 —— 表单、确认对话框、选择器、仪表盘、看板 —— 让用户操作(点击、选择、编辑)并把结果回传给你。触发场景:'展示一个可交互表单'、'渲染用户可点击的按钮/选项'、'让用户在界面里确认/选择'、'做一个小仪表盘/面板',以及任意 /genui 调用。它在现有的流上发出声明式 A2UI(v0.10)界面;应用内渲染器用原生组件绘制(无 iframe),并把用户操作回传给你。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🎛️"
    requires: {}
---

> **重要:** 所有 `scripts/` 路径都相对于本技能目录。
> 运行方式:`cd {this_skill_dir} && python scripts/<name>.py ...`
> 或给 `execute_shell_command` 传 `cwd`。

# GenUI —— agent 产出的可交互界面(A2UI v0.10)

你用**声明式 JSON 界面**(A2UI 格式)描述 UI;应用内渲染器用原生组件绘制,并把
用户的操作回传给你。你从不写 HTML 或 React —— 只发出一份扁平的组件列表 + 数据模型,
然后读回操作结果。

这是可复用的「agent 产出交互式 UI + 用户操作」层。用于临时界面(表单、确认、选择器、
仪表盘)。多步任务计划请用专门的 `task-generator` 技能 —— 它本身就是这套接口的一个消费者。

## 循环

1. **编写**:把界面写成 A2UI envelopes(见 `references/a2ui_protocol.md` 和
   `references/examples/` 里的范例)。只能用 `references/catalog.md` 里 vendored 的
   组件 —— 其它的会被拒绝。
2. **发出**:把 envelopes(一个 JSON 数组)管道给 `scripts/emit_surface.py`。脚本会
   按 catalog 校验并把界面推到当前 run 流上;用户立刻看到。
3. **响应**:用户点 `Button`(或其它 action 组件)时,渲染器把 action 回传。你会作为
   普通输入收到 `{name, surfaceId, context}` —— 处理它,然后可选地再发一份更新后的界面
   (一个小 `updateDataModel` 补丁或替换组件)来反映结果。

## 脚本一览

| 脚本 | 用途 |
|--------|---------|
| `scripts/emit_surface.py`(stdin 传 envelopes 的 JSON 数组) | 按 catalog 校验 + 把界面推到 run 流 |

成功输出到 stdout(`OK: ...`);校验失败把 `VALIDATION_FAILED at <path>: <message>`
打到 stderr 并退出 1 —— 修正被指出的字段后重发。

## 编写规则(细节见 `references/`)

* 一个界面是**扁平的组件列表**,每个 `{id, component, ...props}`,按 id 互相引用。
  必须恰有一个组件 `id: "root"`。
* 把文本/值绑定到**数据模型**:`{"path": "/某个指针"}`(RFC-6901)。用
  `updateDataModel {path, value}` 改数据;重发同 `id` 的组件即可替换它。
* 交互放在 `Button.action.event = {name, context}`。`context` 就是用户点击后你收到的
  内容 —— 把你需要据以行动的 id/值放进去。
* 选一个稳定的 `surfaceId`(如 `confirm:deploy-prod`),让后续更新指向同一个界面。

## 最小示例

```bash
cd {this_skill_dir}
python scripts/emit_surface.py <<'EOF'
[
  {"version":"v0.10","createSurface":{"surfaceId":"confirm:deploy","catalogId":"https://a2ui.org/specification/v0_10/catalogs/basic/catalog.json"}},
  {"version":"v0.10","updateComponents":{"surfaceId":"confirm:deploy","components":[
    {"id":"root","component":"Column","children":["q","yes"]},
    {"id":"q","component":"Text","text":"部署到生产环境?","variant":"h4"},
    {"id":"yes","component":"Button","child":"yeslbl","action":{"event":{"name":"confirm.deploy","context":{"env":"prod"}}},"variant":"primary"},
    {"id":"yeslbl","component":"Text","text":"部署"}
  ]}}
]
EOF
```
