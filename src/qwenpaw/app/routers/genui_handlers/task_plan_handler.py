# -*- coding: utf-8 -*-
"""Map task-board A2UI actions onto the task-plan domain library.

Surfaces are addressed as ``task:<workspace-relative path>``. This handler
makes the task board a normal A2UI consumer: user actions mutate the canonical
``*.task.json`` document, and the returned envelopes update the live surface.
Agent scripts read the same JSON before every execution step, so user edits are
visible without scraping UI state.
"""

from __future__ import annotations

from pathlib import Path

from ....agents.genui import ClientAction, Envelope
from ....agents.task_plan import (
    add_task,
    delete_task,
    parse_task_doc,
    resolve_task_path,
    set_task_field,
    validate,
)
from ....agents.task_plan.render import (
    SURFACE_PREFIX,
    field_patch,
    next_state,
    structural_update,
)


def _resolve(workspace: object, surface_id: str) -> Path:
    rel = surface_id[len(SURFACE_PREFIX) :]
    workspace_dir = Path(getattr(workspace, "workspace_dir"))
    resolved = resolve_task_path(workspace_dir, rel)
    if resolved is None:
        raise ValueError(f"invalid task surface path: {rel!r}")
    if not resolved.exists():
        raise ValueError("task file not found")
    return resolved


def _validate_or_raise(text: str) -> None:
    errors = validate(text)
    if errors:
        raise ValueError("; ".join(errors))


def handle(workspace: object, action: ClientAction) -> list[Envelope]:
    resolved = _resolve(workspace, action.surface_id)
    text = resolved.read_text(encoding="utf-8")
    surface_id = action.surface_id
    ctx = action.context

    if action.name == "task.state":
        tid = str(ctx.get("taskId") or "")
        if not tid:
            raise ValueError("task.state requires context.taskId")
        cur = _current_state(text, tid)
        new = next_state(cur)
        text = set_task_field(text, tid, state=new)
        _validate_or_raise(text)
        resolved.write_text(text, encoding="utf-8")
        return [field_patch(surface_id, tid, "state", new)]

    if action.name == "task.patch":
        tid = str(ctx.get("taskId") or "")
        field = str(ctx.get("field") or "")
        if not tid or not field:
            raise ValueError(
                "task.patch requires context.taskId and context.field",
            )
        value = "" if ctx.get("value") is None else ctx.get("value")
        text = set_task_field(text, tid, **{field: value})
        _validate_or_raise(text)
        resolved.write_text(text, encoding="utf-8")
        return [field_patch(surface_id, tid, field, value)]

    if action.name == "task.delete":
        tid = str(ctx.get("taskId") or "")
        if not tid:
            raise ValueError("task.delete requires context.taskId")
        text = delete_task(text, tid)
        _validate_or_raise(text)
        resolved.write_text(text, encoding="utf-8")
        return structural_update(parse_task_doc(text), surface_id)

    if action.name == "task.add":
        parent_id = str(ctx.get("parentId") or "")
        title = str(ctx.get("title") or "新任务")
        text, _new_id = add_task(text, parent_id, title)
        _validate_or_raise(text)
        resolved.write_text(text, encoding="utf-8")
        return structural_update(parse_task_doc(text), surface_id)

    if action.name == "task.refresh":
        return structural_update(parse_task_doc(text), surface_id)

    raise ValueError(f"unknown task action {action.name!r}")


def _current_state(text: str, task_id: str) -> str:
    for t in parse_task_doc(text).tasks:
        if t.id == task_id:
            return t.state
    raise ValueError(f"task {task_id!r} not found")


# Register for all ``task:`` surfaces.
# pylint: disable=wrong-import-position
from . import register  # noqa: E402

register(SURFACE_PREFIX, handle)
