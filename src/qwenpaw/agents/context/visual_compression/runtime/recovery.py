# -*- coding: utf-8 -*-
"""Turn-local source storage and exact visual-context recovery tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk


class TurnRecoveryStore:
    """Exact visual sources shared by one agent turn.

    The runtime heartbeat advances the agent stream in short-lived asyncio
    tasks, so task-local state such as ``ContextVar`` cannot bridge a model
    call and its subsequent tool call.  A store instance is instead created
    by ``AgentBuilder`` and shared explicitly by the visual middleware and
    recovery tool for the lifetime of one ``Runtime.run``.
    """

    def __init__(self) -> None:
        self._blocks: dict[str, str] = {}

    def replace(self, blocks: list[dict[str, Any]]) -> None:
        """Atomically replace sources exposed by the current model request."""
        self._blocks = {
            str(item.get("id")): str(item.get("text", ""))
            for item in blocks
            if item.get("id")
        }

    def clear(self) -> None:
        """Expire all sources from the preceding model request."""
        self._blocks = {}

    def recover(self, block_id: str) -> str | None:
        """Return one exact source block while this turn remains active."""
        return self._blocks.get(block_id)

    def excerpt(  # pylint: disable=R0911,R0914
        self,
        block_id: str,
        *,
        query: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int = 12_000,
    ) -> str:
        """Return a bounded excerpt without recreating a huge context loop."""
        value = self.recover(block_id)
        if value is None:
            return f"Unknown or expired visual context id: {block_id}"
        lines = value.splitlines()
        if query:
            needle = query.casefold()
            matched = [
                idx
                for idx, line in enumerate(lines)
                if needle in line.casefold()
            ]
            if not matched:
                return (
                    f"No exact line containing {query!r} in {block_id}; "
                    f"source has {len(lines)} lines. Try a shorter query."
                )
            selected: set[int] = set()
            for idx in matched[:64]:
                selected.update(
                    range(max(0, idx - 2), min(len(lines), idx + 3)),
                )
            body = "\n".join(
                f"{idx + 1}: {lines[idx]}" for idx in sorted(selected)
            )
            return body[:max_chars]
        if start_line is not None or end_line is not None:
            start = max(1, int(start_line or 1))
            end = min(len(lines), int(end_line or start + 199))
            if end < start:
                return f"Invalid line range: {start}..{end}"
            body = "\n".join(
                f"{idx + 1}: {lines[idx]}" for idx in range(start - 1, end)
            )
            return body[:max_chars]
        if len(value) <= max_chars:
            return value
        head = "\n".join(
            f"{idx + 1}: {line}" for idx, line in enumerate(lines[:30])
        )
        tail_start = max(30, len(lines) - 15)
        tail = "\n".join(
            f"{idx + 1}: {lines[idx]}" for idx in range(tail_start, len(lines))
        )
        return (
            f"Visual source {block_id} has {len(lines)} lines and "
            f"{len(value)} chars. Full recovery is intentionally not returned "
            "in one tool result because that would recreate the compressed "
            "context. Call again with query=... "
            "or start_line/end_line.\n\n"
            f"[HEAD]\n{head}\n\n[TAIL]\n{tail}"
        )[:max_chars]


def make_recover_visual_context_tool(
    store: TurnRecoveryStore,
) -> Callable[..., Awaitable[ToolChunk]]:
    """Bind the built-in recovery tool to one turn-local store."""

    async def recover_visual_context(
        block_id: str,
        query: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolChunk:
        """Recover byte-exact text represented by a visual context block.

        Use this only when an image is ambiguous or the task requires a
        verbatim value that is absent from the adjacent exact-token factsheet.

        Args:
            block_id: The ``vctx_...`` recovery id shown next to a visual
                block.
            query: Preferred exact substring to find; returns matching lines
                with bounded context instead of replaying the whole block.
            start_line: Optional 1-based exact line-range start.
            end_line: Optional 1-based exact line-range end.
        """
        text = store.excerpt(
            block_id,
            query=query,
            start_line=start_line,
            end_line=end_line,
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(text=text)],
        )

    return recover_visual_context


__all__ = [
    "TurnRecoveryStore",
    "make_recover_visual_context_tool",
]
