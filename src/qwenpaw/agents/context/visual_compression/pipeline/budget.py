# -*- coding: utf-8 -*-
"""Token counting and visual-versus-text request budget policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import (
    CANVAS_MAX_HEIGHT,
    CANVAS_PADDING,
    CHARS_PER_TEXT_TOKEN_FALLBACK,
    IMAGE_COST_SAFETY_MARGIN,
    IMAGE_PATCH_SIZE,
    MAX_VISUAL_COST_RATIO,
    EffortPreset,
)

if TYPE_CHECKING:
    from ..rendering import RenderedPage

_QWENPAW_PACKAGE_ROOT = Path(__file__).resolve().parents[4]
_TOKENIZER_JSON = _QWENPAW_PACKAGE_ROOT / "tokenizer" / "tokenizer.json"


@dataclass(frozen=True)
class RequestBudget:
    """Image envelope; opaque media token cost remains provider-owned."""

    max_total_images: int
    original_images: int
    generated_images: int

    @classmethod
    def from_image_count(
        cls,
        max_total_images: int,
        *,
        images: int,
    ) -> "RequestBudget":
        return cls(
            max_total_images=max_total_images,
            original_images=images,
            generated_images=max(0, max_total_images - images),
        )


@lru_cache(maxsize=1)
def _load_qwen_tokenizer() -> Any:
    """Load the bundled Qwen tokenizer without downloading model assets."""
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(_TOKENIZER_JSON))


def count_text_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Count Qwen text tokens exactly; retain a conservative local fallback."""
    if not text:
        return 0
    try:
        return len(_load_qwen_tokenizer().encode(text).ids)
    except (OSError, ValueError, RuntimeError, ImportError):
        return max(
            1,
            math.ceil(
                len(text.encode("utf-8")) / max(1.0, float(chars_per_token)),
            ),
        )


def profitable(
    baseline_text: str,
    rendered_text: str,
    columns: int,
    preset: EffortPreset,
    baseline_text_tokens: int | None = None,
    image_count_cap: int | None = None,
    replacement_text: str = "",
    estimated_pages: list["RenderedPage"] | None = None,
) -> bool:
    """Accept only replacements that reduce estimated request tokens."""
    text_tokens = (
        int(baseline_text_tokens)
        if baseline_text_tokens is not None
        else count_text_tokens(
            baseline_text,
            CHARS_PER_TEXT_TOKEN_FALLBACK,
        )
    )
    if estimated_pages is None:
        cols = max(1, int(columns))
        rows = 0
        for line in rendered_text.split("\n"):
            line_length = len(line.encode("utf-16-le")) // 2
            rows += 1 if line_length == 0 else math.ceil(line_length / cols)
        hard_rows = max(
            1,
            (CANVAS_MAX_HEIGHT - 2 * CANVAS_PADDING) // preset.line_height,
        )
        readable_rows = max(
            1,
            preset.readable_chars_per_image // cols,
        )
        rows_per_image = min(hard_rows, readable_rows)
        image_count = max(1, math.ceil(rows / rows_per_image))
        if image_count_cap is not None and image_count_cap > 0:
            image_count = min(image_count, int(image_count_cap))
        full_images = max(0, image_count - 1)
        rows_in_last = min(
            rows_per_image,
            max(1, rows - full_images * rows_per_image),
        )
        width = 2 * CANVAS_PADDING + cols * preset.cell_width
        full_height = 2 * CANVAS_PADDING + rows_per_image * preset.line_height
        last_height = 2 * CANVAS_PADDING + rows_in_last * preset.line_height
        dimensions = [
            *((width, full_height) for _ in range(full_images)),
            (width, last_height),
        ]
    else:
        dimensions = [(page.width, page.height) for page in estimated_pages]

    def patch_tokens(width: int, height: int) -> int:
        return math.ceil(width / IMAGE_PATCH_SIZE) * math.ceil(
            height / IMAGE_PATCH_SIZE,
        )

    patch_sum = sum(
        patch_tokens(width, height) for width, height in dimensions
    )
    image_tokens = math.ceil(
        patch_sum * IMAGE_COST_SAFETY_MARGIN,
    )
    replacement_tokens = count_text_tokens(
        replacement_text,
        CHARS_PER_TEXT_TOKEN_FALLBACK,
    )
    replacement_tokens += image_tokens
    accepted = replacement_tokens < text_tokens * max(
        0.5,
        MAX_VISUAL_COST_RATIO,
    )
    return accepted


__all__ = ["RequestBudget", "count_text_tokens", "profitable"]
