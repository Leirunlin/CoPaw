# -*- coding: utf-8 -*-
"""Successful tool-result selection, paging, and visual replacement."""

from __future__ import annotations

import math
import re
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolResultState

from ..config import (
    PRODUCTION_RECIPE,
    VisualCompressionRecipe,
    config_value,
    resolve_render_profile,
)
from ..rendering import (
    READABLE_CHARS_PER_IMAGE,
    estimate_text_pages,
    measure_content_columns,
    page_count_for_text,
    prepare_render_text,
    render_rows_per_page,
    render_text_pages,
)
from .budget import profitable as _profitable
from .messages import compact_slab_whitespace as _compact_slab_whitespace
from .messages import data_blocks as _data_blocks
from .receipt import CompressionReceipt
from .receipt import factsheet_for_recipe as _factsheet_for_recipe
from .receipt import make_recovery_id
from .receipt import record_factsheet as _record_factsheet
from .receipt import record_pages as _record_pages


def _utf16_code_units(text: str) -> int:
    """Count UTF-16 code units to preserve pxpipe pager semantics."""
    return len(text.encode("utf-16-le")) // 2


def _utf16_prefix(text: str, code_units: int) -> str:
    """Return a prefix bounded by UTF-16 code units."""
    encoded = text.encode("utf-16-le", errors="surrogatepass")
    return encoded[: max(0, code_units) * 2].decode(
        "utf-16-le",
        errors="surrogatepass",
    )


def _ecmascript_whitespace(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x0009 <= codepoint <= 0x000D
        or codepoint
        in {
            0x0020,
            0x00A0,
            0x1680,
            0x2028,
            0x2029,
            0x202F,
            0x205F,
            0x3000,
            0xFEFF,
        }
        or 0x2000 <= codepoint <= 0x200A
    )


def _ecmascript_trim_start(text: str) -> str:
    index = 0
    while index < len(text) and _ecmascript_whitespace(text[index]):
        index += 1
    return text[index:]


def _ascii_word_boundary_after(text: str, prefix: str) -> bool:
    if not text.startswith(prefix):
        return False
    if len(text) == len(prefix):
        return True
    next_char = text[len(prefix)]
    return not (
        "0" <= next_char <= "9"
        or "A" <= next_char <= "Z"
        or "a" <= next_char <= "z"
        or next_char == "_"
    )


def _pxpipe_visual_rows(text: str, columns: int) -> int:
    """Port ``countVisualRows`` used by pxpipe's pager estimate."""
    return sum(
        max(1, math.ceil(_utf16_code_units(line) / max(1, columns)))
        for line in text.split("\n")
    )


def _classify_content(text: str) -> str:
    """Port pxpipe's structured/log/other paging classification."""
    head = _utf16_prefix(text, 4096)
    stripped = _ecmascript_trim_start(head)
    after_object = (
        _ecmascript_trim_start(stripped[1:])
        if stripped.startswith("{")
        else ""
    )
    after_array = (
        _ecmascript_trim_start(stripped[1:])
        if stripped.startswith("[")
        else ""
    )
    array_starts_value = bool(after_array) and (
        after_array[0] in {'"', "{", "[", "]"}
        or "0" <= after_array[0] <= "9"
        or (
            after_array.startswith("-")
            and len(after_array) > 1
            and "0" <= after_array[1] <= "9"
        )
        or _ascii_word_boundary_after(after_array, "true")
        or _ascii_word_boundary_after(after_array, "false")
        or _ascii_word_boundary_after(after_array, "null")
    )
    yaml_rest = stripped[3:] if stripped.startswith("---") else ""
    yaml_document_marker = (
        bool(yaml_rest)
        and _ecmascript_whitespace(yaml_rest[0])
        and bool(_ecmascript_trim_start(yaml_rest))
    )
    object_starts_value = bool(after_object) and after_object[0] in {'"', "}"}
    explicit_document_start = stripped.startswith(
        ("---\n", "---\r\n", "diff --git "),
    )
    if (
        object_starts_value
        or array_starts_value
        or explicit_document_start
        or yaml_document_marker
    ):
        return "structured"
    lines = [line for line in head.split("\n")[:40] if len(line) > 0]
    if len(lines) >= 4:
        log_line = re.compile(
            r"^(?:\[?(?:DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)\]?\b|"
            r"\d{4}-\d{2}-\d{2}[T ]?|\d{2}:\d{2}:\d{2}\b)",
            flags=re.ASCII,
        )
        if (
            sum(bool(log_line.search(line)) for line in lines) / len(lines)
            >= 0.3
        ):
            return "log"
    return "other"


def _paging_marker(
    *,
    original_chars: int,
    original_lines: int,
    omitted_chars: int,
    omitted_lines: int,
    head_lines: int,
    tail_lines: int,
    original_images: int,
) -> str:
    shown = (
        f"Showing first {head_lines} lines and last {tail_lines} lines."
        if tail_lines
        else f"Showing first {head_lines} lines (tail elided)."
    )
    return (
        "\n\n[ pxpipe paging: omitted "
        f"{omitted_lines:,} lines ({omitted_chars:,} chars) of content here. "
        f"Original length: {original_chars:,} chars "
        f"({original_lines:,} lines, ~{original_images:,} images). "
        f"{shown} ]\n\n"
    )


def _truncate_for_budget(  # pylint: disable=R0915
    text: str,
    max_images: int,
    profile_name: str,
    render_variant: str = "v0_pxpipe",
) -> tuple[str, int]:
    """Port pxpipe's visual-row and char-bounded head/tail pager."""
    profile = resolve_render_profile(profile_name, render_variant)
    cols = max(
        1,
        (profile.width - 2 * profile.padding) // profile.cell_width,
    )
    rows_per_image = render_rows_per_page(profile, cols)
    estimated_images = max(
        1,
        math.ceil(_pxpipe_visual_rows(text, cols) / rows_per_image),
        math.ceil(_utf16_code_units(text) / READABLE_CHARS_PER_IMAGE),
    )
    if estimated_images <= max_images:
        return text, 0
    total_row_budget = max(8, max_images * rows_per_image - 6)
    total_char_budget = max(
        128,
        max_images * READABLE_CHARS_PER_IMAGE - 512,
    )
    delimiter = "\n" if "\n" in text else "↵"
    lines = text.split(delimiter)
    original_lines = len(lines)
    shape = _classify_content(text)

    def line_rows(line: str) -> int:
        return max(1, math.ceil(_utf16_code_units(line) / cols))

    if shape == "structured":
        rows = chars = cut = 0
        for idx, line in enumerate(lines):
            next_rows = line_rows(line)
            next_chars = _utf16_code_units(line) + int(idx > 0)
            if (
                rows + next_rows > total_row_budget
                or chars + next_chars > total_char_budget
            ):
                break
            rows += next_rows
            chars += next_chars
            cut = idx + 1
        cut = max(1, cut)
        head = delimiter.join(lines[:cut])
        omitted = _utf16_code_units(text) - _utf16_code_units(head)
        marker = _paging_marker(
            original_chars=_utf16_code_units(text),
            original_lines=original_lines,
            omitted_chars=omitted,
            omitted_lines=max(0, original_lines - cut),
            head_lines=cut,
            tail_lines=0,
            original_images=estimated_images,
        )
        return head + marker, omitted

    head_row_budget = math.floor(total_row_budget * 0.6)
    tail_row_budget = total_row_budget - head_row_budget
    head_char_budget = math.floor(total_char_budget * 0.6)
    tail_char_budget = total_char_budget - head_char_budget
    head_rows = head_chars = head_cut = 0
    for idx, line in enumerate(lines):
        next_rows = line_rows(line)
        next_chars = _utf16_code_units(line) + int(idx > 0)
        if (
            head_rows + next_rows > head_row_budget
            or head_chars + next_chars > head_char_budget
        ):
            break
        head_rows += next_rows
        head_chars += next_chars
        head_cut = idx + 1
    head_cut = max(1, head_cut)
    tail_rows = tail_chars = 0
    tail_start = len(lines)
    for idx in range(len(lines) - 1, head_cut - 1, -1):
        line = lines[idx]
        next_rows = line_rows(line)
        next_chars = _utf16_code_units(line) + int(idx < len(lines) - 1)
        if (
            tail_rows + next_rows > tail_row_budget
            or tail_chars + next_chars > tail_char_budget
        ):
            break
        tail_rows += next_rows
        tail_chars += next_chars
        tail_start = idx
    head = delimiter.join(lines[:head_cut])
    if tail_start <= head_cut or tail_start >= len(lines):
        omitted = _utf16_code_units(text) - _utf16_code_units(head)
        marker = _paging_marker(
            original_chars=_utf16_code_units(text),
            original_lines=original_lines,
            omitted_chars=omitted,
            omitted_lines=max(0, original_lines - head_cut),
            head_lines=head_cut,
            tail_lines=0,
            original_images=estimated_images,
        )
        return head + marker, omitted
    tail = delimiter.join(lines[tail_start:])
    tail_lines = len(lines) - tail_start
    omitted = (
        _utf16_code_units(text)
        - _utf16_code_units(head)
        - _utf16_code_units(tail)
    )
    marker = _paging_marker(
        original_chars=_utf16_code_units(text),
        original_lines=original_lines,
        omitted_chars=omitted,
        omitted_lines=max(0, original_lines - head_cut - tail_lines),
        head_lines=head_cut,
        tail_lines=tail_lines,
        original_images=estimated_images,
    )
    return head + marker + tail, omitted


def _configured_keep_sharp(
    block: ToolResultBlock,
    text: str,
    config: Any,
) -> bool:
    # Recovery is already the exact native escape hatch for visualized source.
    # Re-imaging its output on the immediately following call would create a
    # recovery-of-recovery loop and hide the text the model explicitly asked
    # to inspect. Old recovery turns may still enter a later history image.
    if block.name.casefold() == "recover_visual_context":
        return True
    names = {
        str(name).casefold()
        for name in config_value(config, "keep_sharp_tool_names", [])
    }
    if block.name.casefold() in names:
        return True
    for pattern in config_value(config, "keep_sharp_patterns", []):
        try:
            if re.search(str(pattern), text):
                return True
        except re.error:
            # pxpipe treats a throwing/non-boolean callback as false. Invalid
            # Serialized regexes follow the same fail-open-to-normal-planning
            # rule.
            continue
    return False


def compress_tool_results(  # pylint: disable=R0915
    messages: list[Msg],
    config: Any,
    receipt: CompressionReceipt,
    pages_left: int,
    recipe: VisualCompressionRecipe = PRODUCTION_RECIPE,
) -> int:
    """Rewrite eligible results across the copied request in place."""
    # TODO: STALE: The per-region switch exists only for benchmark ablations.
    # Production will always apply the immutable recipe to eligible results.
    # TODO: STALE: Optional counters and ``pixels_per_token`` below exist only
    # for local benchmark receipts. They do not participate in production
    # selection, paging, or rendering.
    evaluation = receipt.evaluation
    if evaluation is not None and not config_value(
        config,
        "compress_tool_results",
        True,
    ):
        return pages_left
    min_chars = recipe.tool_result_min_chars
    ppt = float(config_value(config, "pixels_per_token", 750.0))
    cpt = recipe.chars_per_text_token_fallback
    ratio = recipe.max_visual_cost_ratio
    safety = recipe.image_cost_safety_margin
    profile = recipe.render_profile.name
    render_variant = recipe.render_variant.name
    resolved_profile = recipe.render_profile
    emit_recoverable = bool(config_value(config, "emit_recoverable", True))

    def compress_part(  # pylint: disable=R0911,R0912
        block: ToolResultBlock,
        text: str,
        provenance: str,
    ) -> list[Any] | None:
        nonlocal pages_left
        if pages_left <= 0:
            return None
        if _configured_keep_sharp(block, text, config):
            if evaluation is not None:
                evaluation.passthrough["kept_sharp"] = (
                    evaluation.passthrough.get("kept_sharp", 0) + 1
                )
            return None
        recovery_id = (
            make_recovery_id(text, "tool_result", provenance)
            if emit_recoverable
            else None
        )
        sheet = _factsheet_for_recipe(text, recipe)
        page_budget = min(
            pages_left,
            recipe.max_images_per_tool_result,
        )
        rendered_source = prepare_render_text(
            _compact_slab_whitespace(text),
            render_variant,
        )
        if _utf16_code_units(rendered_source) < min_chars:
            if evaluation is not None:
                evaluation.passthrough["below_threshold"] = (
                    evaluation.passthrough.get("below_threshold", 0) + 1
                )
            return None
        render_payload = rendered_source
        omitted_chars = 0
        render_columns = measure_content_columns(
            render_payload,
            profile,
            render_variant,
        )
        if (
            page_count_for_text(
                render_payload,
                profile,
                render_variant,
                columns=render_columns,
            )
            > page_budget
        ):
            # Paging deliberately omits a middle/tail region. Without the
            # recovery channel there is no exact path back to those bytes, so
            # keep the native result instead of performing an irreversible
            # visual replacement.
            if not emit_recoverable:
                if evaluation is not None:
                    evaluation.passthrough["paging_requires_recovery"] = (
                        evaluation.passthrough.get(
                            "paging_requires_recovery",
                            0,
                        )
                        + 1
                    )
                return None
            rendered_source, omitted_chars = _truncate_for_budget(
                rendered_source,
                page_budget,
                profile,
                render_variant,
            )
            render_payload = rendered_source
            render_columns = measure_content_columns(
                render_payload,
                profile,
                render_variant,
            )
            if (
                page_count_for_text(
                    render_payload,
                    profile,
                    render_variant,
                    columns=render_columns,
                )
                > page_budget
            ):
                if evaluation is not None:
                    evaluation.passthrough["paging_failed"] = (
                        evaluation.passthrough.get("paging_failed", 0) + 1
                    )
                return None
        estimated_pages = estimate_text_pages(
            render_payload,
            profile,
            render_variant,
            columns=render_columns,
        )
        if len(estimated_pages) > page_budget:
            if evaluation is not None:
                evaluation.passthrough["paging_failed"] = (
                    evaluation.passthrough.get("paging_failed", 0) + 1
                )
            return None
        # The original native part is what disappears. Price the complete
        # replacement that survives on the request: rendered pages plus its
        # factsheet and association/recovery marker.
        marker = f"[Visual pages associated with output from {block.name}."
        if recovery_id is not None:
            marker += (
                f" Exact recovery id: {recovery_id}; prefer query=... or a "
                "bounded line range, not the whole source."
            )
        marker += "]"
        replacement_text = "\n".join(part for part in (sheet, marker) if part)
        if not _profitable(
            text,
            render_payload,
            render_columns,
            resolved_profile,
            cpt,
            ratio,
            safety,
            receipt,
            image_count_cap=page_budget,
            replacement_text=replacement_text,
            estimated_pages=estimated_pages,
        ):
            if evaluation is not None:
                evaluation.passthrough["not_profitable"] = (
                    evaluation.passthrough.get("not_profitable", 0) + 1
                )
            return None
        pages = render_text_pages(
            render_payload,
            profile,
            page_budget,
            None,
            render_variant,
            columns=render_columns,
            atlas_mode="gray",
        )
        if not pages:
            return None
        if omitted_chars and evaluation is not None:
            # TODO: STALE: Truncation counters are benchmark evidence only.
            evaluation.truncated_tool_results += 1
            evaluation.omitted_chars += omitted_chars
        # pxpipe puts image blocks first inside tool_result content. Precision
        # and recovery text follows, preserving a stable visual prefix.
        output: list[Any] = [*_data_blocks(pages)]
        if sheet:
            output.append(TextBlock(text=sheet))
            # TODO: STALE: Record only benchmark counters/text; ``sheet`` above
            # is the complete production precision channel.
            _record_factsheet(receipt, sheet, "tool_result", config)
        # Anthropic keeps this canonical block order, while AgentScope's OpenAI
        # formatter promotes DataBlocks into a following user message.
        # Describe association, not before/after order, so the same
        # ToolResultBlock stays truthful on both wire formats.
        output.append(TextBlock(text=marker))
        _record_pages(
            receipt,
            pages,
            text,
            "tool_result",
            ppt,
            emit_recoverable,
            provenance,
        )
        pages_left -= len(pages)
        return output

    # Request orchestration calls this only after frozen history has replaced
    # its owned prefix. Therefore every result visible here belongs to the
    # native frontier and every generated page survives in the final request.
    for msg in messages:
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                continue
            if block.state != ToolResultState.SUCCESS:
                if evaluation is not None:
                    evaluation.passthrough["non_success_tool_result"] = (
                        evaluation.passthrough.get(
                            "non_success_tool_result",
                            0,
                        )
                        + 1
                    )
                continue
            if isinstance(block.output, str):
                replacement = compress_part(block, block.output, block.id)
                if replacement is not None:
                    block.output = replacement
                continue
            if not isinstance(block.output, list):
                continue
            rewritten: list[Any] = []
            for part_index, part in enumerate(block.output):
                if isinstance(part, TextBlock):
                    replacement = compress_part(
                        block,
                        part.text,
                        f"{block.id}:part:{part_index}",
                    )
                    if replacement is not None:
                        rewritten.extend(replacement)
                        continue
                rewritten.append(part)
            block.output = rewritten
    return pages_left
