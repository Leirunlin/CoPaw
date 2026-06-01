"""Path resolution shared by the REST router and the skill CLI scripts.

Both layers need the same policy: a caller-supplied name or relative path is
mapped to ``<workspace>/tasks/<name>.html``; absolute paths, wrong suffix,
and escapes outside the ``tasks/`` directory are rejected.
"""
from __future__ import annotations

from pathlib import Path

from .schema import TASK_HTML_DIR


def tasks_dir(workspace: Path) -> Path:
    return workspace / TASK_HTML_DIR


def resolve_task_path(workspace: Path, name_or_path: str) -> Path | None:
    """Map *name_or_path* to ``<workspace>/tasks/<name>.html`` or return None.

    Accepts ``add-login``, ``add-login.html``, ``tasks/add-login.html``.
    Returns ``None`` for empty input, absolute paths, wrong suffix, or
    escapes outside ``<workspace>/tasks/``.
    """
    raw = (name_or_path or "").strip()
    if not raw:
        return None
    if raw.startswith(f"{TASK_HTML_DIR}/"):
        raw = raw[len(TASK_HTML_DIR) + 1 :]
    candidate = Path(raw)
    if candidate.is_absolute():
        return None
    if not candidate.suffix:
        candidate = candidate.with_suffix(".html")
    if candidate.suffix.lower() != ".html":
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
