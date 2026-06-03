# -*- coding: utf-8 -*-
"""Surgical edits to a task plan JSON document.

Every mutation deserializes the canonical task JSON, edits the flat ``tasks``
list, validates the resulting domain document, and returns canonical JSON text.
The A2UI layer only projects this state and sends user edits back here.
"""

from __future__ import annotations

import json
from typing import Any

from .parse import dump_task_doc
from .schema import DOC_VERSION, TASK_ID_RE, VALID_STATES

# Fields that may be patched in-place via set_task_field.
_PATCHABLE_FIELDS = frozenset(
    {"title", "state", "description", "outcome", "criteria", "test", "notes"},
)


# ---------------------------------------------------------------------------
# Load / dump canonical JSON
# ---------------------------------------------------------------------------


def _load_doc(text: str) -> dict[str, Any]:
    body = text.strip()
    if not body:
        return {"name": "", "version": DOC_VERSION, "tasks": []}
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"task plan JSON malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("task plan JSON must be an object.")
    data.setdefault("version", DOC_VERSION)
    data.setdefault("tasks", [])
    if not isinstance(data["tasks"], list):
        raise ValueError("task plan 'tasks' must be a list.")
    return data


def _find_task(
    doc: dict[str, Any],
    task_id: str,
) -> dict[str, Any] | None:
    for t in doc["tasks"]:
        if isinstance(t, dict) and t.get("id") == task_id:
            return t
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def set_task_field(
    text: str,
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
            f"Invalid state {state!r}; "
            f"expected one of {sorted(VALID_STATES)}.",
        )

    title = fields.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string.")

    doc = _load_doc(text)
    task = _find_task(doc, task_id)
    if task is None:
        raise ValueError(f"Task {task_id!r} not found in document.")

    for k, v in fields.items():
        if v is None:
            continue
        task[k] = v.strip() if k == "title" and isinstance(v, str) else v

    errors = validate_doc(doc)
    if errors:
        raise ValueError("; ".join(errors))
    return dump_task_doc(doc)


def delete_task(text: str, task_id: str) -> str:
    """Remove a task and all its direct children (2-level: simple filter)."""
    if not TASK_ID_RE.match(task_id):
        raise ValueError(f"Invalid task_id {task_id!r}.")
    doc = _load_doc(text)
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
    errors = validate_doc(doc)
    if errors:
        raise ValueError("; ".join(errors))
    return dump_task_doc(doc)


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
            suffix = tid[len(prefix) :]
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
    text: str,
    parent_id: str,
    title: str,
    **extra: Any,
) -> tuple[str, str]:
    """Append a new task. Returns ``(new_text, new_task_id)``.

    *parent_id* must reference an existing top-level task (or be empty).
    Sub-tasks of sub-tasks (3-level nesting) are rejected.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string.")
    doc = _load_doc(text)

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
    errors = validate_doc(doc)
    if errors:
        raise ValueError("; ".join(errors))
    return dump_task_doc(doc), new_id


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate_doc(doc: dict[str, Any]) -> list[str]:
    # pylint: disable=too-many-branches
    """Return validation errors for an already-loaded doc."""
    if not isinstance(doc.get("name", ""), str):
        return ["name must be a string."]

    try:
        tasks = doc.get("tasks") or []
    except AttributeError:
        return ["task plan must be an object."]

    errors: list[str] = []
    if not isinstance(tasks, list):
        return ["tasks must be a list."]
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


def validate(text: str) -> list[str]:
    """Return validation errors for task JSON text (empty list = OK)."""
    try:
        doc = _load_doc(text)
    except ValueError as exc:
        return [str(exc)]
    return validate_doc(doc)
