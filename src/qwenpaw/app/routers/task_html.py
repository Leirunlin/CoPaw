"""Task HTML API endpoints.

UI counterpart to the agent's read/update tools. The iframe reads the
file via :func:`get_file`, posts user mutations through :func:`patch`
/ :func:`delete_task_endpoint` / :func:`add_task_endpoint`, and pulls
updates via the in-iframe Refresh button (no SSE). All write paths
are confined to ``<workspace>/tasks/``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.responses import HTMLResponse, JSONResponse

from ...agents.task_html import (
    MAX_HTML_BYTES,
    add_task,
    delete_task,
    parse_task_doc,
    rel_to_workspace,
    resolve_task_path,
    set_task_field,
    tasks_dir,
    validate,
)
from ...agents.task_html.schema import VALID_STATES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/task_html", tags=["task_html"])

# Fields callers may patch on a single task.
_PATCH_FIELDS = (
    "state",
    "title",
    "description",
    "outcome",
    "criteria",
    "test",
    "notes",
)

# Subset of those that add_task can pre-populate on a new task.
_ADD_EXTRA_FIELDS = (
    "description",
    "outcome",
    "criteria",
    "test",
    "state",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


def _resolve(workspace, path: str) -> Path:
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    resolved = resolve_task_path(Path(workspace.workspace_dir), path)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail="invalid path: must be a relative .html under tasks/",
        )
    return resolved


def _rel(workspace, p: Path) -> str:
    return rel_to_workspace(Path(workspace.workspace_dir), p)


def _read(resolved: Path) -> str:
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _write(resolved: Path, html: str) -> None:
    try:
        resolved.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _validate_or_400(html: str) -> None:
    errors = validate(html)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get(
    "/file",
    summary="Read a task HTML file",
    response_class=HTMLResponse,
)
async def get_file(request: Request, path: str = Query(...)) -> HTMLResponse:
    workspace = await _get_workspace(request)
    return HTMLResponse(content=_read(_resolve(workspace, path)))


@router.get("/list", summary="List task HTML files in workspace")
async def list_files(request: Request) -> JSONResponse:
    workspace = await _get_workspace(request)
    td = tasks_dir(Path(workspace.workspace_dir))
    if not td.exists():
        return JSONResponse(content={"files": []})

    files = []
    for p in sorted(
        (p for p in td.glob("*.html") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        st = p.stat()
        files.append(
            {
                "path": _rel(workspace, p),
                "size": st.st_size,
                "mtime": st.st_mtime,
            },
        )
    return JSONResponse(content={"files": files})


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@router.post("/patch", summary="Patch one task (any combination of fields)")
async def patch(
    request: Request,
    payload: dict = Body(...),
) -> JSONResponse:
    """Apply any combination of state / title / description / outcome /
    criteria / test / notes to a single task."""
    workspace = await _get_workspace(request)
    task_id = payload.get("task_id") or ""
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    fields: dict[str, Any] = {}
    for key in _PATCH_FIELDS:
        if key in payload and payload[key] is not None:
            fields[key] = payload[key]
    if not fields:
        raise HTTPException(
            status_code=400,
            detail=f"provide at least one of {list(_PATCH_FIELDS)}",
        )
    if "state" in fields and fields["state"] not in VALID_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"state must be one of {sorted(VALID_STATES)}",
        )

    resolved = _resolve(workspace, payload.get("path") or "")
    html = _read(resolved)
    try:
        html = set_task_field(html, task_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _validate_or_400(html)
    _write(resolved, html)
    return JSONResponse(content={"ok": True, "path": _rel(workspace, resolved)})


@router.post("/delete", summary="Delete a task (and its descendants)")
async def delete_task_endpoint(
    request: Request,
    payload: dict = Body(...),
) -> JSONResponse:
    workspace = await _get_workspace(request)
    task_id = payload.get("task_id") or ""
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    resolved = _resolve(workspace, payload.get("path") or "")
    try:
        new_html = delete_task(_read(resolved), task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _validate_or_400(new_html)
    _write(resolved, new_html)
    return JSONResponse(content={"ok": True, "path": _rel(workspace, resolved)})


@router.post("/add", summary="Add a new task")
async def add_task_endpoint(
    request: Request,
    payload: dict = Body(...),
) -> JSONResponse:
    """Append a new task under *parent_id* (empty for top level)."""
    workspace = await _get_workspace(request)
    parent_id = payload.get("parent_id") or ""
    title = payload.get("title") or ""
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    extra: dict[str, Any] = {}
    for key in _ADD_EXTRA_FIELDS:
        if key in payload and payload[key] is not None:
            extra[key] = payload[key]
    if "state" in extra and extra["state"] not in VALID_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"state must be one of {sorted(VALID_STATES)}",
        )

    resolved = _resolve(workspace, payload.get("path") or "")
    try:
        new_html, new_id = add_task(_read(resolved), parent_id, title, **extra)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _validate_or_400(new_html)
    _write(resolved, new_html)
    return JSONResponse(
        content={
            "ok": True,
            "path": _rel(workspace, resolved),
            "task_id": new_id,
        },
    )


@router.post("/write", summary="Replace the entire task HTML file")
async def write(
    request: Request,
    payload: dict = Body(...),
) -> JSONResponse:
    """Whole-file replacement (Workspace source-view save)."""
    workspace = await _get_workspace(request)
    html = payload.get("html") or ""
    if not html:
        raise HTTPException(status_code=400, detail="html is required")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"html exceeds {MAX_HTML_BYTES // 1024} KiB",
        )

    _validate_or_400(html)
    try:
        parse_task_doc(html)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved = _resolve(workspace, payload.get("path") or "")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    _write(resolved, html)
    return JSONResponse(content={"ok": True, "path": _rel(workspace, resolved)})
