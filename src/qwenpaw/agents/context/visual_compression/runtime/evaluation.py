# -*- coding: utf-8 -*-
"""Temporary benchmark receipt correlation and PNG persistence.

TODO: STALE: This entire module supports only the local evaluation/reviewer
workflow. Remove it together with the benchmark CLI, ``receipt_dir``, trace
collection, and receipt artifact fields before the production PR.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ..pipeline.receipt import CompressionReceipt

_request_receipt: ContextVar[tuple[object, Any] | None] = ContextVar(
    "qwenpaw_visual_compression_request_receipt",
    default=None,
)


def set_request_receipt(messages: object, receipt: Any) -> None:
    """Bind a benchmark receipt to the exact transformed request object."""
    _request_receipt.set((messages, receipt))


def get_request_receipt(messages: object) -> Any | None:
    """Return the benchmark receipt only for this request message list."""
    current = _request_receipt.get()
    if current is None or current[0] is not messages:
        return None
    return current[1]


def persist_page_artifacts(receipt: CompressionReceipt) -> None:
    """Write optional benchmark PNGs after the pure transform finishes."""
    evidence = receipt.evaluation
    if evidence is None:
        return
    pending = evidence.pending_page_artifacts
    if not evidence.receipt_dir or not pending:
        return
    try:
        image_dir = Path(evidence.receipt_dir).expanduser() / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        for region, sha256, png in pending:
            image_path = image_dir / f"{region}-{sha256[:16]}.png"
            if not image_path.exists():
                image_path.write_bytes(png)
            evidence.image_paths.append(str(image_path.resolve()))
    except OSError as exc:
        evidence.artifact_error = str(exc)
    finally:
        pending.clear()


__all__ = [
    "get_request_receipt",
    "persist_page_artifacts",
    "set_request_receipt",
]
