# -*- coding: utf-8 -*-
"""Fixed algorithm settings for visual context compression.

User-facing runtime values remain in
qwenpaw.config.config.VisualCompressionConfig.
This module owns immutable pxpipe-compatible profiles, variants, and defensive
algorithm limits shared by the renderer, factsheet, and schema transformer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

FACTSHEET_MAX_SCAN_CHARS = 262_144
FACTSHEET_MAX_DISTINCT = 2_048
FACTSHEET_MAX_CHUNK_CHARS = 512
# TODO: STALE: Leftovers from the removed generic schema walker. No production
# module imports them; delete them after old benchmark/test references are
# gone.
SCHEMA_MAX_DEPTH = 20
SCHEMA_FORMAT_MAX_LENGTH = 32
ROLE_MARK_USER = "\x01"
ROLE_MARK_ASSISTANT = "\x02"


def config_value(config: Any, name: str, default: Any) -> Any:
    """Read one runtime option from a validated config or test double."""
    return getattr(config, name, default)


@dataclass(frozen=True)
class RenderProfile:
    name: str
    font_size: int
    line_height: int
    cell_width: int
    width: int = 1024
    max_height: int = 1024
    padding: int = 16


# TODO: STALE: ``calibrated`` is retained as the selected recipe's historical
# name. ``5x8`` is its byte-identical benchmark alias; 7x10/9x12 are direct
# renderer calibration alternatives. Production selects only the immutable
# profile embedded in ``PRODUCTION_RECIPE`` below.
PROFILES = {
    "5x8": RenderProfile(
        "5x8",
        font_size=8,
        line_height=8,
        cell_width=5,
        width=1568,
        max_height=728,
        padding=4,
    ),
    "7x10": RenderProfile("7x10", font_size=14, line_height=17, cell_width=9),
    "9x12": RenderProfile("9x12", font_size=18, line_height=22, cell_width=11),
    "calibrated": RenderProfile(
        "calibrated",
        font_size=8,
        line_height=8,
        cell_width=5,
        width=1568,
        max_height=728,
        padding=4,
    ),
}


@dataclass(frozen=True)
class RenderVariant:
    """One controlled image-rendering ablation.

    ``v0_pxpipe`` deliberately resolves to the historical renderer without
    changing a single raster parameter.  The other variants each change one
    declared rendering dimension while leaving the compression planner,
    factsheet, history policy, and provider request layout untouched.
    """

    name: str
    polarity: str = "light"
    page_shape: str = "pxpipe"
    font_recipe: str = "pxpipe"
    layout: str = "pxpipe_reflow"
    width: int | None = None
    max_height: int | None = None
    font_size: int | None = None
    line_height: int | None = None
    cell_width: int | None = None
    weight: str = "regular"
    ink_color: str = "default"


# TODO: STALE: ``RenderVariant`` and all non-v0 entries below form the
# temporary renderer benchmark surface. Collapse callers to the frozen
# pxpipe profile and remove this variant dispatcher before the production PR.
RENDER_VARIANTS: dict[str, RenderVariant] = {
    "v0_pxpipe": RenderVariant("v0_pxpipe"),
    # TODO: STALE: The remaining controlled ablation variants are
    # evaluation-only; remove them before production release.
    "v1_dark": RenderVariant("v1_dark", polarity="dark"),
    "v2_square": RenderVariant("v2_square", page_shape="square"),
    "v3_jbmono10": RenderVariant(
        "v3_jbmono10",
        font_recipe="jetbrains_mono_10",
    ),
    "v4_preserve_newlines": RenderVariant(
        "v4_preserve_newlines",
        layout="preserve_newlines",
    ),
    # Density-frontier campaign.  Names encode the only intended geometry
    # change so every paid artifact remains self-describing.
    "density_640x384_5x8": RenderVariant(
        "density_640x384_5x8",
        width=640,
        max_height=384,
    ),
    "density_768x512_5x8": RenderVariant(
        "density_768x512_5x8",
        width=768,
        max_height=512,
    ),
    "density_960x512_5x8": RenderVariant(
        "density_960x512_5x8",
        width=960,
        max_height=512,
    ),
    "density_1280x640_5x8": RenderVariant(
        "density_1280x640_5x8",
        width=1280,
        max_height=640,
    ),
    "density_1568x728_5x8": RenderVariant(
        "density_1568x728_5x8",
        width=1568,
        max_height=728,
    ),
    "density_1920x896_5x8": RenderVariant(
        "density_1920x896_5x8",
        width=1920,
        max_height=896,
    ),
    "density_1568x728_jbmono10": RenderVariant(
        "density_1568x728_jbmono10",
        width=1568,
        max_height=728,
        font_recipe="jetbrains_mono_10",
    ),
    "density_1568x728_jbmono12": RenderVariant(
        "density_1568x728_jbmono12",
        width=1568,
        max_height=728,
        font_recipe="jetbrains_mono_12",
        font_size=12,
        line_height=14,
        cell_width=7,
    ),
    # Independent format campaign.  The regular aliases are intentional:
    # they prove the new task suite against byte-identical light/dark controls.
    "format_light_regular": RenderVariant("format_light_regular"),
    "format_dark_regular": RenderVariant(
        "format_dark_regular",
        polarity="dark",
    ),
    "format_light_bold": RenderVariant(
        "format_light_bold",
        weight="bold",
    ),
    "format_dark_bold": RenderVariant(
        "format_dark_bold",
        polarity="dark",
        weight="bold",
    ),
    "format_dark_amber": RenderVariant(
        "format_dark_amber",
        polarity="dark",
        ink_color="amber",
    ),
    "format_light_blue": RenderVariant(
        "format_light_blue",
        ink_color="blue",
    ),
}


def resolve_render_variant(name: str | None) -> RenderVariant:
    key = str(name or "v0_pxpipe")
    if key not in RENDER_VARIANTS:
        raise ValueError(f"unknown render variant: {key}")
    return RENDER_VARIANTS[key]


def resolve_render_profile(
    profile_name: str,
    variant_name: str = "v0_pxpipe",
) -> RenderProfile:
    """Resolve geometry without mutating the historical pxpipe profile."""
    base = PROFILES.get(profile_name, PROFILES["calibrated"])
    variant = resolve_render_variant(variant_name)
    width = 1024 if variant.page_shape == "square" else base.width
    max_height = 1024 if variant.page_shape == "square" else base.max_height
    font_size = base.font_size
    line_height = base.line_height
    cell_width = base.cell_width
    suffix = "-square" if variant.page_shape == "square" else ""
    if variant.font_recipe == "jetbrains_mono_10":
        font_size, line_height, cell_width = 10, 11, 6
        suffix += "-jbmono10"
    width = variant.width if variant.width is not None else width
    max_height = (
        variant.max_height if variant.max_height is not None else max_height
    )
    font_size = (
        variant.font_size if variant.font_size is not None else font_size
    )
    line_height = (
        variant.line_height if variant.line_height is not None else line_height
    )
    cell_width = (
        variant.cell_width if variant.cell_width is not None else cell_width
    )
    geometry_override = any(
        value is not None
        for value in (
            variant.width,
            variant.max_height,
            variant.font_size,
            variant.line_height,
            variant.cell_width,
        )
    )
    if not suffix and not geometry_override:
        return base
    name = (
        f"{base.name}-{variant.name}"
        if geometry_override
        else f"{base.name}{suffix}"
    )
    if variant.font_recipe == "jetbrains_mono_10" and not name.endswith(
        "-jbmono10",
    ):
        name += "-jbmono10"
    return RenderProfile(
        name=name,
        font_size=font_size,
        line_height=line_height,
        cell_width=cell_width,
        width=width,
        max_height=max_height,
        padding=base.padding,
    )


@dataclass(frozen=True)
class VisualCompressionRecipe:
    """One code-owned, immutable production behavior recipe.

    This is deliberately not the persisted ``VisualCompressionConfig``.
    Agent configuration decides whether the feature may run; this value
    decides how the production transform behaves once it runs. Temporary
    benchmark profiles remain above for direct evaluation calls, but the
    production pipeline never selects among them from user configuration.
    """

    recipe_id: str
    config_schema_version: int
    pipeline_version: str
    renderer_version: str
    precision_version: str
    render_profile: RenderProfile
    render_variant: RenderVariant
    readable_chars_per_image: int
    image_patch_size: int
    image_cost_safety_margin: float
    max_visual_cost_ratio: float
    chars_per_text_token_fallback: float
    factsheet_limit: int
    static_min_chars: int
    tool_result_min_chars: int
    max_images_per_request: int
    max_images_per_tool_result: int
    history_min_collapse_messages: int
    history_collapse_grid_messages: int
    history_freeze_grid_messages: int
    history_keep_recent_messages: int


# This is the only recipe used by the production middleware path. Keep the
# complete algorithm decision surface in one immutable value so renderer,
# gate, planner, and receipt cannot silently resolve different defaults.
PRODUCTION_RECIPE = VisualCompressionRecipe(
    recipe_id="qwenpaw-fixed-grid-v3",
    config_schema_version=1,
    pipeline_version="pawfocus-v2",
    renderer_version="pxpipe-render-v1",
    precision_version="pxpipe-facts-v1",
    render_profile=PROFILES["calibrated"],
    render_variant=RENDER_VARIANTS["v0_pxpipe"],
    readable_chars_per_image=28_080,
    image_patch_size=28,
    image_cost_safety_margin=1.10,
    max_visual_cost_ratio=0.90,
    chars_per_text_token_fallback=4.0,
    factsheet_limit=96,
    static_min_chars=2_000,
    tool_result_min_chars=6_000,
    max_images_per_request=64,
    max_images_per_tool_result=10,
    history_min_collapse_messages=10,
    history_collapse_grid_messages=50,
    history_freeze_grid_messages=10,
    history_keep_recent_messages=6,
)


def evaluation_recipe_from_config(config: Any) -> VisualCompressionRecipe:
    """TODO: STALE: Rebuild old benchmark variants as an explicit recipe.

    Only the opted-in local evaluation path may call this adapter. Production
    always uses ``PRODUCTION_RECIPE`` and therefore cannot be changed by the
    persisted benchmark fields retained for manifest compatibility.
    """
    variant_name = str(config_value(config, "render_variant", "v0_pxpipe"))
    profile_name = str(config_value(config, "render_profile", "calibrated"))
    return replace(
        PRODUCTION_RECIPE,
        recipe_id=f"evaluation:{profile_name}:{variant_name}",
        render_profile=resolve_render_profile(profile_name, variant_name),
        render_variant=resolve_render_variant(variant_name),
        image_cost_safety_margin=float(
            config_value(config, "image_cost_safety_margin", 1.10),
        ),
        max_visual_cost_ratio=float(
            config_value(config, "max_visual_cost_ratio", 0.90),
        ),
        chars_per_text_token_fallback=float(
            config_value(config, "chars_per_text_token", 4.0),
        ),
        factsheet_limit=(
            min(
                96,
                int(config_value(config, "factsheet_limit", 96)),
            )
            if bool(config_value(config, "emit_factsheet", True))
            else 0
        ),
        tool_result_min_chars=int(
            config_value(config, "min_block_chars", 6_000),
        ),
        max_images_per_request=min(
            64,
            int(config_value(config, "max_images_per_request", 64)),
        ),
        max_images_per_tool_result=min(
            10,
            int(config_value(config, "max_images_per_tool_result", 10)),
        ),
        history_collapse_grid_messages=int(
            config_value(config, "history_collapse_grid_messages", 50),
        ),
        history_freeze_grid_messages=int(
            config_value(config, "history_chunk_messages", 10),
        ),
        history_keep_recent_messages=int(
            config_value(config, "keep_recent_messages", 6),
        ),
    )


# These two projections are the production precision module's cycle-free
# defaults. They intentionally come from the same frozen recipe used by
# callers.
FACTSHEET_MAX_ENTRIES = PRODUCTION_RECIPE.factsheet_limit
FACTSHEET_PAGE_CHARS = PRODUCTION_RECIPE.readable_chars_per_image

# TODO: STALE: The remaining compatibility aliases are either unused or
# consumed only by ``CompressionEvaluation``. Delete them with benchmark
# evidence; new production code reads the frozen recipe directly.
CONFIG_SCHEMA_VERSION = PRODUCTION_RECIPE.config_schema_version
PIPELINE_VERSION = PRODUCTION_RECIPE.pipeline_version
RENDERER_VERSION = PRODUCTION_RECIPE.renderer_version
PRECISION_VERSION = PRODUCTION_RECIPE.precision_version
HISTORY_MAX_IMAGES = PRODUCTION_RECIPE.max_images_per_request
HISTORY_MIN_COLLAPSE_MESSAGES = PRODUCTION_RECIPE.history_min_collapse_messages
HISTORY_COLLAPSE_GRID_MESSAGES = (
    PRODUCTION_RECIPE.history_collapse_grid_messages
)
HISTORY_FREEZE_GRID_MESSAGES = PRODUCTION_RECIPE.history_freeze_grid_messages
HISTORY_KEEP_RECENT_MESSAGES = PRODUCTION_RECIPE.history_keep_recent_messages
STATIC_MIN_CHARS = PRODUCTION_RECIPE.static_min_chars


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "FACTSHEET_MAX_CHUNK_CHARS",
    "HISTORY_MAX_IMAGES",
    "HISTORY_MIN_COLLAPSE_MESSAGES",
    "HISTORY_COLLAPSE_GRID_MESSAGES",
    "HISTORY_FREEZE_GRID_MESSAGES",
    "HISTORY_KEEP_RECENT_MESSAGES",
    "FACTSHEET_MAX_DISTINCT",
    "FACTSHEET_MAX_ENTRIES",
    "FACTSHEET_MAX_SCAN_CHARS",
    "FACTSHEET_PAGE_CHARS",
    "PROFILES",
    "PIPELINE_VERSION",
    "PRECISION_VERSION",
    "PRODUCTION_RECIPE",
    "RENDER_VARIANTS",
    "ROLE_MARK_ASSISTANT",
    "ROLE_MARK_USER",
    "RENDERER_VERSION",
    "RenderProfile",
    "RenderVariant",
    "VisualCompressionRecipe",
    "SCHEMA_FORMAT_MAX_LENGTH",
    "SCHEMA_MAX_DEPTH",
    "STATIC_MIN_CHARS",
    "config_value",
    "evaluation_recipe_from_config",
    "resolve_render_profile",
    "resolve_render_variant",
]
