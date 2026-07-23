# -*- coding: utf-8 -*-
"""AgentScope pre-model hook for request-time visual compression."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from agentscope.middleware import MiddlewareBase

from .recovery import set_recoverable_blocks

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentscope.agent import Agent


def _model_key(current_model: Any) -> str | None:
    """Return QwenPaw's exact per-model capability-cache key."""
    try:
        key = getattr(current_model, "model_key", None)
    except Exception:  # pragma: no cover - defensive third-party model
        return None
    return key if isinstance(key, str) and key else None


def _agent_will_strip_media(
    agent: "Agent",
    current_model: Any = None,
) -> bool:
    """Whether QwenPaw will discard media for this exact model call."""
    formatter = getattr(agent, "formatter", None)
    if bool(getattr(formatter, "_qwenpaw_force_strip_media", False)):
        return True
    key = _model_key(current_model)
    if key is not None:
        from .....providers.model_capability_cache import get_capability_cache

        return bool(
            get_capability_cache().get(key, "rejects_media", False),
        )
    rejects_media = getattr(agent, "_model_rejects_media", None)
    if not callable(rejects_media):
        return False
    try:
        return bool(rejects_media())
    except Exception:  # pragma: no cover - defensive host integration
        logger.debug(
            "Could not read the agent's learned media capability",
            exc_info=True,
        )
        return False


class VisualCompressionMiddleware(MiddlewareBase):
    """Rewrite one prepared request immediately before provider I/O."""

    def __init__(self, config: Any) -> None:
        self._visual_config = config

    async def on_model_call(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        if not self._visual_config.enabled:
            set_recoverable_blocks([])
            return await next_handler(**input_kwargs)

        from ....prompt import get_model_supports_image

        current_model = input_kwargs.get("current_model")
        if _agent_will_strip_media(
            agent,
            current_model,
        ) or not get_model_supports_image(current_model):
            set_recoverable_blocks([])
            return await next_handler(**input_kwargs)

        request = dict(input_kwargs)
        messages = request.get("messages") or []
        tools = request.get("tools")
        try:
            from ..pipeline.request import transform_model_request

            transformed, transformed_tools, receipt = transform_model_request(
                messages,
                tools,
                config=self._visual_config,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Visual compression failed; sending the original request",
            )
            set_recoverable_blocks([])
            return await next_handler(**request)
        set_recoverable_blocks(receipt.recoverable)
        request["messages"] = transformed
        request["tools"] = transformed_tools

        # TODO: STALE: Receipt correlation and PNG persistence serve only the
        # temporary benchmark. Keep them outside the production transform
        # failure boundary: evaluation I/O must never disable compression.
        # Only bind the object reference; the opted-in benchmark trace is
        # responsible for the potentially expensive ``to_dict`` copy.
        receipt_evaluation = receipt.evaluation
        if receipt_evaluation is not None and receipt_evaluation.receipt_dir:
            try:
                from .evaluation import (
                    persist_page_artifacts,
                    set_request_receipt,
                )

                set_request_receipt(transformed, receipt)
                persist_page_artifacts(receipt)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Visual-compression evaluation capture failed",
                    exc_info=True,
                )
        return await next_handler(**request)


__all__ = ["VisualCompressionMiddleware"]
