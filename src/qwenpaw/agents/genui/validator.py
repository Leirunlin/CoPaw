"""Catalog-aware structural validation for A2UI envelopes.

Concepts borrowed from A2UI's conformance suite; **no** google-adk SDK is
imported. Validation is deliberately structural (envelope shape, catalog
allowlist, JSON-Pointer well-formedness, root presence) — deep per-component
prop validation is the renderer's job. We fail fast: an envelope that would
produce an un-renderable surface is rejected before it hits the stream.

Errors are returned in A2UI's standard ``VALIDATION_FAILED`` shape so they can
be fed straight back to the LLM for self-correction.
"""
from __future__ import annotations

from typing import Any, Optional

from .catalog import (
    A2UI_VERSION,
    ALLOWED_COMPONENTS,
    DEFERRED_COMPONENTS,
    ROOT_ID,
)
from .state import split_pointer

Error = dict[str, str]

_MESSAGE_KEYS = frozenset(
    {
        "createSurface",
        "updateComponents",
        "updateDataModel",
        "deleteSurface",
        "callFunction",
        "actionResponse",
    },
)


def _err(surface_id: str, path: str, message: str) -> Error:
    return {
        "code": "VALIDATION_FAILED",
        "surfaceId": surface_id,
        "path": path,
        "message": message,
    }


def validate_envelope(
    envelope: dict[str, Any],
    *,
    expect_root: bool = False,
) -> list[Error]:
    """Validate one server->client envelope.

    ``expect_root=True`` additionally requires the ``updateComponents`` list to
    contain the ``root`` component (use it when emitting a complete surface from
    a CLI script, where no prior components exist to host the root).
    """
    errors: list[Error] = []

    if envelope.get("version") != A2UI_VERSION:
        errors.append(
            _err("", "/version",
                 f"version must be {A2UI_VERSION!r}, got "
                 f"{envelope.get('version')!r}."),
        )

    keys = _MESSAGE_KEYS & set(envelope)
    if len(keys) != 1:
        errors.append(
            _err("", "/",
                 f"envelope must contain exactly one message key, found "
                 f"{sorted(keys) or 'none'}."),
        )
        return errors

    key = next(iter(keys))
    inner = envelope[key]
    surface_id = str(inner.get("surfaceId", "")) if isinstance(inner, dict) else ""

    if key == "updateComponents":
        errors += _validate_components(surface_id, inner, expect_root=expect_root)
    elif key == "updateDataModel":
        errors += _validate_data_model(surface_id, inner)
    elif key == "createSurface":
        if not surface_id:
            errors.append(_err(surface_id, "/createSurface/surfaceId",
                               "surfaceId is required."))
        if not inner.get("catalogId"):
            errors.append(_err(surface_id, "/createSurface/catalogId",
                               "catalogId is required."))
    elif key == "deleteSurface":
        if not surface_id:
            errors.append(_err(surface_id, "/deleteSurface/surfaceId",
                               "surfaceId is required."))

    return errors


def _validate_components(
    surface_id: str,
    inner: dict[str, Any],
    *,
    expect_root: bool,
) -> list[Error]:
    errors: list[Error] = []
    components = inner.get("components")
    if not isinstance(components, list) or not components:
        errors.append(_err(surface_id, "/updateComponents/components",
                           "components must be a non-empty array."))
        return errors

    seen_ids: set[str] = set()
    has_root = False
    for i, comp in enumerate(components):
        base = f"/updateComponents/components/{i}"
        if not isinstance(comp, dict):
            errors.append(_err(surface_id, base, "component must be an object."))
            continue
        cid = comp.get("id")
        ctype = comp.get("component")
        if not cid:
            errors.append(_err(surface_id, f"{base}/id", "component id is required."))
        else:
            if cid in seen_ids:
                errors.append(_err(surface_id, f"{base}/id",
                                   f"duplicate component id {cid!r}."))
            seen_ids.add(cid)
            if cid == ROOT_ID:
                has_root = True
        if not ctype:
            errors.append(_err(surface_id, f"{base}/component",
                               "component type is required."))
        elif ctype not in ALLOWED_COMPONENTS:
            if ctype in DEFERRED_COMPONENTS:
                msg = (f"component {ctype!r} is part of the Basic catalog but "
                       "not yet vendored in qwenpaw; use a vendored component.")
            else:
                msg = (f"unknown component {ctype!r}; allowed: "
                       f"{sorted(ALLOWED_COMPONENTS)}.")
            errors.append(_err(surface_id, f"{base}/component", msg))

    if expect_root and not has_root:
        errors.append(_err(surface_id, "/updateComponents/components",
                           f"exactly one component must have id {ROOT_ID!r}."))
    return errors


def _validate_data_model(surface_id: str, inner: dict[str, Any]) -> list[Error]:
    errors: list[Error] = []
    path = inner.get("path", "/")
    try:
        split_pointer(str(path))
    except ValueError as exc:
        errors.append(_err(surface_id, "/updateDataModel/path", str(exc)))
    return errors


def first_error_message(errors: list[Error]) -> Optional[str]:
    """Human/LLM-friendly one-liner for the first error (CLI stderr)."""
    if not errors:
        return None
    e = errors[0]
    return f"{e['code']} at {e['path']}: {e['message']}"
