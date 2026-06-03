# -*- coding: utf-8 -*-
"""A2UI v0.10 envelope + component builders, and the inbound action model.

Envelopes are the canonical JSON wire form, so the builders here return plain
``dict``s and stay transport/framework agnostic.
We keep a thin :class:`ClientAction` dataclass for the *inbound* direction
because it is parsed out of an HTTP request body and benefits from typing.

Server -> client messages (A2UI v0.10 ``server_to_client.json``):
    createSurface, updateComponents, updateDataModel, deleteSurface,
    callFunction, actionResponse.
Client -> server (``client_to_server.json``): action, functionResponse, error.

This module only builds the subset qwenpaw emits today (createSurface,
updateComponents, updateDataModel, deleteSurface, actionResponse). callFunction
is intentionally omitted from the v1 surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .catalog import A2UI_VERSION, BASIC_CATALOG_ID

# A2UI component / envelope dicts are arbitrary JSON.
Component = dict[str, Any]
Envelope = dict[str, Any]


# ---------------------------------------------------------------------------
# Server -> client envelope builders
# ---------------------------------------------------------------------------


def create_surface(
    surface_id: str,
    *,
    catalog_id: str = BASIC_CATALOG_ID,
    theme: Optional[dict[str, Any]] = None,
) -> Envelope:
    """Tell the client to create a new surface and begin rendering."""
    inner: dict[str, Any] = {"surfaceId": surface_id, "catalogId": catalog_id}
    if theme is not None:
        inner["theme"] = theme
    return {"version": A2UI_VERSION, "createSurface": inner}


def update_components(
    surface_id: str,
    components: list[Component],
) -> Envelope:
    """Add/replace components on a surface. Exactly one component across the
    surface's accumulated set must have ``id == "root"`` (the validator and the
    :class:`~.state.SurfaceStateManager` enforce/track this)."""
    return {
        "version": A2UI_VERSION,
        "updateComponents": {
            "surfaceId": surface_id,
            "components": components,
        },
    }


def update_data_model(
    surface_id: str,
    path: str = "/",
    value: Any = None,
    *,
    delete: bool = False,
) -> Envelope:
    """Upsert (or delete) a value in the surface data model by RFC-6901 path.

    ``delete=True`` omits ``value`` from the envelope, which the A2UI client
    interprets as "remove the key at ``path``".
    """
    inner: dict[str, Any] = {"surfaceId": surface_id, "path": path}
    if not delete:
        inner["value"] = value
    return {"version": A2UI_VERSION, "updateDataModel": inner}


def delete_surface(surface_id: str) -> Envelope:
    return {
        "version": A2UI_VERSION,
        "deleteSurface": {"surfaceId": surface_id},
    }


def action_response(
    action_id: str,
    *,
    value: Any = None,
    error: Optional[dict[str, str]] = None,
) -> Envelope:
    """Respond to a client action that set ``wantResponse``."""
    inner: dict[str, Any] = {}
    if error is not None:
        inner["error"] = error
    else:
        inner["value"] = value
    return {
        "version": A2UI_VERSION,
        "actionId": action_id,
        "actionResponse": inner,
    }


# ---------------------------------------------------------------------------
# DynamicValue helpers (literal | {path} | {call})
# ---------------------------------------------------------------------------


def ref(path: str) -> dict[str, str]:
    """A data-model binding: ``{"path": "/tasks/0/title"}`` (RFC-6901)."""
    return {"path": path}


# ---------------------------------------------------------------------------
# Component builders (vendored subset). Each returns ``{id, component, ...}``.
# ---------------------------------------------------------------------------


def text(
    component_id: str,
    value: Any,
    *,
    variant: Optional[str] = None,
) -> Component:
    c: Component = {"id": component_id, "component": "Text", "text": value}
    if variant is not None:
        c["variant"] = variant
    return c


def column(
    component_id: str,
    children: list[str],
    *,
    align: Optional[str] = None,
) -> Component:
    c: Component = {
        "id": component_id,
        "component": "Column",
        "children": children,
    }
    if align is not None:
        c["align"] = align
    return c


def row(
    component_id: str,
    children: list[str],
    *,
    align: Optional[str] = None,
) -> Component:
    c: Component = {
        "id": component_id,
        "component": "Row",
        "children": children,
    }
    if align is not None:
        c["align"] = align
    return c


def card(component_id: str, child: str) -> Component:
    return {"id": component_id, "component": "Card", "child": child}


def divider(component_id: str) -> Component:
    return {"id": component_id, "component": "Divider"}


def button(
    component_id: str,
    child: str,
    *,
    action_name: str,
    context: Optional[dict[str, Any]] = None,
    variant: Optional[str] = None,
    want_response: bool = False,
) -> Component:
    event: dict[str, Any] = {"name": action_name, "context": context or {}}
    if want_response:
        event["wantResponse"] = True
    c: Component = {
        "id": component_id,
        "component": "Button",
        "child": child,
        "action": {"event": event},
    }
    if variant is not None:
        c["variant"] = variant
    return c


def checkbox(component_id: str, label: Any, value: Any) -> Component:
    return {
        "id": component_id,
        "component": "CheckBox",
        "label": label,
        "value": value,
    }


def text_field(
    component_id: str,
    *,
    label: Any = None,
    value: Any = None,
    action_name: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> Component:
    c: Component = {"id": component_id, "component": "TextField"}
    if label is not None:
        c["label"] = label
    if value is not None:
        c["value"] = value
    if action_name is not None:
        c["action"] = {
            "event": {"name": action_name, "context": context or {}},
        }
    return c


def list_(
    component_id: str,
    *,
    children: Optional[list[str]] = None,
    template: Optional[dict[str, str]] = None,
) -> Component:
    """A List rendered either from an explicit ``children`` id array or from a
    ``template`` ``{componentId, path}`` bound to a data-model array."""
    c: Component = {"id": component_id, "component": "List"}
    if template is not None:
        c["children"] = template
    elif children is not None:
        c["children"] = children
    return c


# ---------------------------------------------------------------------------
# Inbound: client -> server action
# ---------------------------------------------------------------------------


@dataclass
class ClientAction:
    """A user-initiated action reported by the renderer (after data bindings in
    ``context`` are resolved to real values)."""

    name: str
    surface_id: str
    source_component_id: str
    timestamp: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    action_id: Optional[str] = None
    want_response: bool = False

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "ClientAction":
        # Accept either a raw A2UI ``{version, action:{...}}`` envelope or the
        # flattened action object the qwenpaw renderer POSTs directly.
        action = body.get("action", body)
        missing = [
            k
            for k in ("name", "surfaceId", "sourceComponentId")
            if not action.get(k)
        ]
        if missing:
            raise ValueError(f"action missing required field(s): {missing}")
        return cls(
            name=str(action["name"]),
            surface_id=str(action["surfaceId"]),
            source_component_id=str(action["sourceComponentId"]),
            timestamp=str(action.get("timestamp") or ""),
            context=dict(action.get("context") or {}),
            action_id=action.get("actionId"),
            want_response=bool(action.get("wantResponse")),
        )
