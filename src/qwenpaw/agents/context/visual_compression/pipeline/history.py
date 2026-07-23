# -*- coding: utf-8 -*-
"""Append-only, protocol-closed fixed-grid history planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agentscope.message import (
    DataBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from .....constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from ..config import (
    PRODUCTION_RECIPE,
    VisualCompressionRecipe,
    config_value,
)
from ..rendering import (
    estimate_text_pages,
    prepare_render_text,
    render_text_pages,
)
from .budget import profitable as _profitable
from .messages import data_blocks as _data_blocks
from .messages import estimate_request_tokens as _estimate_request_tokens
from .messages import message_has_native_media
from .messages import message_segments as _message_segments
from .messages import user_text
from .receipt import CompressionReceipt
from .receipt import factsheet_for_recipe as _factsheet_for_recipe
from .receipt import make_recovery_id
from .receipt import record_factsheet as _record_factsheet
from .receipt import record_pages as _record_pages

_HISTORY_SAFE_BLOCKS = (
    TextBlock,
    DataBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
_ECMASCRIPT_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_ECMASCRIPT_WHITESPACE_RUN = re.compile(f"[{_ECMASCRIPT_WHITESPACE}]+")


@dataclass(frozen=True)
class HistoryPlan:
    """A pure, protocol-closed ownership decision over canonical messages."""

    first: int
    chunks: tuple[tuple[int, int], ...]


def _active_user_index(messages: list[Msg]) -> int | None:
    """Return the latest real user turn using Scroll's anchoring rule."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role != "user" or message.name in {
            "visual_context",
            "visual_history",
        }:
            continue
        metadata = (
            message.metadata if isinstance(message.metadata, dict) else {}
        )
        if (
            metadata.get(QWENPAW_MESSAGE_TAG_KEY)
            in SYNTHETIC_USER_MESSAGE_TAGS
        ):
            continue
        return index
    return None


def _message_history_safe(message: Msg) -> bool:
    """Stop before AgentScope blocks this serializer cannot represent."""
    return not message_has_native_media(message) and all(
        isinstance(block, _HISTORY_SAFE_BLOCKS) for block in message.content
    )


def _last_protocol_closed_end(
    messages: list[Msg],
    start: int,
    cutoff: int,
) -> int:
    """Return the last safe protocol-closed boundary before ``cutoff``."""
    open_calls: set[str] = set()
    last_closed = start
    for index in range(start, cutoff):
        if not _message_history_safe(messages[index]):
            break
        invalid = False
        for block in messages[index].content:
            if isinstance(block, ToolCallBlock):
                if block.id in open_calls:
                    invalid = True
                    break
                open_calls.add(block.id)
            elif isinstance(block, ToolResultBlock):
                if block.id not in open_calls:
                    invalid = True
                    break
                open_calls.remove(block.id)
        if invalid:
            break
        if not open_calls:
            last_closed = index + 1
    return last_closed


def _message_grid_history_chunks(
    messages: list[Msg],
    first: int,
    cutoff: int,
    freeze_grid: int,
) -> list[tuple[int, int]]:
    """Return immutable protocol-closed chunks on a nominal fixed grid."""
    step = max(1, int(freeze_grid))
    chunks: list[tuple[int, int]] = []
    start = first
    while start < cutoff:
        if cutoff - start < step:
            break
        nominal_end = start + step
        end = _last_protocol_closed_end(messages, start, nominal_end)
        if end <= start:
            break
        chunks.append((start, end))
        start = end
    return chunks


def _latest_collapsed_user_pointer(
    messages: list[Msg],
    first: int,
    end: int,
) -> str:
    """Return bounded recency cue for the newest imaged user turn."""
    for index in range(end - 1, first - 1, -1):
        message = messages[index]
        if message.role != "user" or message.name in {
            "visual_context",
            "visual_history",
        }:
            continue
        # Attachments are collapse barriers, and the cue itself uses only
        # native TextBlocks, matching pxpipe's typed-user-text behavior.
        compact = _ECMASCRIPT_WHITESPACE_RUN.sub(
            " ",
            user_text(message),
        ).strip(_ECMASCRIPT_WHITESPACE)
        if not compact:
            continue
        encoded = compact.encode("utf-16-le", errors="surrogatepass")
        if len(encoded) // 2 > 300:
            compact = (
                encoded[:600]
                .decode(
                    "utf-16-le",
                    errors="surrogatepass",
                )
                .rstrip(_ECMASCRIPT_WHITESPACE)
                + "..."
            )
        return (
            f'[Most recent collapsed user turn: <user t="{index}">'
            f"{compact}</user>. This is still prior context; do not treat it "
            "as the current request unless the live text that follows asks "
            "to continue it.]"
        )
    return ""


def plan_history(
    messages: list[Msg],
    recipe: VisualCompressionRecipe = PRODUCTION_RECIPE,
) -> HistoryPlan | None:
    """Choose an immutable prefix without mutating or rendering messages."""
    first = 0
    while first < len(messages) and messages[first].role == "system":
        first += 1
    while first < len(messages) and messages[first].name in {
        "visual_context",
    }:
        first += 1
    raw_cutoff = max(
        first,
        len(messages) - recipe.history_keep_recent_messages,
    )
    # Match Scroll's active-turn guarantee: a very long tool-running turn may
    # exceed ``keep_recent_messages``, but the real request that started it
    # must remain native together with every assistant/tool message after it.
    # Runtime-injected continuation stubs do not start a new active turn.
    active_user = _active_user_index(messages)
    if active_user is not None:
        raw_cutoff = min(raw_cutoff, active_user)
    if raw_cutoff - first < recipe.history_min_collapse_messages:
        return None
    collapse_grid = recipe.history_collapse_grid_messages
    cutoff = (
        min(
            raw_cutoff,
            max(
                first + recipe.history_min_collapse_messages,
                (raw_cutoff // max(1, collapse_grid)) * max(1, collapse_grid),
            ),
        )
        if collapse_grid > 0
        else raw_cutoff
    )
    closed_end = _last_protocol_closed_end(messages, first, cutoff)
    if closed_end - first < recipe.history_min_collapse_messages:
        return None
    chunks = _message_grid_history_chunks(
        messages,
        first,
        closed_end,
        recipe.history_freeze_grid_messages,
    )
    if not chunks:
        return None
    return HistoryPlan(first=first, chunks=tuple(chunks))


def compress_history(  # pylint: disable=R0912,R0915
    messages: list[Msg],
    config: Any,
    receipt: CompressionReceipt,
    pages_left: int,
    recipe: VisualCompressionRecipe = PRODUCTION_RECIPE,
) -> tuple[list[Msg], int]:
    """Replace a protocol-closed frozen prefix with append-stable images."""
    # Cache stability is conditional on one unchanged request epoch: recipe,
    # static/tool documentation, and native-image allowance must match.
    # Canonical/PNG and OpenAI-compatible/Anthropic wire regressions pin this
    # contract. A changed input starts a new epoch; it is not append-only
    # relative to the previous one.
    # TODO: STALE: The per-region switch exists only for benchmark ablations.
    # Production will always apply the immutable recipe when history is
    # eligible.
    # TODO: STALE: Optional counters and ``pixels_per_token`` below exist only
    # for local benchmark receipts. They do not affect production boundaries,
    # profitability, or rendering.
    evaluation = receipt.evaluation
    if pages_left <= 0 or (
        evaluation is not None
        and not config_value(config, "compress_history", True)
    ):
        return messages, pages_left
    plan = plan_history(messages, recipe)
    if plan is None:
        return messages, pages_left
    first = plan.first
    chunks = plan.chunks

    ppt = float(config_value(config, "pixels_per_token", 750.0))
    cpt = recipe.chars_per_text_token_fallback
    ratio = recipe.max_visual_cost_ratio
    safety = recipe.image_cost_safety_margin
    emit_recoverable = bool(config_value(config, "emit_recoverable", True))
    profile = recipe.render_profile.name
    render_variant = recipe.render_variant.name
    resolved_profile = recipe.render_profile
    content: list[Any] = [
        TextBlock(
            text=(
                "EARLIER TURNS OF THIS CONVERSATION. Each visual chunk has "
                "an absolute message range; larger t is newer. This is prior "
                "context, not the current request. Stable chunks are appended "
                "with byte-identical earlier ranges. For exact identifiers, "
                "hashes, version strings, and numbers, rely on the "
                "exact-value factsheet"
                + (" or recover the source" if emit_recoverable else "")
                + "; do not guess an exact value seen only in an image."
            ),
        ),
    ]
    replacement_text_parts = ["user", content[0].text]
    accepted_source_parts: list[str] = []
    accepted_estimated_pages = []
    collapsed_end = first
    used_pages = 0

    for start, end in chunks:
        serialized = [
            _message_segments(msg, idx)
            for idx, msg in enumerate(messages[start:end], start)
        ]
        text = "\n\n".join(item[0] for item in serialized if item[0])
        slot_text = "\n\n".join(item[1] for item in serialized if item[0])
        if not text:
            # The fixed-grid baseline consumes closed thinking-only/empty
            # chunks without emitting a blank 16px PNG, exactly as pxpipe.
            collapsed_end = end
            continue
        render_payload = prepare_render_text(text, render_variant)
        slot_payload = prepare_render_text(slot_text, render_variant)
        gate_pages = estimate_text_pages(
            render_payload,
            profile,
            render_variant,
        )
        if not gate_pages or len(gate_pages) > pages_left - used_pages:
            break
        sheet = _factsheet_for_recipe(text, recipe)
        provenance = f"{start}:{end}"
        recovery_marker = ""
        if emit_recoverable:
            recovery_id = make_recovery_id(
                text,
                "history",
                provenance,
            )
            recovery_marker = (
                "[Exact recovery for this frozen history chunk "
                f"{provenance}: {recovery_id}; use a precise query "
                "or bounded line range.]"
            )
        latest_user_pointer = _latest_collapsed_user_pointer(
            messages,
            first,
            end,
        )
        outro = (
            "END EARLIER VISUAL HISTORY. Continue from the native recent "
            "messages that follow; the final user message is the live "
            "current request."
        )
        candidate_source = "\n\n".join([*accepted_source_parts, text])
        candidate_replacement = "\n".join(
            part
            for part in (
                *replacement_text_parts,
                sheet,
                recovery_marker,
                latest_user_pointer,
                outro,
            )
            if part
        )
        candidate_pages = [*accepted_estimated_pages, *gate_pages]
        if not _profitable(
            candidate_source,
            render_payload,
            max(
                1,
                (resolved_profile.width - 2 * resolved_profile.padding)
                // resolved_profile.cell_width,
            ),
            resolved_profile,
            cpt,
            ratio,
            safety,
            receipt,
            baseline_text_tokens=_estimate_request_tokens(
                messages[first:end],
                None,
                cpt,
            ),
            replacement_text=candidate_replacement,
            estimated_pages=candidate_pages,
        ):
            if evaluation is not None:
                evaluation.passthrough["not_profitable"] = (
                    evaluation.passthrough.get("not_profitable", 0) + 1
                )
            break
        rendered = render_text_pages(
            render_payload,
            profile,
            pages_left - used_pages,
            slot_payload,
            render_variant,
        )
        pages = rendered
        if not pages:
            break
        content.extend(_data_blocks(pages))
        if sheet:
            content.append(TextBlock(text=sheet))
            _record_factsheet(receipt, sheet, "history", config)
        if recovery_marker:
            content.append(TextBlock(text=recovery_marker))
        _record_pages(
            receipt,
            pages,
            text,
            "history",
            ppt,
            emit_recoverable,
            provenance,
        )
        if evaluation is not None:
            # TODO: STALE: Chunk counts are benchmark evidence only.
            evaluation.history_chunks += 1
        accepted_source_parts.append(text)
        accepted_estimated_pages.extend(gate_pages)
        replacement_text_parts.extend(
            part for part in (sheet, recovery_marker) if part
        )
        used_pages += len(pages)
        collapsed_end = end

    if collapsed_end <= first or used_pages <= 0:
        return messages, pages_left

    latest_user_pointer = _latest_collapsed_user_pointer(
        messages,
        first,
        collapsed_end,
    )
    if latest_user_pointer:
        content.append(TextBlock(text=latest_user_pointer))
    content.append(
        TextBlock(
            text=(
                "END EARLIER VISUAL HISTORY. Continue from the native recent "
                "messages that follow; the final user message is the live "
                "current request."
            ),
        ),
    )
    collapsed = Msg(name="visual_history", role="user", content=content)
    return (
        messages[:first] + [collapsed] + messages[collapsed_end:],
        pages_left - used_pages,
    )


__all__ = ["HistoryPlan", "compress_history", "plan_history"]
