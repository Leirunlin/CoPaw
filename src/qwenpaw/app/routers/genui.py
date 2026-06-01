"""Generative-UI (A2UI) HTTP surface.

One uniform action channel + an emit hook for skill subprocesses + cold-load /
live-stream for renderers:

* ``POST /genui/action``  — a user action on any surface (replaces the 5
  per-feature ``task-*`` postMessage->REST calls). Mutates canonical state via
  the matching handler, broadcasts the resulting A2UI patch to live
  subscribers, and returns it so the acting client applies it immediately
  (works even when no agent run is live).
* ``POST /genui/emit``    — internal: a skill subprocess pushes A2UI envelopes
  (create/update) onto the run stream during agent execution.
* ``GET  /genui/surface`` — cold-load the current surface (server mirror, or
  derived from canonical state on disk) for a late-mounting renderer.
* ``GET  /genui/stream``  — attach to a run's SSE for live surface deltas.

``runKey`` may be a chat id or a session id; it is normalized to the canonical
``chat.id`` the ``task_tracker`` keys runs by.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.responses import JSONResponse, StreamingResponse

from ...agents.genui import (
    SURFACE_STATE,
    ClientAction,
    emit,
)
from ..agent_context import get_agent_for_request
from . import genui_handlers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/genui", tags=["genui"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _normalize_run_key(workspace: Any, candidate: str) -> str:
    """Resolve a chat id / session id to the canonical ``chat.id`` run key."""
    cand = (candidate or "").strip()
    if not cand:
        return cand
    chat_manager = getattr(workspace.runner, "_chat_manager", None)
    if chat_manager is not None:
        try:
            resolved = await chat_manager.get_chat_id_by_session(
                session_id=cand,
                channel="console",
            )
            if resolved:
                return resolved
        except Exception:  # noqa: BLE001 — fall back to the candidate as-is
            logger.debug("run_key resolve failed for %s", cand, exc_info=True)
    return cand


def _derive_task_envelopes(
    workspace: Any,
    surface_id: str,
) -> list[dict[str, Any]]:
    """Build a task surface from its canonical HTML on disk (cold-load fallback
    when the surface is not in the in-memory mirror, e.g. after a restart)."""
    from ...agents.task_html import resolve_task_path
    from ...agents.task_html.render import SURFACE_PREFIX, render_html

    if not surface_id.startswith(SURFACE_PREFIX):
        return []
    rel = surface_id[len(SURFACE_PREFIX):]
    resolved = resolve_task_path(Path(workspace.workspace_dir), rel)
    if resolved is None or not resolved.exists():
        return []
    try:
        return render_html(resolved.read_text(encoding="utf-8"), surface_id)
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# Action (client -> server)
# ---------------------------------------------------------------------------


@router.post("/action", summary="Report a user action on a generative-UI surface")
async def post_action(request: Request, payload: dict = Body(...)) -> JSONResponse:
    workspace = await get_agent_for_request(request)
    try:
        action = ClientAction.from_body(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        envelopes = genui_handlers.dispatch(workspace, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_key = await _normalize_run_key(
        workspace, str(payload.get("runKey") or payload.get("chatId") or ""),
    )
    errors = await emit(workspace.task_tracker, run_key, envelopes)
    return JSONResponse(
        content={"ok": not errors, "errors": errors, "envelopes": envelopes},
    )


# ---------------------------------------------------------------------------
# Emit (skill subprocess -> server -> run stream)
# ---------------------------------------------------------------------------


@router.post("/emit", summary="Push A2UI envelopes onto a run stream")
async def post_emit(request: Request, payload: dict = Body(...)) -> JSONResponse:
    workspace = await get_agent_for_request(request)
    envelopes = payload.get("envelopes")
    if not isinstance(envelopes, list) or not envelopes:
        raise HTTPException(status_code=400, detail="envelopes (non-empty list) required")
    run_key = await _normalize_run_key(workspace, str(payload.get("runKey") or ""))
    errors = await emit(
        workspace.task_tracker,
        run_key,
        envelopes,
        expect_root=bool(payload.get("expectRoot")),
    )
    return JSONResponse(content={"ok": not errors, "errors": errors})


# ---------------------------------------------------------------------------
# Cold-load (renderer mount / reconnect)
# ---------------------------------------------------------------------------


@router.get("/surface", summary="Cold-load the current state of a surface")
async def get_surface(
    request: Request,
    runKey: str = Query(...),
    surfaceId: str = Query(...),
) -> JSONResponse:
    workspace = await get_agent_for_request(request)
    run_key = await _normalize_run_key(workspace, runKey)

    envelopes = SURFACE_STATE.snapshot(run_key, surfaceId)
    if not envelopes:
        envelopes = _derive_task_envelopes(workspace, surfaceId)
        # Seed the mirror so subsequent patches have a base to fold into.
        for env in envelopes:
            SURFACE_STATE.apply(run_key, env)
    return JSONResponse(content={"envelopes": envelopes})


# ---------------------------------------------------------------------------
# Live stream (renderer subscribes to surface deltas)
# ---------------------------------------------------------------------------


@router.get("/stream", summary="Stream live A2UI surface deltas for a run")
async def get_stream(request: Request, runKey: str = Query(...)) -> Any:
    workspace = await get_agent_for_request(request)
    run_key = await _normalize_run_key(workspace, runKey)
    tracker = workspace.task_tracker

    queue = await tracker.attach(run_key)
    if queue is None:
        # No live run — the renderer relies on /surface + action responses.
        return JSONResponse(content={"live": False})

    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, run_key)
        try:
            async for frame in stream_it:
                yield frame
        finally:
            await stream_it.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
