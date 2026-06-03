# -*- coding: utf-8 -*-
"""Generative-UI interface for qwenpaw, modeled on the A2UI v0.10 content
format and delivered over the existing SSE transport.

This package is the reusable "agent produces interactive UI + user acts on it"
abstraction. It owns the A2UI envelope/component builders, a catalog-aware
validator, the server-side surface mirror, and the emitter that rides the
``task_tracker`` fan-out. The first consumer is the task board (see the
``task-generator`` skill + ``routers/genui_handlers/task_plan_handler.py``);
new interactive features register an action handler instead of building their
own REST + postMessage pipeline.

Pinned to A2UI ``v0.10`` (see :mod:`.catalog`); do not track upstream.
"""

from .catalog import (
    A2UI_VERSION,
    ALLOWED_COMPONENTS,
    BASIC_COMPONENTS,
    BASIC_CATALOG_ID,
    DEFERRED_COMPONENTS,
    DOMAIN_COMPONENTS,
    ROOT_ID,
    TASK_PLAN_CATALOG_ID,
)
from .emitter import (
    A2UI_OBJECT,
    build_a2ui_event,
    emit,
    envelopes_to_sse,
    sse_for_envelope,
)
from .protocol import (
    ClientAction,
    Component,
    Envelope,
    action_response,
    button,
    card,
    checkbox,
    column,
    create_surface,
    delete_surface,
    divider,
    list_,
    ref,
    row,
    text,
    text_field,
    update_components,
    update_data_model,
)
from .state import (
    SURFACE_STATE,
    SurfaceStateManager,
    pointer_delete,
    pointer_get,
    pointer_upsert,
    split_pointer,
)
from .validator import Error, first_error_message, validate_envelope

__all__ = [
    "A2UI_OBJECT",
    "A2UI_VERSION",
    "ALLOWED_COMPONENTS",
    "BASIC_COMPONENTS",
    "BASIC_CATALOG_ID",
    "ClientAction",
    "Component",
    "DEFERRED_COMPONENTS",
    "DOMAIN_COMPONENTS",
    "Envelope",
    "Error",
    "ROOT_ID",
    "SURFACE_STATE",
    "SurfaceStateManager",
    "TASK_PLAN_CATALOG_ID",
    "action_response",
    "build_a2ui_event",
    "button",
    "card",
    "checkbox",
    "column",
    "create_surface",
    "delete_surface",
    "divider",
    "emit",
    "envelopes_to_sse",
    "first_error_message",
    "list_",
    "pointer_delete",
    "pointer_get",
    "pointer_upsert",
    "ref",
    "row",
    "split_pointer",
    "sse_for_envelope",
    "text",
    "text_field",
    "update_components",
    "update_data_model",
    "validate_envelope",
]
