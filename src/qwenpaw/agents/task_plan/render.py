# -*- coding: utf-8 -*-
"""Project a task plan JSON document into an A2UI task board.

FastAPI-free so it is shared by the ``/genui`` router handler and the skill CLI
scripts. The canonical state remains the task JSON on disk; this module only
generates a surface. The data model keys tasks by id so a user edit or agent
progress update is a stable ``updateDataModel`` path-upsert such as
``/tasks/t-1/state``.

The board exposes editable fields through A2UI data bindings. The renderer
updates its local data model while the user types and sends ``task.patch`` on
commit. The handler validates and writes the same task JSON that the agent
reads before every execution step.
"""

from __future__ import annotations

from typing import Any

from .. import genui as g
from .schema import TaskDoc, TaskState

SURFACE_PREFIX = "task:"

# State cycle the board's state button walks through on each click.
_CYCLE = [
    TaskState.TODO.value,
    TaskState.IN_PROGRESS.value,
    TaskState.DONE.value,
]

# Per-task fields exposed in the surface data model.
_DATA_FIELDS = (
    "title",
    "state",
    "description",
    "outcome",
    "criteria",
    "test",
    "notes",
)

_TASK_BOARD_ACTIONS = {
    "state": "task.state",
    "patch": "task.patch",
    "add": "task.add",
    "delete": "task.delete",
    "refresh": "task.refresh",
}


def surface_id_for(rel_path: str) -> str:
    """``tasks/add-login.task.json`` -> ``task:tasks/add-login.task.json``."""
    return f"{SURFACE_PREFIX}{rel_path}"


def next_state(current: str) -> str:
    """Return the next board state; unknown/terminal states restart at todo."""
    try:
        return _CYCLE[(_CYCLE.index(current) + 1) % len(_CYCLE)]
    except ValueError:
        return _CYCLE[0]


def task_data_model(doc: TaskDoc) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    order: list[str] = []
    children_by_parent: dict[str, list[str]] = {}
    counts = {
        "total": 0,
        "todo": 0,
        "in_progress": 0,
        "done": 0,
        "skipped": 0,
        "blocked": 0,
        "failed": 0,
    }
    for t in doc.tasks:
        tasks[t.id] = {f: getattr(t, f, "") for f in _DATA_FIELDS}
        tasks[t.id]["id"] = t.id
        tasks[t.id]["parent_id"] = t.parent_id
        order.append(t.id)
        children_by_parent.setdefault(t.parent_id or "", []).append(t.id)
        counts["total"] += 1
        if t.state in counts:
            counts[t.state] += 1
    return {
        "name": doc.name,
        "tasks": tasks,
        "taskOrder": order,
        "childrenByParent": children_by_parent,
        "progress": counts,
    }


def task_components(_doc: TaskDoc) -> list[g.Component]:
    """Flat component list (adjacency) for the board, root id == ``root``."""
    return [
        {
            "id": "root",
            "component": "TaskBoard",
            "value": g.ref("/"),
            "actions": _TASK_BOARD_ACTIONS,
        },
    ]


def task_to_envelopes(doc: TaskDoc, surface_id: str) -> list[g.Envelope]:
    """Full surface: createSurface + updateComponents + updateDataModel."""
    return [
        g.create_surface(surface_id, catalog_id=g.TASK_PLAN_CATALOG_ID),
        g.update_components(surface_id, task_components(doc)),
        g.update_data_model(surface_id, "/", task_data_model(doc)),
    ]


def structural_update(doc: TaskDoc, surface_id: str) -> list[g.Envelope]:
    """Envelopes to apply after an add/delete (component refresh + data)."""
    return [
        g.update_components(surface_id, task_components(doc)),
        g.update_data_model(surface_id, "/", task_data_model(doc)),
    ]


def field_patch(
    surface_id: str,
    task_id: str,
    field: str,
    value: Any,
) -> g.Envelope:
    """Single-field data patch (e.g. after a state cycle)."""
    return g.update_data_model(surface_id, f"/tasks/{task_id}/{field}", value)
