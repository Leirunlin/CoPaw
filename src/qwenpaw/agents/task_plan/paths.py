# -*- coding: utf-8 -*-
"""Path resolution shared by the GenUI router and the skill CLI scripts.

Both layers need the same policy: a caller-supplied name or relative path is
mapped to ``<workspace>/tasks/<name>.task.json``; absolute paths, wrong suffix,
and escapes outside the ``tasks/`` directory are rejected.
"""

from __future__ import annotations

from pathlib import Path

from .schema import TASK_DIR, TASK_FILE_SUFFIX


def tasks_dir(workspace: Path) -> Path:
    return workspace / TASK_DIR


def resolve_task_path(workspace: Path, name_or_path: str) -> Path | None:
    """Map *name_or_path* to ``<workspace>/tasks/<name>.task.json`` or None.

    Accepts ``add-login``, ``add-login.task.json``,
    ``tasks/add-login.task.json``. Legacy non-JSON task artifacts are
    rejected so new code only addresses canonical task-plan JSON files.
    Returns ``None`` for empty input, absolute paths, wrong suffix, or
    escapes outside ``<workspace>/tasks/``.
    """
    raw = (name_or_path or "").strip()
    if not raw:
        return None
    if raw.startswith(f"{TASK_DIR}/"):
        raw = raw[len(TASK_DIR) + 1 :]
    candidate = Path(raw)
    if candidate.is_absolute():
        return None
    if candidate.suffixes[-2:] == [".task", ".json"]:
        pass
    elif not candidate.suffix:
        candidate = Path(f"{candidate}{TASK_FILE_SUFFIX}")
    else:
        return None
    td = tasks_dir(workspace)
    resolved = (td / candidate).resolve()
    try:
        resolved.relative_to(td.resolve())
    except ValueError:
        return None
    return resolved


def rel_to_workspace(workspace: Path, p: Path) -> str:
    try:
        return str(p.relative_to(workspace))
    except ValueError:
        return str(p)
