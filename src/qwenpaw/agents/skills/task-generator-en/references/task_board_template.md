# TaskBoard Domain Template

Task plans should not be hand-built from `Row` / `Column` / `Card`. Use one
`TaskBoard` root component and let the frontend template own the visual and
interaction quality. A2UI carries the protocol, data binding, and action names.

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
- `task.add`: context `{ "parentId": "t-1", "title": "New task" }`
- `task.delete`: context `{ "taskId": "t-1.1" }`
- `task.refresh`: context `{}`

The canonical state remains `tasks/<name>.task.json`. The template is a visual
projection only.
