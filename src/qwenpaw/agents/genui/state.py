# -*- coding: utf-8 -*-
"""Server-side mirror of every live A2UI surface.

Why mirror state the client already holds? Two reasons:
1. An action handler that mutates canonical state, such as a task plan JSON
   file, needs to compute the *minimal* A2UI patch to broadcast. That means
   knowing the current data model.
2. A renderer that mounts late (the Workspace pane opens after the agent
   already emitted the surface) cold-loads via
   :meth:`SurfaceStateManager.snapshot` instead of refetching a whole file.

State is in-memory and rebuildable from canonical sources, so it is never
persisted. Keyed by ``(run_key, surfaceId)``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from . import protocol
from .catalog import BASIC_CATALOG_ID

# ---------------------------------------------------------------------------
# RFC-6901 JSON Pointer (the subset A2UI's updateDataModel uses)
# ---------------------------------------------------------------------------


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def split_pointer(path: str) -> list[str]:
    """Split an RFC-6901 pointer into tokens.

    ``""`` / ``"/"`` -> root ``[]``.
    """
    if path in ("", "/"):
        return []
    if not path.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {path!r}")
    return [_unescape(tok) for tok in path.lstrip("/").split("/")]


def _descend(container: Any, token: str, *, create: bool) -> Any:
    if isinstance(container, list):
        idx = len(container) if token == "-" else int(token)
        if create:
            while len(container) <= idx:
                container.append({})
        return container[idx]
    if isinstance(container, dict):
        if create and token not in container:
            container[token] = {}
        return container[token]
    raise ValueError(
        f"cannot descend into {type(container).__name__} at {token!r}",
    )


def pointer_upsert(doc: Any, path: str, value: Any) -> Any:
    """Set ``value`` at ``path`` (creating intermediates). Returns the new doc
    (root replacement when ``path`` is root)."""
    tokens = split_pointer(path)
    if not tokens:
        return value
    cur = doc if doc is not None else {}
    parent = cur
    for tok in tokens[:-1]:
        parent = _descend(parent, tok, create=True)
    last = tokens[-1]
    if isinstance(parent, list):
        idx = len(parent) if last == "-" else int(last)
        while len(parent) <= idx:
            parent.append(None)
        parent[idx] = value
    elif isinstance(parent, dict):
        parent[last] = value
    else:
        raise ValueError(f"cannot set {last!r} on {type(parent).__name__}")
    return cur


def pointer_delete(doc: Any, path: str) -> Any:
    tokens = split_pointer(path)
    if not tokens:
        return {}
    cur = doc
    parent = cur
    try:
        for tok in tokens[:-1]:
            parent = _descend(parent, tok, create=False)
        last = tokens[-1]
        if isinstance(parent, list):
            del parent[int(last)]
        elif isinstance(parent, dict):
            parent.pop(last, None)
    except (KeyError, IndexError, ValueError):
        pass  # deleting an absent path is a no-op
    return cur


def pointer_get(doc: Any, path: str, default: Any = None) -> Any:
    try:
        cur = doc
        for tok in split_pointer(path):
            cur = _descend(cur, tok, create=False)
        return cur
    except (KeyError, IndexError, ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Surface state
# ---------------------------------------------------------------------------


@dataclass
class _Surface:
    surface_id: str
    catalog_id: str = BASIC_CATALOG_ID
    # Flat component map keyed by component id (A2UI is an adjacency list).
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    data: Any = field(default_factory=dict)


class SurfaceStateManager:
    """Thread-safe live surface registry keyed by ``(run_key, surfaceId)``."""

    def __init__(self) -> None:
        self._surfaces: dict[tuple[str, str], _Surface] = {}
        self._lock = threading.Lock()

    def apply(self, run_key: str, envelope: dict[str, Any]) -> None:
        """Fold a server->client envelope into the mirror."""
        with self._lock:
            if "createSurface" in envelope:
                inner = envelope["createSurface"]
                sid = inner["surfaceId"]
                self._surfaces[(run_key, sid)] = _Surface(
                    surface_id=sid,
                    catalog_id=inner.get("catalogId", BASIC_CATALOG_ID),
                )
            elif "updateComponents" in envelope:
                inner = envelope["updateComponents"]
                surf = self._ensure(run_key, inner["surfaceId"])
                for comp in inner.get("components", []):
                    cid = comp.get("id")
                    if cid:
                        surf.components[cid] = comp
            elif "updateDataModel" in envelope:
                inner = envelope["updateDataModel"]
                surf = self._ensure(run_key, inner["surfaceId"])
                path = inner.get("path") or "/"
                if "value" in inner:
                    surf.data = pointer_upsert(surf.data, path, inner["value"])
                else:
                    surf.data = pointer_delete(surf.data, path)
            elif "deleteSurface" in envelope:
                sid = envelope["deleteSurface"]["surfaceId"]
                self._surfaces.pop((run_key, sid), None)

    def snapshot(self, run_key: str, surface_id: str) -> list[dict[str, Any]]:
        """Replay envelopes that reconstruct the current surface from scratch
        (for a late-mounting / reconnecting renderer). Empty list if unknown.
        """
        with self._lock:
            surf = self._surfaces.get((run_key, surface_id))
            if surf is None:
                return []
            envelopes = [
                protocol.create_surface(
                    surface_id,
                    catalog_id=surf.catalog_id,
                ),
            ]
            if surf.components:
                envelopes.append(
                    protocol.update_components(
                        surface_id,
                        list(surf.components.values()),
                    ),
                )
            envelopes.append(
                protocol.update_data_model(surface_id, "/", surf.data),
            )
            return envelopes

    def get_data(self, run_key: str, surface_id: str) -> Any:
        with self._lock:
            surf = self._surfaces.get((run_key, surface_id))
            return None if surf is None else surf.data

    def _ensure(self, run_key: str, surface_id: str) -> _Surface:
        key = (run_key, surface_id)
        surf = self._surfaces.get(key)
        if surf is None:
            surf = _Surface(surface_id=surface_id)
            self._surfaces[key] = surf
        return surf


# Process-wide manager. Surfaces are namespaced by run_key, so a single
# instance is safe across workspaces/runs.
SURFACE_STATE = SurfaceStateManager()
