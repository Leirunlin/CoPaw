# -*- coding: utf-8 -*-
"""Transform outcome, exact recovery sources, and temporary evidence.

The production contract is ``CompressionReceipt`` plus the recovery/factsheet
recording helpers used by each compression region.
``CompressionEvaluation`` and every evaluation-only branch are marked
``TODO: STALE`` so benchmark cleanup leaves one coherent receipt module.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from typing import TYPE_CHECKING, Any

from agentscope.message import Msg

from ..config import (
    FACTSHEET_MAX_ENTRIES,
    PIPELINE_VERSION,
    PRECISION_VERSION,
    PRODUCTION_RECIPE,
    RENDERER_VERSION,
    VisualCompressionRecipe,
    config_value,
)
from .budget import count_text_tokens
from .messages import estimate_request_tokens
from .precision import factsheet_text

if TYPE_CHECKING:
    from ..rendering import RenderedPage


@dataclass
class CompressionEvaluation:
    """TODO: STALE local benchmark evidence for an opted-in request."""

    receipt_schema_version: int = 1
    recipe_id: str = PRODUCTION_RECIPE.recipe_id
    config_schema_version: int = 1
    pipeline_version: str = PIPELINE_VERSION
    tool_policy: str = ""
    renderer_version: str = RENDERER_VERSION
    precision_version: str = PRECISION_VERSION
    model: str = ""
    arm: str = "on"
    transform_ms: float = 0.0
    original_estimated_tokens: int = 0
    transformed_estimated_tokens: int = 0
    compressed_chars: int = 0
    image_count: int = 0
    image_bytes: int = 0
    image_pixels: int = 0
    estimated_image_tokens: int = 0
    factsheet_tokens: int = 0
    factsheet_entries: int = 0
    factsheet_records: list[dict[str, str]] = field(default_factory=list)
    history_chunks: int = 0
    # TODO: STALE: Legacy pxpipe/Claude-host diagnostics retained only so old
    # benchmark receipts remain readable. QwenPaw does not populate them.
    dynamic_block_count: int = 0
    unknown_static_tags: list[str] = field(default_factory=list)
    churning_static_tags: list[str] = field(default_factory=list)
    truncated_tool_results: int = 0
    omitted_chars: int = 0
    dropped_chars: int = 0
    dropped_codepoints_top: dict[str, int] = field(default_factory=dict)
    gate_candidates: int = 0
    gate_accepted: int = 0
    gate_text_tokens: int = 0
    gate_visual_tokens: int = 0
    token_counter: str = "qwen_bundled_tokenizer"
    render_profile: str = ""
    render_variant: str = "v0_pxpipe"
    render_geometry: dict[str, Any] = field(default_factory=dict)
    regions: dict[str, int] = field(default_factory=dict)
    passthrough: dict[str, int] = field(default_factory=dict)
    image_sha256: list[str] = field(default_factory=list)
    page_records: list[dict[str, Any]] = field(default_factory=list)
    # TODO: STALE: Filesystem artifact fields are benchmark-only.
    image_paths: list[str] = field(default_factory=list)
    artifact_error: str | None = None
    config_hash: str = ""
    cacheable_prefix_digest: str = ""
    cacheable_prefix_components: list[str] = field(default_factory=list)
    request_digest: str = ""
    receipt_dir: str | None = None
    pending_page_artifacts: list[tuple[str, str, bytes]] = field(
        default_factory=list,
        repr=False,
    )


@dataclass
class CompressionReceipt:
    """Minimal result and request-local recovery source for one transform."""

    # TODO: STALE: Recipe identity is consumed only by benchmark/tests; the
    # production transform already closes over ``PRODUCTION_RECIPE`` and
    # recovery routing uses the per-block ids below.
    recipe_id: str = PRODUCTION_RECIPE.recipe_id
    # TODO: STALE: ``applied`` has no production consumer yet. Keep it only if
    # the UI adopts an explicit per-request compression status; otherwise
    # remove it with benchmark outcome handling. It cannot be inferred from
    # ``recoverable`` when exact recovery is disabled.
    applied: bool = False
    # TODO: STALE: Human-readable benchmark/preflight outcome. Production
    # routing uses QwenPaw's capability boolean and recovery uses only the
    # exact request-local blocks below; neither consumes this string.
    reason: str = "disabled"
    recoverable: list[dict[str, Any]] = field(default_factory=list)
    # TODO: STALE: Optional local benchmark evidence. Delete this field with
    # ``CompressionEvaluation``; only request-local recovery plus any
    # explicitly retained first-PR outcome field belongs in the production
    # contract.
    evaluation: CompressionEvaluation | None = field(
        default=None,
        repr=False,
    )

    @property
    def evaluation_enabled(self) -> bool:
        """TODO: STALE: Whether benchmark evidence was explicitly enabled."""
        return self.evaluation is not None

    def to_dict(self) -> dict[str, Any]:
        """TODO: STALE: Flatten the receipt for the local benchmark trace."""
        result = {
            item.name: deepcopy(getattr(self, item.name))
            for item in fields(self)
            if item.name != "evaluation"
        }
        if self.evaluation is not None:
            result.update(
                {
                    item.name: deepcopy(getattr(self.evaluation, item.name))
                    for item in fields(self.evaluation)
                    if item.name != "pending_page_artifacts"
                },
            )
        return result


def make_recovery_id(
    text: str,
    region: str = "visual",
    provenance: str = "",
) -> str:
    """Build an id without conflating equal text from different sources."""
    payload = "\0".join((region, provenance, text)).encode("utf-8")
    return "vctx_" + hashlib.sha256(payload).hexdigest()[:12]


def factsheet_for_recipe(
    text: str,
    recipe: VisualCompressionRecipe = PRODUCTION_RECIPE,
) -> str:
    """Build facts from the selected immutable recipe."""
    limit = min(FACTSHEET_MAX_ENTRIES, recipe.factsheet_limit)
    return factsheet_text(text, limit) if limit > 0 else ""


# TODO: STALE: BEGIN temporary evaluation helpers. Delete this complete block
# (through ``finish_evaluation``) with ``CompressionEvaluation`` and remove its
# guarded call sites. ``record_pages`` below this block remains production.
def factsheet_size(sheet: str) -> int:
    if not sheet:
        return 0
    if sheet.startswith("[Exact identifiers from the rendered context"):
        body = sheet.rsplit(": ", 1)[-1].removesuffix("]")
        return 0 if not body else body.count(" · ") + 1
    return max(0, len(sheet.splitlines()) - 1)


def record_factsheet(
    receipt: CompressionReceipt,
    sheet: str,
    region: str,
    config: Any,
) -> None:
    # TODO: STALE: Factsheet counters/text are benchmark evidence only. The
    # production precision channel is the already-built ``sheet`` string.
    evaluation = receipt.evaluation
    if evaluation is None or not sheet:
        return
    evaluation.factsheet_tokens += count_text_tokens(sheet)
    evaluation.factsheet_entries += factsheet_size(sheet)
    if bool(config_value(config, "record_factsheet_text", False)):
        evaluation.factsheet_records.append(
            {"region": region, "text": sheet},
        )


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluation_config_hash(config: Any) -> str:
    """Hash the temporary benchmark configuration without its output path."""
    # TODO: STALE: Configuration fingerprints are benchmark evidence only.
    payload = {
        key: value
        for key, value in (
            config.model_dump(mode="json").items()
            if hasattr(config, "model_dump")
            else vars(config).items()
        )
        if key != "receipt_dir"
    }
    if "factsheet_limit" in payload:
        payload["factsheet_limit"] = min(
            FACTSHEET_MAX_ENTRIES,
            int(payload["factsheet_limit"]),
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode(),
    ).hexdigest()[:16]


def record_render_geometry(
    receipt: CompressionReceipt,
    recipe: VisualCompressionRecipe = PRODUCTION_RECIPE,
) -> None:
    """Record temporary renderer identity and geometry evidence."""
    # TODO: STALE: The production transform only needs the resolved settings.
    evaluation = receipt.evaluation
    if evaluation is None:
        return
    # TODO: STALE: Lazy to keep the normal model-factory import path free of
    # renderer/Pillow; delete with this evaluation-only helper.
    from ..rendering.renderer import (
        render_asset_metadata,
        render_rows_per_page,
    )

    profile = recipe.render_profile
    variant = recipe.render_variant
    columns = max(
        1,
        (profile.width - 2 * profile.padding) // profile.cell_width,
    )
    rows_per_image = render_rows_per_page(profile, columns)

    evaluation.render_profile = profile.name
    evaluation.render_variant = variant.name
    evaluation.recipe_id = recipe.recipe_id
    evaluation.render_geometry = {
        **asdict(profile),
        "polarity": variant.polarity,
        "page_shape": variant.page_shape,
        "font_recipe": variant.font_recipe,
        "layout": variant.layout,
        "weight": variant.weight,
        "ink_color": variant.ink_color,
        "columns": columns,
        "rows_per_image": rows_per_image,
        "theoretical_ascii_chars_per_image": columns * rows_per_image,
        **render_asset_metadata(profile, variant.name),
    }


def record_request_digests(
    receipt: CompressionReceipt,
    messages: list[Msg],
    tools: list[dict] | None,
    keep_recent: int,
) -> None:
    """Record temporary cache-prefix evidence without claiming a hit."""
    # TODO: STALE: Hashing the complete request exists only for benchmark
    # cache analysis and must never add work to the normal production path.
    evaluation = receipt.evaluation
    if evaluation is None:
        return
    components: list[str] = []
    if tools:
        components.append("tools:" + _json_digest(tools))
    cutoff = max(0, len(messages) - max(1, int(keep_recent)))
    for index, msg in enumerate(messages):
        if (
            index >= cutoff
            and msg.role != "system"
            and msg.name not in {"visual_context", "visual_history"}
        ):
            continue
        dumped = msg.model_dump(mode="json")
        if msg.name in {"visual_context", "visual_history"}:
            header = {key: dumped.get(key) for key in ("role", "name")}
            components.append("message:" + _json_digest(header))
            for block in dumped.get("content", []) or []:
                components.append("block:" + _json_digest(block))
        else:
            components.append("message:" + _json_digest(dumped))
    evaluation.cacheable_prefix_components = components
    evaluation.cacheable_prefix_digest = _json_digest(components)
    evaluation.request_digest = _json_digest(
        {
            "messages": [msg.model_dump(mode="json") for msg in messages],
            "tools": tools,
        },
    )


def finish_evaluation(
    receipt: CompressionReceipt,
    messages: list[Msg],
    tools: list[dict] | None,
    *,
    keep_recent: int,
    planning_cpt: float,
    started: float | None,
) -> None:
    """Populate the temporary benchmark receipt after a transform."""
    # TODO: STALE: Normal production requests leave this branch immediately.
    # Remove this helper with the benchmark receipt and evaluation CLI.
    evaluation = receipt.evaluation
    if evaluation is None:
        return
    evaluation.transformed_estimated_tokens = (
        estimate_request_tokens(messages, tools, planning_cpt)
        + evaluation.estimated_image_tokens
    )
    record_request_digests(receipt, messages, tools, keep_recent)
    if started is not None:
        evaluation.transform_ms = round(
            (time.perf_counter() - started) * 1000,
            3,
        )


# TODO: STALE: END temporary evaluation helpers.


def record_pages(
    receipt: CompressionReceipt,
    pages: list[RenderedPage],
    text: str,
    region: str,
    pixels_per_token: float,
    emit_recoverable: bool,
    provenance: str = "",
) -> None:
    receipt.applied = True
    evaluation = receipt.evaluation
    if evaluation is not None:
        # TODO: STALE: Everything in this branch is temporary benchmark and
        # artifact evidence. Production needs only ``applied`` and recovery.
        evaluation.compressed_chars += len(text)
        evaluation.image_count += len(pages)
        evaluation.image_bytes += sum(len(page.png) for page in pages)
        pixels = sum(page.width * page.height for page in pages)
        evaluation.image_pixels += pixels
        evaluation.estimated_image_tokens += math.ceil(
            pixels / pixels_per_token,
        )
        evaluation.image_sha256.extend(page.sha256 for page in pages)
        evaluation.dropped_chars += sum(page.dropped_chars for page in pages)
        dropped_counts = dict(evaluation.dropped_codepoints_top)
        for page in pages:
            for codepoint, count in page.dropped_codepoints.items():
                dropped_counts[codepoint] = (
                    dropped_counts.get(codepoint, 0) + count
                )
        evaluation.dropped_codepoints_top = dict(
            sorted(
                dropped_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:20],
        )
        evaluation.page_records.extend(
            {
                "region": region,
                "sha256": page.sha256,
                "width": page.width,
                "height": page.height,
                "source_chars": page.source_chars,
                "dropped_chars": page.dropped_chars,
            }
            for page in pages
        )
        if evaluation.receipt_dir:
            evaluation.pending_page_artifacts.extend(
                (region, page.sha256, page.png) for page in pages
            )
        evaluation.regions[region] = evaluation.regions.get(region, 0) + 1
    if emit_recoverable:
        receipt.recoverable.append(
            {
                "id": make_recovery_id(text, region, provenance),
                "region": region,
                **({"provenance": provenance} if provenance else {}),
                "text": text,
                "image_count": len(pages),
            },
        )


__all__ = [
    "CompressionEvaluation",
    "CompressionReceipt",
    "evaluation_config_hash",
    "factsheet_for_recipe",
    "factsheet_size",
    "finish_evaluation",
    "make_recovery_id",
    "record_factsheet",
    "record_pages",
    "record_render_geometry",
    "record_request_digests",
]
