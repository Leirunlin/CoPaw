"""Render a task document as an A2UI surface (the generative-UI view of a task
board). FastAPI-free so it is shared by the ``/genui`` router handler and the
skill CLI scripts (which run as subprocesses and must not import the app).

The canonical state remains the embedded ``task-doc`` JSON on disk; this module
only *projects* it into A2UI envelopes. The data model keys tasks by id (not an
array) so a single field change is a stable ``updateDataModel`` path-upsert
(``/tasks/<id>/state``) rather than an array reshuffle.

v1 board affordances: per-task state-cycle + delete buttons, per-stage and
top-level add buttons, live two-way state binding. Rich inline edit (title /
description via a modal) is deferred until the Modal/form catalog components are
vendored — the agent still authors those fields, and the user edits via source
view in the meantime.
"""
from __future__ import annotations

from typing import Any

from .. import genui as g
from .parse import parse_task_doc
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


def surface_id_for(rel_path: str) -> str:
    """``tasks/add-login.html`` -> ``task:tasks/add-login.html``."""
    return f"{SURFACE_PREFIX}{rel_path}"


def next_state(current: str) -> str:
    """Next state in the board cycle. Unknown/terminal states restart at todo."""
    try:
        return _CYCLE[(_CYCLE.index(current) + 1) % len(_CYCLE)]
    except ValueError:
        return _CYCLE[0]


def task_data_model(doc: TaskDoc) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    for t in doc.tasks:
        tasks[t.id] = {f: getattr(t, f, "") for f in _DATA_FIELDS}
    return {"name": doc.name, "tasks": tasks}


def _task_row(tid: str, *, is_stage: bool) -> list[g.Component]:
    """Components for one task's action row (state button, title, delete)."""
    title_variant = "h5" if is_stage else "body"
    return [
        g.row(
            f"row_{tid}",
            [f"statebtn_{tid}", f"title_{tid}", f"delbtn_{tid}"],
            align="center",
        ),
        g.button(
            f"statebtn_{tid}",
            f"statelbl_{tid}",
            action_name="task.state",
            context={"taskId": tid},
        ),
        g.text(f"statelbl_{tid}", g.ref(f"/tasks/{tid}/state")),
        g.text(f"title_{tid}", g.ref(f"/tasks/{tid}/title"), variant=title_variant),
        g.button(
            f"delbtn_{tid}",
            f"dellbl_{tid}",
            action_name="task.delete",
            context={"taskId": tid},
            variant="borderless",
        ),
        g.text(f"dellbl_{tid}", "✕"),
    ]


def task_components(doc: TaskDoc) -> list[g.Component]:
    """Flat component list (adjacency) for the board, root id == ``root``."""
    by_parent: dict[str, list[str]] = {}
    for t in doc.tasks:
        by_parent.setdefault(t.parent_id or "", []).append(t.id)

    components: list[g.Component] = []
    stage_ids = by_parent.get("", [])

    board_children: list[str] = []
    for sid in stage_ids:
        components += _task_row(sid, is_stage=True)
        stage_body_children = [f"row_{sid}"]
        for cid in by_parent.get(sid, []):
            components += _task_row(cid, is_stage=False)
            stage_body_children.append(f"row_{cid}")
        # Per-stage "add sub-task" affordance.
        stage_body_children.append(f"addbtn_{sid}")
        components.append(
            g.button(
                f"addbtn_{sid}",
                f"addlbl_{sid}",
                action_name="task.add",
                context={"parentId": sid},
                variant="borderless",
            ),
        )
        components.append(g.text(f"addlbl_{sid}", "+ 子任务"))
        components.append(g.column(f"stagebody_{sid}", stage_body_children))
        components.append(g.card(f"stage_{sid}", f"stagebody_{sid}"))
        board_children.append(f"stage_{sid}")

    # Top-level "add stage" affordance.
    components.append(
        g.button(
            "addstage",
            "addstagelbl",
            action_name="task.add",
            context={"parentId": ""},
            variant="primary",
        ),
    )
    components.append(g.text("addstagelbl", "+ 阶段"))
    board_children.append("addstage")

    header_text = doc.name or "任务"
    components.append(g.text("header", header_text, variant="h3"))
    components.append(g.column("board", board_children))
    components.append(g.column("root", ["header", "board"]))
    return components


def task_to_envelopes(doc: TaskDoc, surface_id: str) -> list[g.Envelope]:
    """Full surface: createSurface + updateComponents + updateDataModel."""
    return [
        g.create_surface(surface_id),
        g.update_components(surface_id, task_components(doc)),
        g.update_data_model(surface_id, "/", task_data_model(doc)),
    ]


def render_html(html: str, surface_id: str) -> list[g.Envelope]:
    """Convenience: parse task HTML then project to envelopes."""
    return task_to_envelopes(parse_task_doc(html), surface_id)


def structural_update(doc: TaskDoc, surface_id: str) -> list[g.Envelope]:
    """Envelopes to apply after an add/delete (component refresh + data)."""
    return [
        g.update_components(surface_id, task_components(doc)),
        g.update_data_model(surface_id, "/", task_data_model(doc)),
    ]


def field_patch(surface_id: str, task_id: str, field: str, value: Any) -> g.Envelope:
    """Single-field data patch (e.g. after a state cycle)."""
    return g.update_data_model(surface_id, f"/tasks/{task_id}/{field}", value)
