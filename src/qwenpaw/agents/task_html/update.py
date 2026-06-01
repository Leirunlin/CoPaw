"""Surgical edits to a task HTML document.

The HTML on disk wraps a single
``<script type="application/json" id="task-doc">…</script>`` block that
holds the canonical data. Every mutation deserialises that JSON,
operates on the flat ``tasks`` list, and writes the JSON back inline —
the surrounding HTML/CSS/JS are preserved byte-stable.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .parse import _SCRIPT_RE
from .schema import (
    TASK_DOC_SCRIPT_ID,
    TASK_ID_RE,
    VALID_STATES,
)

# Fields a leaf task object can carry.
_TASK_FIELDS = (
    "id",
    "parent_id",
    "title",
    "state",
    "description",
    "outcome",
    "criteria",
    "test",
    "notes",
)

# Fields that may be patched in-place via set_task_field.
_PATCHABLE_FIELDS = frozenset(
    {"title", "state", "description", "outcome", "criteria", "test", "notes"},
)


# ---------------------------------------------------------------------------
# Load / dump the embedded JSON
# ---------------------------------------------------------------------------


def _load_doc(html: str) -> dict[str, Any]:
    m = _SCRIPT_RE.search(html)
    if m is None:
        raise ValueError(
            f'Missing <script id="{TASK_DOC_SCRIPT_ID}"> block.',
        )
    body = m.group("body").strip()
    if not body:
        return {"name": "", "version": "2", "tasks": []}
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"task-doc JSON malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("task-doc JSON must be an object.")
    data.setdefault("tasks", [])
    if not isinstance(data["tasks"], list):
        raise ValueError("task-doc 'tasks' must be a list.")
    return data


def _dump_doc(html: str, doc: dict[str, Any]) -> str:
    # Escape '</' so user-supplied text can't close the host <script> tag.
    raw = json.dumps(doc, ensure_ascii=False, indent=2).replace("</", "<\\/")
    new_body = "\n" + raw + "\n"

    def repl(match: re.Match[str]) -> str:
        full = match.group(0)
        body = match.group("body")
        idx = full.find(body)
        return full[:idx] + new_body + full[idx + len(body) :]

    return _SCRIPT_RE.sub(repl, html, count=1)


def _find_task(
    doc: dict[str, Any],
    task_id: str,
) -> Optional[dict[str, Any]]:
    for t in doc["tasks"]:
        if isinstance(t, dict) and t.get("id") == task_id:
            return t
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def set_task_field(
    html: str,
    task_id: str,
    **fields: Any,
) -> str:
    """Patch one or more fields on a task. Unknown fields are rejected."""
    if not TASK_ID_RE.match(task_id):
        raise ValueError(f"Invalid task_id {task_id!r}.")

    unknown = set(fields) - _PATCHABLE_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown patch fields: {sorted(unknown)}. "
            f"Allowed: {sorted(_PATCHABLE_FIELDS)}.",
        )

    state = fields.get("state")
    if state is not None and state not in VALID_STATES:
        raise ValueError(
            f"Invalid state {state!r}; expected one of {sorted(VALID_STATES)}.",
        )

    title = fields.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string.")

    doc = _load_doc(html)
    task = _find_task(doc, task_id)
    if task is None:
        raise ValueError(f"Task {task_id!r} not found in document.")

    for k, v in fields.items():
        if v is None:
            continue
        task[k] = v.strip() if k == "title" and isinstance(v, str) else v

    return _dump_doc(html, doc)


def set_task_state(
    html: str,
    task_id: str,
    new_state: str,
    notes: Optional[str] = None,
) -> str:
    """Patch ``state`` (and optionally ``notes``)."""
    payload: dict[str, Any] = {"state": new_state}
    if notes is not None:
        payload["notes"] = notes
    return set_task_field(html, task_id, **payload)


def set_task_title(html: str, task_id: str, new_title: str) -> str:
    return set_task_field(html, task_id, title=new_title)


def delete_task(html: str, task_id: str) -> str:
    """Remove a task and all its direct children (2-level: simple filter)."""
    if not TASK_ID_RE.match(task_id):
        raise ValueError(f"Invalid task_id {task_id!r}.")
    doc = _load_doc(html)
    before = len(doc["tasks"])
    doc["tasks"] = [
        t
        for t in doc["tasks"]
        if not (
            isinstance(t, dict)
            and (t.get("id") == task_id or t.get("parent_id") == task_id)
        )
    ]
    if len(doc["tasks"]) == before:
        raise ValueError(f"Task {task_id!r} not found in document.")
    return _dump_doc(html, doc)


def _next_available_id(tasks: list[dict[str, Any]], parent_id: str) -> str:
    """Compute the next dotted-id under *parent_id* (empty = top level)."""
    prefix = f"{parent_id}." if parent_id else "t-"
    used: set[int] = set()
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "")
        if parent_id:
            # Direct child of this parent: id starts with "<parent>." and no
            # further dot afterwards.
            if not tid.startswith(prefix):
                continue
            suffix = tid[len(prefix):]
        else:
            # Top level: id matches "t-N" with no dot.
            if not tid.startswith("t-") or "." in tid:
                continue
            suffix = tid[2:]
        try:
            used.add(int(suffix))
        except ValueError:
            continue
    n = 1
    while n in used:
        n += 1
    return f"{prefix}{n}"


def add_task(
    html: str,
    parent_id: str,
    title: str,
    **extra: Any,
) -> tuple[str, str]:
    """Append a new task. Returns ``(new_html, new_task_id)``.

    *parent_id* must reference an existing top-level task (or be empty).
    Sub-tasks of sub-tasks (3-level nesting) are rejected.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string.")
    doc = _load_doc(html)

    if parent_id:
        if not TASK_ID_RE.match(parent_id):
            raise ValueError(f"Invalid parent_id {parent_id!r}.")
        parent = _find_task(doc, parent_id)
        if parent is None:
            raise ValueError(f"Parent {parent_id!r} not found.")
        if parent.get("parent_id"):
            raise ValueError(
                f"Cannot nest under {parent_id!r}: 2-level limit.",
            )

    new_id = _next_available_id(doc["tasks"], parent_id)
    task: dict[str, Any] = {
        "id": new_id,
        "parent_id": parent_id,
        "title": title.strip(),
        "state": "todo",
        "description": "",
        "outcome": "",
        "criteria": "",
        "test": "",
        "notes": "",
    }
    for k in ("description", "outcome", "criteria", "test", "state", "notes"):
        v = extra.get(k)
        if v is None:
            continue
        if k == "state" and v not in VALID_STATES:
            raise ValueError(
                f"Invalid state {v!r}; "
                f"expected one of {sorted(VALID_STATES)}.",
            )
        task[k] = v

    doc["tasks"].append(task)
    return _dump_doc(html, doc), new_id


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate(html: str) -> list[str]:
    """Return validation errors (empty list = OK)."""
    try:
        doc = _load_doc(html)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    tasks = doc.get("tasks") or []
    seen_ids: set[str] = set()
    top_level_ids: set[str] = set()

    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            errors.append(f"tasks[{i}] is not an object.")
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            errors.append(f"tasks[{i}] missing id.")
            continue
        if not TASK_ID_RE.match(tid):
            errors.append(
                f"Malformed task id {tid!r} "
                "(allowed: 't-N' or 't-N.M' — 2-level only).",
            )
        if tid in seen_ids:
            errors.append(f"Duplicate task id {tid!r}.")
        seen_ids.add(tid)

        state = str(t.get("state") or "").strip()
        if state and state not in VALID_STATES:
            errors.append(f"Task {tid!r} has invalid state {state!r}.")

        parent = str(t.get("parent_id") or "").strip()
        if not parent:
            top_level_ids.add(tid)

    # Re-walk for parent integrity (need full id set).
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        parent = str(t.get("parent_id") or "").strip()
        if not parent:
            continue
        if parent not in seen_ids:
            errors.append(
                f"Task {tid!r} references missing parent {parent!r}.",
            )
            continue
        if parent not in top_level_ids:
            errors.append(
                f"Task {tid!r} parent {parent!r} is itself a sub-task "
                "(2-level limit).",
            )
        if "." in parent:
            # Caught above too, but explicit message helps the LLM.
            errors.append(
                f"Task {tid!r}: parent_id {parent!r} must be top level.",
            )

    return errors
