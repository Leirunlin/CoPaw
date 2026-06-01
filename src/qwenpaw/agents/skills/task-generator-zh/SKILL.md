---
name: task-generator
description: "用此 skill 把一项多步骤工作规划成结构化 HTML 任务图，并逐步执行它。常见触发：「帮我规划一个 task」「拆成 task list 并跑起来」「做这个 task」「继续 task」「resume tasks」以及任意 /task-generator [arg] 调用。产物是 <workspace>/tasks/<name>.html（横向阶段卡片图）；用户在 Workspace 面板审阅/编辑；用户回复「执行」后 agent 才开始逐步执行。"
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

两个明确阶段，**用户只有一个 gate** 在中间：

* **阶段 1 — 创建。** 构造任务 JSON，调用 `scripts/materialize.py`。脚本把 JSON 合并进服务端 HTML 模板，写入 `<workspace>/tasks/<name>.html`，告诉用户位置，**让出回合**。
* **阶段 2 — 执行。** 用户说"执行"/"go"/"execute"/"开始"/"继续" 时，逐步执行任务。

UI 风格、按钮、卡片都由模板决定，LLM **只产 JSON 数据**——不需要 read_file 模板，也不要 echo HTML。

## Scripts 一览

| 脚本 | 用途 |
|------|------|
| `scripts/materialize.py <name> [--summary "..."]` (JSON 从 stdin) | 创建任务 HTML + 写入 manifest 元数据 |
| `scripts/read.py <name>` | 解析 HTML，打印 JSON（tasks + next_runnable）到 stdout |
| `scripts/update.py <name> <task_id> --state X --notes "..."` | 改单个任务字段 |
| `scripts/list.py` | JSON：每个任务的 path / name / summary / created / modified（读 manifest，不解析 HTML） |

所有脚本：成功消息在 stdout，错误 `ERROR: ...` 到 stderr 并 exit 1。

## References

| 文件 | 用途 |
|------|------|
| `references/task_plan_template.html` | UI 模板（CSS + 横向卡片 JS + DOM modal）。`materialize.py` 自动读取并把 `__TASK_NAME__` / `__TASK_DOC_JSON__` 替换掉。**LLM 不需要主动 read_file 它，也不要 echo 到对话或 prompt 里**；只有当用户问「按钮叫什么」「modal 长啥样」等细节时再去读它定位。 |

## Step 0. 判断调用路径

* `/task-generator <focus>`（或自然语言「规划一个做 X 的 task」）→ **阶段 1**。
* `/task-generator` 无参 → 跑 `scripts/list.py`；用户之前说过"执行"，对最新文件走**阶段 2**；否则把列表给用户，问要操作哪一个。
* `/task-generator <existing-name>` 匹配现有 `<workspace>/tasks/<name>.html` → 问用户：精修（重走阶段 1，文件名加 `-v2`）还是执行（阶段 2）？
* 一次创建之后用户说"执行"/"go"/"开始" → 对最新文件走**阶段 2**。
* 用户消息暗示对**已有任务**的状态查询时——"resume" / "继续" / "做到哪了" / "status" / "继续 task"——**先调** `scripts/list.py`，即使你"记得"之前在做什么。manifest 一次给齐所有 task 的身份 + summary；从中挑 resume 候选，问用户确认，再 `scripts/read.py <name>` 取完整 state 进入阶段 2。**不要自动 resume**——和阶段 1 → 阶段 2 一样有用户 gate。

## 阶段 1 — 创建

### Step 1.1 派生 `task_name`

```
task_name = "-".join(focus.split())
```

例：`add login feature` → `add-login-feature`；`重构 登录 流程` → `重构-登录-流程`。

### Step 1.2 构造 task_doc

`task_doc` 是 JSON 对象（**严格 2 级嵌套**）：

```json
{
  "name": "<人类可读的任务名>",
  "version": "2",
  "tasks": [
    {"id": "t-1",   "parent_id": "",    "title": "行前准备调研", "description": "", "outcome": "", "criteria": "", "test": "", "state": "todo"},
    {"id": "t-1.1", "parent_id": "t-1", "title": "签证政策与入境要求", "description": "...", "outcome": "...", "criteria": "...", "test": "", "state": "todo"},
    {"id": "t-2",   "parent_id": "",    "title": "住宿调研",     "state": "todo"}
  ]
}
```

### Step 1.3 调用 `scripts/materialize.py`

**唯一入口：stdin HEREDOC**。把 task_doc JSON 用单引号 HEREDOC 直接喂给脚本（marker 用 `EOTASKDOC`，不用 `EOF`，避免 JSON 里恰好出现一行 `EOF` 导致 heredoc 提前结束）。**强烈建议**带 `--summary "..."`——从用户的 prompt 提一句话意图（manifest 存它，跨 session resume 时 `list.py` 不需要解析 HTML 就能展示）：

```bash
python scripts/materialize.py <task_name> --summary "把旧 session middleware 迁到新签名方案" <<'EOTASKDOC'
{
  "name": "...",
  "version": "2",
  "tasks": [...]
}
EOTASKDOC
```

通过 `execute_shell_command(command=<整段>, cwd="<this_skill_dir>")` 调用. 单引号 marker (`<<'EOTASKDOC'`) 关掉 shell 变量展开，JSON 不会被 `$` 之类字符破坏。**不要**先写临时文件再调脚本——多一次 tool 调用且污染 `/tmp`。`--summary` 可选但**强烈建议**——不传则 manifest 里 summary 为空，跨 session resume 时 agent 拿不到提示。

**成功**：stdout 出现 `[task-html:tasks/<name>.html]`。告诉用户文件位置（提示在 Workspace 面板查看），问他们回复**"执行"/"go"**。**让出回合**。

**失败**：stderr 有 `ERROR: ...`（如 schema 校验失败、文件已存在）。修复后重试，**不**把内部错误原文给用户。

让出之后**不**做任何后续工作。用户的**下一条**消息（"执行"/"go"/"看着不错，跑吧"）才触发阶段 2。

## 阶段 2 — 执行

单一迭代循环。除了失败或用户明确停止，循环内不再额外确认。

### Step 2.1 重新读取文件

```bash
python scripts/read.py <task_name>
```

stdout JSON 结构：

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
  "next_runnable": { ... } | null
}
```

**每轮循环开始都要调用。** 它把用户在 iframe 中做的修改（编辑/删除/新增/状态切换）带回来。

### Step 2.2 挑选下一个任务

* `next_runnable === null` → 所有叶子终态，跳到 **Step 2.5（完成）**。
* 否则 `task = next_runnable`。
* 若 `task.state === "in_progress"`，说明上一次执行被打断了；承认这一点，从 `notes` 提示的位置继续。

### Step 2.3 检测 Undo / 结构修改

若树上有先前 done 的任务现在又是 `state=todo`，而后面的任务仍是 done，说明用户点了状态徽章撤回（或手工编辑）。问用户要从那里重跑还是跳过，**让出**。**不要**自动重跑——可能覆盖已有产出。

若 `tasks` 形状自上次迭代以来变了（数量不一致、出现新 id），简短承认并继续——用户编辑的状态优先。

### Step 2.4 执行一个任务

1. 标记 in_progress：

   ```bash
   python scripts/update.py <task_name> <task_id> --state in_progress
   ```

2. 用合适的工具（`execute_shell_command`、`write_file`、`edit_file`、channel 响应……）做 `task.title` 描述的事。读 `task.description` / `task.outcome` / `task.criteria` 理解细节和验收。
3. 如果 `task.test` 是非空 shell 命令，主要工作完成后用 `execute_shell_command(command=task.test)` 验证。
   * 退出码 0 → 成功。
   * 非零 → 失败（把截断的输出记到 notes）。
4. 成功：

   ```bash
   python scripts/update.py <task_name> <task_id> --state done --notes "一段总结"
   ```

   失败：

   ```bash
   python scripts/update.py <task_name> <task_id> --state failed --notes "错误 + 短假设"
   ```

   失败后**让出**——用户决定是修复重跑、跳过，还是停止。

回到 **Step 2.1**。

### Step 2.5 完成

`next_runnable === null` 时：

1. 扫描 `tasks` 字段，把所有 `failed` / `blocked` 叶子连同其 notes 报告给用户。
2. 告诉用户：文件位于 `<workspace>/tasks/<name>.html`。完成。
3. **不要**删除文件——用户会保留作为记录。

## task_doc Schema 规则

* **2 级限制**：id 只能是 `t-N`（顶层 / 阶段）或 `t-N.M`（子任务）。`t-1.1.1` 之类的 3 级**会被脚本拒绝**。
* **id 唯一**：全文唯一。
* **parent_id**：子任务的 `parent_id` 必须是某个**顶层** task 的 id。顶层 task 的 `parent_id` 是空字符串。
* **state 合法值**：`todo` / `in_progress` / `done` / `skipped` / `blocked` / `failed`。初稿统一 `todo`。
* **title** 必填，短动词短语。
* `description` / `outcome` / `criteria` / `test` / `notes` 都是可选字符串。没有时填空字符串——别填占位文字（"待补充" 之类没用）。
* `test`：用户没明说时**不要瞎编**。

## 并行规则

* **顶层任务（`t-1`、`t-2`、`t-3` …）是串行的。** 在 `t-1` 的所有叶子进入终态（`done` / `skipped`）之前，`t-2` 不会启动。
* **同一父任务下的 sub-task（`t-1.1`、`t-1.2` …）相互独立时可以并行执行。** 当工作能干净地分解成无副作用的小块时，把它们组在同一个父任务下。
* v1 执行时 `next_runnable` 仍按 id 顺序一次返回一个任务。把并行当作**结构性意图**——agent 在安全时可在同一回合批量调 `execute_shell_command`。

## 反模式

* 不要 read_file 任何模板，也不要 echo HTML。**只产 JSON 数据**。
* 不要把渲染后的 HTML 贴到 chat。用户在 Workspace 面板（iframe）或"Open in new tab"中查看。
* **不要**在阶段 1 的同一回合里继续做阶段 2 的事。materialize 后总是让出。阶段 2 由用户触发。
* 执行 Step 2.1 的重新读取**不要**跳过。跳了就毁了"用户能中途改文件"的设计。
* 执行过程中**不要**自动加子任务。如果工作量超出预期，在当前任务的 notes 里记一笔，让用户决定。
* **不要**在 task_doc 里加 `t-1.1.1` 或更深的 id；脚本会拒绝。
* 不要为了找 resume 目标对每个文件循环 `read.py` —— 调一次 `list.py` 从 metadata 里判断。
