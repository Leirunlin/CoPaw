---
name: task-generator
description: "用此 skill 把一项多步骤工作规划成结构化 task plan，并逐步执行它。常见触发：「帮我规划一个 task」「拆成 task list 并跑起来」「做这个 task」「继续 task」「resume tasks」以及任意 /task-generator [arg] 调用。产物是 <workspace>/tasks/<name>.task.json；Workspace 面板用 A2UI 原生看板渲染，用户可在看板里编辑，agent 每轮执行前会重新读取同一份 JSON。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📋"
    requires: {}
---

> **重要：** 所有 `scripts/` 路径都相对于此技能目录。
> 运行方式：`cd {this_skill_dir} && python scripts/<name>.py ...`
> 或使用 `execute_shell_command` 的 `cwd` 参数。

# Task Generator

该 skill 有两个阶段，**用户只有一个 gate** 在中间：

* **阶段 1 — 创建。** 构造 task_doc JSON，调用 `scripts/materialize.py`。脚本把 JSON 写入 `<workspace>/tasks/<name>.task.json`，同时把它投影成 A2UI 看板发到当前 run，然后让出回合。
* **阶段 2 — 执行。** 用户说"执行"/"go"/"开始"/"继续"后，agent 每轮重新读取同一份 task JSON，按 `next_runnable` 执行并写回状态。

看板是 A2UI surface，使用 `references/task_board_template.md` 中定义的
task-plan 领域模板。**JSON task plan 是唯一权威状态**：agent 写入后 UI 更新；
用户在 UI 中编辑 title / description / notes 后，前端通过 `task.patch` 写回
JSON，agent 下一轮 `read.py` 会看到。

## Scripts

| 脚本 | 用途 |
|------|------|
| `scripts/materialize.py <name> [--summary "..."]` (JSON 从 stdin) | 创建 `tasks/<name>.task.json` + 写入 manifest 元数据 + 发出 A2UI surface |
| `scripts/read.py <name-or-path>` | 读取 task JSON，打印 tasks + next_runnable |
| `scripts/update.py <name-or-path> <task_id> --state X --notes "..."` | 修改单个任务字段并推送 A2UI 更新 |
| `scripts/list.py` | 列出 task 文件 metadata；只读 manifest 和文件 stat，不解析任务正文 |

所有脚本：成功消息在 stdout；错误 `ERROR: ...` 到 stderr 并 exit 1。

## 调用路径

* `/task-generator <focus>` 或自然语言「规划一个做 X 的 task」→ **阶段 1**。
* `/task-generator` 无参 → 先跑 `scripts/list.py`。如果用户明确说过"执行/继续"，让用户确认候选后进入阶段 2；否则展示列表并问要操作哪一个。
* `/task-generator <existing-name>` 匹配现有 `<workspace>/tasks/<name>.task.json` → 问用户：精修（重走阶段 1，文件名加 `-v2`）还是执行（阶段 2）。
* 用户说"执行"/"go"/"开始" → 对刚创建或用户确认的 task 进入阶段 2。
* 用户说"resume"/"继续"/"做到哪了"/"status" → 先调 `scripts/list.py`，让用户确认目标，再 `scripts/read.py <name>`。

不要凭记忆自动 resume。跨 session 的入口始终是 `list.py`。

## 阶段 1 — 创建

1. 派生 `task_name`：`"-".join(focus.split())`。
2. 构造严格 2 级嵌套的 `task_doc`：

```json
{
  "name": "人类可读的任务名",
  "version": "2",
  "tasks": [
    {"id": "t-1", "parent_id": "", "title": "阶段名", "state": "todo", "description": "", "outcome": "", "criteria": "", "test": "", "notes": ""},
    {"id": "t-1.1", "parent_id": "t-1", "title": "子任务", "state": "todo", "description": "...", "outcome": "...", "criteria": "...", "test": "", "notes": ""}
  ]
}
```

3. 用 stdin heredoc 调 `scripts/materialize.py`，推荐带 `--summary`：

```bash
python scripts/materialize.py add-login --summary "实现登录能力" <<'EOTASKDOC'
{
  "name": "实现登录能力",
  "version": "2",
  "tasks": []
}
EOTASKDOC
```

成功 stdout 会包含 `[task-plan:tasks/<name>.task.json]`。告诉用户文件位置，并请他们回复**"执行"/"go"**。创建后必须让出回合，不要同一回合继续执行。

## 阶段 2 — 执行

每轮循环开始都要重新读取：

```bash
python scripts/read.py <name-or-path>
```

`read.py` 输出：

```json
{
  "path": "tasks/<name>.task.json",
  "name": "...",
  "version": "2",
  "tasks": [{ "id": "t-1", "parent_id": "", "title": "...", "state": "todo", "description": "", "outcome": "", "criteria": "", "test": "", "notes": "" }],
  "next_runnable": { "...": "..." } | null
}
```

执行规则：

* `next_runnable === null` → 所有叶子终态，进入完成汇报。
* 若返回 `in_progress` 任务，说明上次中断，从 notes 指示的位置继续。
* 若用户在看板里改了 title / description / notes / 状态，重新读取会看到最新内容；以文件为准。
* 标记开始：`python scripts/update.py <name> <task_id> --state in_progress`。
* 完成后写回：`python scripts/update.py <name> <task_id> --state done --notes "简短总结"`。
* 失败时写回：`python scripts/update.py <name> <task_id> --state failed --notes "错误 + 短假设"`，然后让出。
* 若 `task.test` 非空，主要工作完成后执行该 shell 命令作为验证。

## Schema 规则

* id 只能是 `t-N` 或 `t-N.M`，最多 2 级。
* id 全文唯一。
* 子任务 `parent_id` 必须指向顶层任务。
* 合法状态：`todo` / `in_progress` / `done` / `skipped` / `blocked` / `failed`。
* `title` 必填，短动词短语。
* `description` / `outcome` / `criteria` / `test` / `notes` 为空时填空字符串。
* 用户没明确要求时不要编造 `test` 命令。

## 反模式

* 不要生成或粘贴 HTML。task plan 是 JSON；UI 是 A2UI 投影。
* 不要跳过每轮 `read.py`。用户可能刚在看板里编辑过。
* 不要自动 resume；先 `list.py` 并让用户确认。
* 不要自动加深层级或生成 `t-1.1.1`。
* 执行过程中不要自动新增任务；超出预期时写 notes，让用户决定。
