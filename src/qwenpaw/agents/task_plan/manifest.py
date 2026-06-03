# -*- coding: utf-8 -*-
"""Per-workspace task plan manifest — extension-only metadata store.

Holds fields that the task domain document does not need to carry:
user-supplied summary, original creation timestamp, cached display name.
Progress / state / next_runnable always come from parsing the live task JSON,
NOT from here — the manifest never duplicates task state, so writers that
mutate task state don't have to keep two places in sync.

Authority: task JSON is canonical for everything in :mod:`task_plan.schema`.
Manifest is a soft cache. ``read_manifest`` returns ``{}`` on missing or
corrupt files; ``upsert_entry`` does an atomic tempfile + rename.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .schema import TASK_DIR

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"


def manifest_path(workspace: Path) -> Path:
    return workspace / TASK_DIR / MANIFEST_NAME


def read_manifest(workspace: Path) -> dict[str, dict]:
    """Return ``{stem: entry}`` or ``{}`` if file missing / unparseable.

    Never raises. A corrupt or schema-mismatched manifest is treated as
    empty so a malformed file can't break ``list.py``.
    """
    p = manifest_path(workspace)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("task manifest unreadable at %s: %s", p, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return {}
    return {str(k): dict(v) for k, v in tasks.items() if isinstance(v, dict)}


def _write_atomic(workspace: Path, tasks: dict[str, dict]) -> None:
    p = manifest_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tasks": tasks}
    fd, tmp = tempfile.mkstemp(
        prefix=f".{MANIFEST_NAME}.",
        suffix=".tmp",
        dir=str(p.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def upsert_entry(
    workspace: Path,
    stem: str,
    *,
    name: str,
    summary: str,
    created: str,
) -> None:
    """Insert or replace a manifest entry. Atomic write."""
    tasks = read_manifest(workspace)
    tasks[stem] = {"name": name, "summary": summary, "created": created}
    _write_atomic(workspace, tasks)


def remove_entry(workspace: Path, stem: str) -> None:
    """Drop a manifest entry. No-op if absent. Atomic write."""
    tasks = read_manifest(workspace)
    if stem not in tasks:
        return
    del tasks[stem]
    _write_atomic(workspace, tasks)
