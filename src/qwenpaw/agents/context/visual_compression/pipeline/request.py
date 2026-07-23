# -*- coding: utf-8 -*-
"""Provider-independent context planning and request transformation.

The transformer works on deep copies of ``Msg`` objects. Images remain
AgentScope ``DataBlock`` instances until the active formatter builds the wire.
Tool documentation follows one provider-independent QwenPaw-native policy.
"""

from __future__ import annotations

import json
import time
from typing import Any

from agentscope.message import Msg, TextBlock

from .....constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

from ..config import (
    PRODUCTION_RECIPE,
    VisualCompressionRecipe,
    config_value,
    evaluation_recipe_from_config,
)
from .receipt import (
    CompressionEvaluation,
    CompressionReceipt,
    evaluation_config_hash,
    finish_evaluation,
    record_render_geometry,
)
from .history import compress_history
from .budget import RequestBudget
from .messages import MediaInventory, estimate_request_tokens, inspect_media
from .static_context import compress_static_context, wrap_env_tail
from .tool_results import compress_tool_results


def _is_external_user(message: Msg) -> bool:
    """Whether one canonical message is the live external user request."""
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    return (
        message.role == "user"
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        == EXTERNAL_USER_QUERY_MESSAGE_TAG
    )


def _append_env_tail(messages: list[Msg], env_tail: str) -> None:
    """Append the complete dynamic env block to the real external user."""
    if not env_tail.strip():
        return
    wrapped = wrap_env_tail(env_tail)
    for message in reversed(messages):
        if _is_external_user(message):
            message.content.append(TextBlock(text=wrapped))
            return

    # A very long same-turn tool loop may have pushed the external user into a
    # frozen history chunk. Never drop host context: restore it to native
    # system authority instead of manufacturing a new user message.
    for message in messages:
        if message.role == "system":
            message.content.append(TextBlock(text=env_tail.strip()))
            return


def _validate_media_invariants(
    messages: list[Msg],
    original: MediaInventory,
    budget: RequestBudget,
) -> None:
    """Fail open at middleware level if a transform loses native media."""
    final = inspect_media(messages)
    if (
        final.audio != original.audio
        or final.video != original.video
        or final.files != original.files
        or final.unknown != original.unknown
        or final.images < original.images
    ):
        raise RuntimeError("visual compression changed original media")
    if final.images - original.images > budget.generated_images:
        raise RuntimeError("visual compression exceeded image allowance")


# TODO: STALE cleanup guide for the production PR:
# 1. Remove ``time``, ``CompressionEvaluation``, evaluation helpers, and
#    ``evaluation_recipe_from_config`` from this module.
# 2. Remove the benchmark-only ``model`` and ``recipe`` parameters below;
#    production always reads the immutable ``PRODUCTION_RECIPE``. Model media
#    capability remains the middleware's responsibility through QwenPaw's
#    existing capability registry.
# 3. Remove ``receipt_dir``, ``collect_evaluation``, ``started``, ``arm``, the
#    optional evaluation object, original-token accounting, and geometry
#    recording. The middleware already owns the production enabled gate.
# 4. Delete the nested ``finish`` helper instead of promoting it to a module
#    abstraction: it exists only to finalize temporary benchmark evidence.
# 5. Return ``(cloned, copied_tools, receipt)`` after env-tail placement and
#    media invariants. What remains should read as copy -> media inventory ->
#    static -> immutable history -> recent tool results -> env tail ->
#    invariants, with no provider/evaluation branching.
def transform_model_request(
    messages: list[Msg],
    tools: list[dict] | None,
    *,
    config: Any,
    # TODO: STALE: Benchmark-only inputs. Production always uses the immutable
    # recipe and does not need a model id; model capability is checked by the
    # middleware through QwenPaw's existing capability registry.
    model: str = "",
    recipe: VisualCompressionRecipe | None = None,
) -> tuple[list[Msg], list[dict] | None, CompressionReceipt]:
    """Apply the provider-independent production compression pipeline."""
    # TODO: STALE: BEGIN temporary evaluation setup. The production path uses
    # ``PRODUCTION_RECIPE`` and leaves ``evaluation`` unset. Delete this setup
    # with the benchmark CLI and the evaluation receipt payload.
    receipt_dir = config_value(config, "receipt_dir", None)
    # TODO: STALE: ``record_factsheet_text`` and ``receipt_dir`` are the two
    # temporary benchmark opt-ins. They also gate all expensive receipt work
    # so ordinary production requests do not hash/copy the complete request.
    collect_evaluation = bool(
        config_value(config, "record_factsheet_text", False) or receipt_dir,
    )
    if recipe is None:
        recipe = (
            evaluation_recipe_from_config(config)
            if collect_evaluation
            else PRODUCTION_RECIPE
        )
    started = time.perf_counter() if collect_evaluation else None
    # TODO: STALE: ``experiment_arm`` exists only for paired benchmark runs.
    # Missing means the normal production path is ON so removing that field
    # later cannot silently disable an enabled configuration.
    arm = (
        str(config_value(config, "experiment_arm", "on"))
        if collect_evaluation
        else "on"
    )
    evaluation = (
        CompressionEvaluation(
            recipe_id=recipe.recipe_id,
            config_schema_version=recipe.config_schema_version,
            pipeline_version=recipe.pipeline_version,
            # TODO: STALE: Benchmark fingerprint for the single production
            # policy; remove with ``CompressionEvaluation``.
            tool_policy="qwenpaw-native-v1",
            renderer_version=recipe.renderer_version,
            precision_version=recipe.precision_version,
            model=model,
            arm=arm,
            config_hash=evaluation_config_hash(config),
            receipt_dir=receipt_dir,
        )
        if collect_evaluation
        else None
    )
    # TODO: STALE: END temporary evaluation setup.
    receipt = CompressionReceipt(
        recipe_id=recipe.recipe_id,
        evaluation=evaluation,
    )
    cloned = [
        Msg.model_validate(msg.model_dump(mode="json")) for msg in messages
    ]
    copied_tools = (
        json.loads(json.dumps(tools, ensure_ascii=False))
        if tools is not None
        else None
    )
    planning_cpt = recipe.chars_per_text_token_fallback
    # TODO: STALE: Original-token accounting is benchmark-only.
    if evaluation is not None:
        evaluation.original_estimated_tokens = estimate_request_tokens(
            cloned,
            copied_tools,
            planning_cpt,
        )

    def finish(
        reason: str,
    ) -> tuple[list[Msg], list[dict] | None, CompressionReceipt]:
        """TODO: STALE finalize optional benchmark evidence."""
        receipt.reason = reason
        finish_evaluation(
            receipt,
            cloned,
            copied_tools,
            keep_recent=recipe.history_keep_recent_messages,
            planning_cpt=planning_cpt,
            started=started,
        )
        return cloned, copied_tools, receipt

    if not bool(config_value(config, "enabled", False)) or arm not in {
        "on",
        "on_nofactsheet",
    }:
        return finish("disabled")
    # TODO: STALE: Renderer geometry is recorded only for benchmark evidence.
    record_render_geometry(receipt, recipe)
    # Native images are correctness-owned by QwenPaw's normal formatter. They
    # are never removed to make room for synthetic pages; an already-oversized
    # request therefore receives no additional visual-compression images.
    media = inspect_media(cloned)
    request_budget = RequestBudget.from_image_count(
        recipe.max_images_per_request,
        images=media.images,
    )
    pages_left = request_budget.generated_images
    can_relocate_env_tail = any(_is_external_user(msg) for msg in cloned)
    (
        cloned,
        copied_tools,
        pages_left,
        env_tail,
    ) = compress_static_context(
        cloned,
        copied_tools,
        config,
        receipt,
        pages_left,
        recipe,
        relocate_env_tail=can_relocate_env_tail,
    )
    # Freeze history from untouched canonical tool results first. This makes
    # history the stable cache prefix and prevents an intermediate tool-result
    # image from being serialized as ``[image]`` and discarded.
    history_budget = min(pages_left, recipe.max_images_per_request)
    cloned, history_pages_left = compress_history(
        cloned,
        config,
        receipt,
        history_budget,
        recipe,
    )
    pages_left -= history_budget - history_pages_left
    pages_left = compress_tool_results(
        cloned,
        config,
        receipt,
        pages_left,
        recipe,
    )
    _append_env_tail(cloned, env_tail)
    _validate_media_invariants(cloned, media, request_budget)
    return finish("applied" if receipt.applied else "nothing_profitable")


__all__ = ["transform_model_request"]
