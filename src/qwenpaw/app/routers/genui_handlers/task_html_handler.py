"""Map task-board A2UI actions onto the existing ``task_html`` library.

Surfaces are addressed as ``task:<workspace-relative path>``. This handler is
the bridge that lets the task board be a *consumer* of the generative-UI
interface: the 5 former ``task-*`` postMessage->REST calls collapse into the
single ``/genui/action`` channel, and every mutation returns the minimal A2UI
patch instead of triggering a full-file reload.
"""
from __future__ import annotations

from pathlib import Path

from ....agents.genui import ClientAction, Envelope
from ....agents.task_html import (
    add_task,
    delete_task,
    parse_task_doc,
    resolve_task_path,
    set_task_field,
    validate,
)
from ....agents.task_html.render import (
    SURFACE_PREFIX,
    field_patch,
    next_state,
    structural_update,
)


def _resolve(workspace: object, surface_id: str) -> Path:
    rel = surface_id[len(SURFACE_PREFIX):]
    resolved = resolve_task_path(Path(workspace.workspace_dir), rel)  # type: ignore[attr-defined]
    if resolved is None:
        raise ValueError(f"invalid task surface path: {rel!r}")
    if not resolved.exists():
        raise ValueError("task file not found")
    return resolved


def _validate_or_raise(html: str) -> None:
    errors = validate(html)
    if errors:
        raise ValueError("; ".join(errors))


def handle(workspace: object, action: ClientAction) -> list[Envelope]:
    resolved = _resolve(workspace, action.surface_id)
    html = resolved.read_text(encoding="utf-8")
    surface_id = action.surface_id
    ctx = action.context

    if action.name == "task.state":
        tid = str(ctx.get("taskId") or "")
        if not tid:
            raise ValueError("task.state requires context.taskId")
        cur = _current_state(html, tid)
        new = next_state(cur)
        html = set_task_field(html, tid, state=new)
        _validate_or_raise(html)
        resolved.write_text(html, encoding="utf-8")
        return [field_patch(surface_id, tid, "state", new)]

    if action.name == "task.delete":
        tid = str(ctx.get("taskId") or "")
        if not tid:
            raise ValueError("task.delete requires context.taskId")
        html = delete_task(html, tid)
        _validate_or_raise(html)
        resolved.write_text(html, encoding="utf-8")
        return structural_update(parse_task_doc(html), surface_id)

    if action.name == "task.add":
        parent_id = str(ctx.get("parentId") or "")
        title = str(ctx.get("title") or "新任务")
        html, _new_id = add_task(html, parent_id, title)
        _validate_or_raise(html)
        resolved.write_text(html, encoding="utf-8")
        return structural_update(parse_task_doc(html), surface_id)

    if action.name == "task.refresh":
        return structural_update(parse_task_doc(html), surface_id)

    raise ValueError(f"unknown task action {action.name!r}")


def _current_state(html: str, task_id: str) -> str:
    for t in parse_task_doc(html).tasks:
        if t.id == task_id:
            return t.state
    raise ValueError(f"task {task_id!r} not found")


# Register for all ``task:`` surfaces.
from . import register  # noqa: E402

register(SURFACE_PREFIX, handle)
