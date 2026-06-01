"""Action-handler registry for the unified ``/genui/action`` endpoint.

A user action on any generative-UI surface arrives as one A2UI ``ClientAction``.
We dispatch by ``surfaceId`` prefix to a registered handler, so a new
interactive feature only adds a handler module (and registers it) instead of
adding bespoke REST endpoints + postMessage wiring.

A handler mutates its own canonical state and returns the A2UI envelopes that
should be applied to the surface (broadcast to live subscribers and returned to
the acting client). Handlers are synchronous (file IO); raise ``ValueError`` for
bad input — the router maps it to HTTP 400.
"""
from __future__ import annotations

from typing import Callable

from ....agents.genui import ClientAction, Envelope

Handler = Callable[["object", ClientAction], list[Envelope]]

_REGISTRY: dict[str, Handler] = {}


def register(prefix: str, handler: Handler) -> None:
    """Register *handler* for surfaces whose id starts with *prefix*."""
    _REGISTRY[prefix] = handler


def dispatch(workspace: "object", action: ClientAction) -> list[Envelope]:
    for prefix, handler in _REGISTRY.items():
        if action.surface_id.startswith(prefix):
            return handler(workspace, action)
    raise ValueError(f"no genui action handler for surface {action.surface_id!r}")


# Import side-effect: register the built-in handlers.
from . import task_html_handler  # noqa: E402,F401
