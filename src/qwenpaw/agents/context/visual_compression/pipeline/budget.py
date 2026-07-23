# -*- coding: utf-8 -*-
"""Token counting and visual-versus-text request budget policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import PRODUCTION_RECIPE

if TYPE_CHECKING:
    from ..config import RenderProfile
    from ..rendering import RenderedPage
    from .receipt import CompressionReceipt

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
    profile: "RenderProfile",
    chars_per_text_token: float,
    max_visual_cost_ratio: float | None = None,
    image_cost_safety_margin: float | None = None,
    receipt: "CompressionReceipt | None" = None,
    baseline_text_tokens: int | None = None,
    image_count_cap: int | None = None,
    replacement_text: str = "",
    estimated_pages: list["RenderedPage"] | None = None,
) -> bool:
    """Gate a complete text-to-visual replacement at Qwen patch geometry."""
    text_tokens = (
        int(baseline_text_tokens)
        if baseline_text_tokens is not None
        else count_text_tokens(baseline_text, chars_per_text_token)
    )
    if estimated_pages is None:
        cols = max(1, int(columns))
        rows = 0
        for line in rendered_text.split("\n"):
            # Preserve pxpipe row geometry by counting UTF-16 code units.
            line_length = len(line.encode("utf-16-le")) // 2
            rows += 1 if line_length == 0 else math.ceil(line_length / cols)
        hard_rows = max(
            1,
            (profile.max_height - 2 * profile.padding) // profile.line_height,
        )
        readable_rows = max(
            1,
            PRODUCTION_RECIPE.readable_chars_per_image // cols,
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
        width = 2 * profile.padding + cols * profile.cell_width
        full_height = (
            2 * profile.padding + rows_per_image * profile.line_height
        )
        last_height = 2 * profile.padding + rows_in_last * profile.line_height
        dimensions = [
            *((width, full_height) for _ in range(full_images)),
            (width, last_height),
        ]
    else:
        dimensions = [(page.width, page.height) for page in estimated_pages]

    def patch_tokens(width: int, height: int) -> int:
        patch = PRODUCTION_RECIPE.image_patch_size
        return math.ceil(width / patch) * math.ceil(height / patch)

    patch_sum = sum(
        patch_tokens(width, height) for width, height in dimensions
    )
    safety = (
        PRODUCTION_RECIPE.image_cost_safety_margin
        if image_cost_safety_margin is None
        else float(image_cost_safety_margin)
    )
    ratio = (
        PRODUCTION_RECIPE.max_visual_cost_ratio
        if max_visual_cost_ratio is None
        else float(max_visual_cost_ratio)
    )
    image_tokens = math.ceil(patch_sum * max(1.0, safety))
    replacement_tokens = count_text_tokens(
        replacement_text,
        chars_per_text_token,
    )
    replacement_tokens += image_tokens
    accepted = replacement_tokens < text_tokens * max(
        0.5,
        ratio,
    )
    evaluation = receipt.evaluation if receipt is not None else None
    if evaluation is not None:
        # TODO: STALE: These counters are benchmark evidence. Remove this
        # mutation when the temporary evaluation receipt is deleted; the
        # production decision is only the returned boolean.
        evaluation.gate_candidates += 1
        evaluation.gate_accepted += int(accepted)
        evaluation.gate_text_tokens += text_tokens
        evaluation.gate_visual_tokens += replacement_tokens
    return accepted


__all__ = ["RequestBudget", "count_text_tokens", "profitable"]
