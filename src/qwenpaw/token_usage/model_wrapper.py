# -*- coding: utf-8 -*-
"""Model wrapper that records token usage from LLM responses."""

# TODO: STALE: These imports support only the temporary visual-compression
# benchmark trace. Remove them with the evaluation CLI.
import time
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from agentscope.message import TextBlock, ThinkingBlock, ToolCallBlock

from .buffer import _UsageEvent
from .manager import get_token_usage_manager


def _response_char_counts(response: Any) -> dict[str, int]:
    """Measure provider output characters for the temporary benchmark."""
    counts = {"text_chars": 0, "tool_use_chars": 0, "thinking_chars": 0}
    for block in getattr(response, "content", []) or []:
        if isinstance(block, TextBlock):
            counts["text_chars"] += len(block.text or "")
        elif isinstance(block, ThinkingBlock):
            counts["thinking_chars"] += len(block.thinking or "")
        elif isinstance(block, ToolCallBlock):
            counts["tool_use_chars"] += len(block.name or "") + len(
                block.input or "",
            )
    counts["output_chars"] = sum(counts.values())
    return counts


class TokenRecordingModelWrapper(
    ChatModelBase,
):  # pylint: disable=abstract-method
    """Wraps a ChatModelBase to record token usage on each call."""

    _usage_by_session: dict[str, dict[str, Any]] = {}
    # TODO: STALE: Per-call traces are consumed only by the temporary headless
    # benchmark CLI. Remove this state and its helpers with that CLI.
    _trace_by_session: dict[str, list[dict[str, Any]]] = {}

    def __init__(
        self,
        provider_id: str,
        model: ChatModelBase,
        compact_threshold: float | None = None,
    ) -> None:
        # agentscope 2.0 ChatModelBase requires credential/model/parameters.
        # Forward the wrapped model's own values so the base attributes stay
        # consistent (some downstream code reads ``self.model`` for logging).
        super().__init__(
            credential=getattr(model, "credential", None),
            model=getattr(model, "model", "unknown"),
            parameters=getattr(model, "parameters", None)
            or ChatModelBase.Parameters(),
            stream=getattr(model, "stream", True),
            context_size=getattr(model, "context_size", 32768),
        )
        self._model = model
        self._provider_id = provider_id
        # Auto-compaction threshold (fraction of the window) for the UI, or
        # None when compaction is disabled/unknown.
        self._compact_threshold = compact_threshold

    def _record_usage(
        self,
        usage: ChatUsage | None,
        call_meta: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        visual_receipt: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a usage event synchronously — never blocks the caller."""
        pt = getattr(usage, "input_tokens", 0) or 0 if usage else 0
        ct = getattr(usage, "output_tokens", 0) or 0 if usage else 0
        trace_enabled = session_id in self._trace_by_session
        if pt <= 0 and ct <= 0 and not trace_enabled:
            return

        now_iso = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        if pt > 0 or ct > 0:
            event = _UsageEvent(
                provider_id=self._provider_id,
                model_name=self.model,
                prompt_tokens=pt,
                completion_tokens=ct,
                date_str=date.today().isoformat(),
                now_iso=now_iso,
            )
            # Fire-and-forget: synchronous put_nowait, no await needed.
            get_token_usage_manager().enqueue(event)

        usage_data: dict[str, Any] = {
            "provider_id": self._provider_id,
            "model_name": self.model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            # Context window of the wrapped model, so the UI can show how full
            # the *current* context is (prompt_tokens / context_size), distinct
            # from the cumulative session totals. 0 = unknown.
            "context_size": int(getattr(self._model, "context_size", 0) or 0),
            # Auto-compaction threshold (fraction of the window) so the UI can
            # mark where context gets evicted. None = disabled/unknown.
            "compact_threshold": self._compact_threshold,
        }
        # TODO: STALE: A follow-up UI change may expose a content-safe boolean
        # saying whether this exact provider request was visually compressed.
        # Do not reuse the benchmark receipt here: it contains diagnostics and
        # may retain full recoverable source text. The first production PR
        # keeps the existing turn-usage payload unchanged.
        if pt > 0 or ct > 0:
            self._store_usage(usage_data, session_id=session_id)

        if not trace_enabled:
            return

        # TODO: STALE: Everything below in this method is benchmark-only.
        # Production turn usage does not need cache metrics, latency, output
        # character counts, or per-call traces.
        trace_data = {
            **usage_data,
            "visual_compression": visual_receipt,
            "cache_creation_input_tokens": (
                getattr(usage, "cache_creation_input_tokens", 0) or 0
                if usage
                else 0
            ),
            "cache_input_tokens": (
                getattr(usage, "cache_input_tokens", 0) or 0 if usage else 0
            ),
            "provider_time_seconds": (
                getattr(usage, "time", 0) or 0 if usage else 0
            ),
            "timing": call_meta or {},
        }
        self._store_trace(trace_data, session_id=session_id)

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    @classmethod
    def pop_trace_for_session(cls, session_id: str) -> list[dict[str, Any]]:
        """Return every model call in a turn/session, in request order."""
        return cls._trace_by_session.pop(session_id, [])

    @classmethod
    def start_trace_for_session(cls, session_id: str) -> None:
        """Opt one temporary benchmark session into per-call tracing."""
        cls._trace_by_session[session_id] = []

    @classmethod
    def trace_length_for_session(cls, session_id: str) -> int:
        """Return call count without consuming the durable trace."""
        return len(cls._trace_by_session.get(session_id, []))

    def _store_usage(
        self,
        usage: dict[str, Any] | None,
        *,
        session_id: str | None = None,
    ) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = session_id or get_current_session_id()
        if session_id and usage:
            self._usage_by_session[session_id] = usage

    def _store_trace(
        self,
        usage: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = session_id or get_current_session_id()
        # Normal production sessions are deliberately absent: otherwise this
        # benchmark-only map grows forever because only the headless CLI pops
        # it. ``start_trace_for_session`` is the explicit opt-in boundary.
        if session_id in self._trace_by_session:
            self._trace_by_session[session_id].append(usage)

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        messages = kwargs.get("messages", args[0] if args else None)
        # TODO: STALE: Timing/error/output metrics below support only the
        # temporary visual-compression benchmark. Receipt correlation is also
        # benchmark-only; production turn usage remains unchanged.
        trace_enabled = session_id in self._trace_by_session
        visual_receipt = None
        if trace_enabled and messages is not None:
            from ..agents.context.visual_compression.runtime import evaluation

            receipt = evaluation.get_request_receipt(messages)
            visual_receipt = receipt.to_dict() if receipt is not None else None
        started = time.perf_counter() if trace_enabled else None
        try:
            result = await self._model.generate_structured_output(
                *args,
                **kwargs,
            )
        except Exception as exc:
            if started is not None:
                elapsed = time.perf_counter() - started
                self._record_usage(
                    None,
                    {
                        "total_seconds": elapsed,
                        "ttft_seconds": elapsed,
                        "status": "error",
                        "error": str(exc),
                    },
                    session_id=session_id,
                    visual_receipt=visual_receipt,
                )
            raise
        call_meta = None
        if started is not None:
            elapsed = time.perf_counter() - started
            call_meta = {
                "total_seconds": elapsed,
                "ttft_seconds": elapsed,
                "status": "success",
                **_response_char_counts(result),
            }
        self._record_usage(
            getattr(result, "usage", None),
            call_meta,
            session_id=session_id,
            visual_receipt=visual_receipt,
        )
        return result

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        # agentscope 2.0 routes structured output through
        # ``generate_structured_output`` instead of a ``__call__`` kwarg, and
        # provider SDKs (anthropic, openai) reject unknown kwargs. Drop the
        # 1.x ``structured_model`` if a caller still passes it.
        kwargs.pop("structured_model", None)

        # Fix: Omit tool_choice="auto" for vLLM compatibility
        # vLLM without --enable-auto-tool-choice will reject requests when
        # tool_choice="auto" is present, even if tools are provided.
        # By omitting tool_choice when it's "auto", we bypass the check
        # while keeping tools available for correct tool calling behavior.
        if tool_choice == "auto":
            tool_choice = None

        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id()
        # TODO: STALE: Timing/error/output metrics below support only the
        # temporary visual-compression benchmark. Receipt correlation is also
        # benchmark-only; production turn usage remains unchanged.
        trace_enabled = session_id in self._trace_by_session
        request_visual_receipt = None
        if trace_enabled:
            from ..agents.context.visual_compression.runtime import evaluation

            receipt = evaluation.get_request_receipt(messages)
            request_visual_receipt = (
                receipt.to_dict() if receipt is not None else None
            )
        started = time.perf_counter() if trace_enabled else None
        try:
            result = await self._model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
        except Exception as exc:
            if started is not None:
                elapsed = time.perf_counter() - started
                self._record_usage(
                    None,
                    {
                        "total_seconds": elapsed,
                        "ttft_seconds": elapsed,
                        "status": "error",
                        "error": str(exc),
                    },
                    session_id=session_id,
                    visual_receipt=request_visual_receipt,
                )
            raise

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(
                result,
                started,
                session_id=session_id,
                visual_receipt=request_visual_receipt,
            )
        call_meta = None
        if started is not None:
            elapsed = time.perf_counter() - started
            call_meta = {
                "total_seconds": elapsed,
                "ttft_seconds": elapsed,
                "status": "success",
                **_response_char_counts(result),
            }
        self._record_usage(
            getattr(result, "usage", None),
            call_meta,
            session_id=session_id,
            visual_receipt=request_visual_receipt,
        )
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        started: float | None,
        *,
        session_id: str | None = None,
        visual_receipt: dict[str, Any] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        if started is None:
            async for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                yield chunk
            self._record_usage(
                last_usage,
                session_id=session_id,
                visual_receipt=visual_receipt,
            )
            return

        first_chunk_at: float | None = None
        output_counts = {
            "text_chars": 0,
            "tool_use_chars": 0,
            "thinking_chars": 0,
            "output_chars": 0,
        }
        try:
            async for chunk in stream:
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                if bool(getattr(chunk, "is_last", False)):
                    output_counts = _response_char_counts(chunk)
                yield chunk
        except Exception as exc:
            ended = time.perf_counter()
            self._record_usage(
                last_usage,
                {
                    "total_seconds": ended - started,
                    "ttft_seconds": (
                        (first_chunk_at - started)
                        if first_chunk_at is not None
                        else ended - started
                    ),
                    "status": "error",
                    "error": str(exc),
                    **output_counts,
                },
                session_id=session_id,
                visual_receipt=visual_receipt,
            )
            raise
        ended = time.perf_counter()
        self._record_usage(
            last_usage,
            {
                "total_seconds": ended - started,
                "ttft_seconds": (
                    (first_chunk_at - started)
                    if first_chunk_at is not None
                    else ended - started
                ),
                "status": "success",
                **output_counts,
            },
            session_id=session_id,
            visual_receipt=visual_receipt,
        )
