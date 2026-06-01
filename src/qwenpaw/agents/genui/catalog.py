"""Frozen A2UI v0.10 catalog facts — the single source of truth shared by
the validator (:mod:`.validator`), the emitter (:mod:`.protocol`), and the
skill reference docs.

We pin to **one** A2UI version and vendor a **subset** of the Basic catalog.
The frontend renderer (``console/src/genui``) and the skill ``references/``
MUST keep the same allowlist verbatim — an agent that emits a component
outside this set would produce an un-renderable surface, so the validator
rejects it up front (fail fast).
"""
from __future__ import annotations

# Pinned protocol version. Every server->client / client->server envelope
# carries this verbatim. Do NOT track upstream (A2UI is v0.x, "expect changes").
A2UI_VERSION = "v0.10"

# Catalog identifier the client renderer registers under. Matches the vendored
# Basic catalog snapshot.
BASIC_CATALOG_ID = (
    "https://a2ui.org/specification/v0_10/catalogs/basic/catalog.json"
)

# The first vendored component subset (kept in lock-step with
# console/src/genui catalog + skills/genui-*/references/catalog.md).
# Enough to natively rebuild the task board and cover near-term forms/pickers.
ALLOWED_COMPONENTS: frozenset[str] = frozenset(
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
