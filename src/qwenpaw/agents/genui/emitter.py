"""Bridge A2UI envelopes onto qwenpaw's existing SSE transport.

An A2UI server->client message is carried as a ``DataContent`` event whose
``object`` is overridden to ``"a2ui_response"`` (the runtime-reserved
``MessageType.A2UI_RESPONSE``). Two facts make this a zero-new-transport path:

* ``Event.object`` is a free string, and the channel serializes-then-yields
  every event *before* its ``content/message/response`` dispatch switch — so an
  ``a2ui_response`` event flows to the client verbatim and matches no branch.
* ``DataContent.object`` defaults to ``"content"``; we MUST override it, else
  the event trips the DATA-streaming path in ``channels/base.py``.

Delivery reuses the per-run fan-out in ``task_tracker`` (``broadcast``): the
same buffer/replay machinery that backs reconnects also carries surface
updates, so a late or reconnecting renderer replays them for free.
"""
from __future__ import annotations

from typing import Any

from agentscope_runtime.engine.schemas.agent_schemas import (
    DataContent,
    MessageType,
)

from .state import SURFACE_STATE
from .validator import Error, validate_envelope

# The reserved type-name the runtime declares (agent_schemas.MessageType). We
# reference the constant but tolerate older runtimes via the literal fallback.
A2UI_OBJECT = getattr(MessageType, "A2UI_RESPONSE", "a2ui_response")


def build_a2ui_event(
    envelope: dict[str, Any],
    *,
    surface_id: str,
    run_key: str,
) -> DataContent:
    """Wrap one A2UI envelope as an SSE-ready ``DataContent`` event."""
    return DataContent(
        object=A2UI_OBJECT,
        delta=False,
        index=None,
        data={
            "a2ui": envelope,
            "surfaceId": surface_id,
            "runKey": run_key,
        },
    )


def sse_for_envelope(
    envelope: dict[str, Any],
    *,
    surface_id: str,
    run_key: str,
) -> str:
    """Serialize an envelope to a single SSE frame (``data: …\\n\\n``)."""
    event = build_a2ui_event(envelope, surface_id=surface_id, run_key=run_key)
    return f"data: {event.model_dump_json()}\n\n"


def _surface_id_of(envelope: dict[str, Any]) -> str:
    for key in (
        "createSurface",
        "updateComponents",
        "updateDataModel",
        "deleteSurface",
    ):
        inner = envelope.get(key)
        if isinstance(inner, dict) and inner.get("surfaceId"):
            return str(inner["surfaceId"])
    return ""


async def emit(
    tracker: Any,
    run_key: str,
    envelopes: list[dict[str, Any]],
    *,
    expect_root: bool = False,
    validate: bool = True,
) -> list[Error]:
    """Validate, fold into :data:`SURFACE_STATE`, and broadcast envelopes.

    Returns the list of validation errors. Invalid envelopes are skipped (not
    broadcast) so a partially-bad batch still delivers its good frames; the
    caller surfaces the errors (e.g. back to the LLM for self-correction).

    ``tracker`` is the workspace ``task_tracker``; ``run_key`` is the chat/run
    id. If no run is live, ``tracker.broadcast`` returns False and the surface
    still lands in :data:`SURFACE_STATE` for a later snapshot/cold-load.
    """
    errors: list[Error] = []
    for env in envelopes:
        if validate:
            env_errors = validate_envelope(env, expect_root=expect_root)
            if env_errors:
                errors.extend(env_errors)
                continue
        SURFACE_STATE.apply(run_key, env)
        sse = sse_for_envelope(
            env, surface_id=_surface_id_of(env), run_key=run_key,
        )
        await tracker.broadcast(run_key, sse)
    return errors


def envelopes_to_sse(
    run_key: str,
    envelopes: list[dict[str, Any]],
) -> list[str]:
    """Pure helper (no broadcast) — build SSE frames for a batch, e.g. to seed
    a freshly attached queue from a snapshot."""
    return [
        sse_for_envelope(env, surface_id=_surface_id_of(env), run_key=run_key)
        for env in envelopes
    ]
