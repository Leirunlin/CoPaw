# -*- coding: utf-8 -*-
"""Frozen A2UI v0.10 catalog facts shared by the renderer and validator.

We pin to **one** A2UI version, vendor a subset of the Basic catalog, and allow
domain catalogs to register their own template components. The general
``genui`` skill documents only ``BASIC_COMPONENTS``; domain consumers document
their own components in their own skill references.
"""

from __future__ import annotations

# Pinned protocol version. Every server->client / client->server envelope
# carries this verbatim. Do NOT track upstream; A2UI is v0.x.
A2UI_VERSION = "v0.10"

# Catalog identifier the client renderer registers under. Matches the vendored
# Basic catalog snapshot.
BASIC_CATALOG_ID = (
    "https://a2ui.org/specification/v0_10/catalogs/basic/catalog.json"
)

TASK_PLAN_CATALOG_ID = "qwenpaw://genui/catalog/task-plan/v1"

# The first vendored Basic component subset (kept in lock-step with
# skills/genui-*/references/catalog.md). Enough for near-term forms/pickers.
BASIC_COMPONENTS: frozenset[str] = frozenset(
    {
        "Text",
        "Row",
        "Column",
        "List",
        "Card",
        "Divider",
        "Button",
        "CheckBox",
        "TextField",
        "ChoicePicker",
        "Icon",
    },
)

# Domain template components are owned by their consumer package/skill, not by
# the general genui skill docs.
DOMAIN_COMPONENTS: frozenset[str] = frozenset({"TaskBoard"})

ALLOWED_COMPONENTS: frozenset[str] = BASIC_COMPONENTS | DOMAIN_COMPONENTS

# Deferred (present in the Basic catalog but not vendored yet). Listed only so
# the validator can give a precise "deferred, not unknown" message.
DEFERRED_COMPONENTS: frozenset[str] = frozenset(
    {
        "Image",
        "Video",
        "AudioPlayer",
        "Tabs",
        "Modal",
        "DateTimeInput",
        "Slider",
    },
)

# The component-tree entry point id (A2UI requires exactly one).
ROOT_ID = "root"
