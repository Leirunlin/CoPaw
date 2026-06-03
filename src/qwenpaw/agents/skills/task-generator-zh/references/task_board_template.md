# TaskBoard 领域模板

Task plan 不应该用 `Row` / `Column` / `Card` 手工拼 UI。使用单个
`TaskBoard` 根组件，把视觉和交互交给前端模板，A2UI 只承载协议、数据绑定
和 action 名称。

## Surface shape

`createSurface.catalogId`:
`qwenpaw://genui/catalog/task-plan/v1`

```json
{
  "id": "root",
  "component": "TaskBoard",
  "value": { "path": "/" },
  "actions": {
    "state": "task.state",
    "patch": "task.patch",
    "add": "task.add",
    "delete": "task.delete",
    "refresh": "task.refresh"
  }
}
```

## Data model

```json
{
  "name": "Add login",
  "tasks": {
    "t-1": {
      "id": "t-1",
      "parent_id": "",
      "title": "Backend",
      "state": "todo",
      "description": "",
      "outcome": "",
      "criteria": "",
      "test": "",
      "notes": ""
    }
  },
  "taskOrder": ["t-1", "t-1.1"],
  "childrenByParent": {
    "": ["t-1"],
    "t-1": ["t-1.1"]
  },
  "progress": {
    "total": 2,
    "todo": 2,
    "in_progress": 0,
    "done": 0,
    "skipped": 0,
    "blocked": 0,
    "failed": 0
  }
}
```

## Action contract

- `task.state`: context `{ "taskId": "t-1.1" }`
- `task.patch`: context `{ "taskId": "t-1.1", "field": "notes", "value": "..." }`
- `task.add`: context `{ "parentId": "t-1", "title": "新任务" }`
- `task.delete`: context `{ "taskId": "t-1.1" }`
- `task.refresh`: context `{}`

权威状态始终是 `tasks/<name>.task.json`。这个模板只是可视化投影。
