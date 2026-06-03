# -*- coding: utf-8 -*-
"""Parse task plan JSON → :class:`TaskDoc`.

The durable task state is plain JSON. A2UI surfaces are generated from this
domain document, and user edits are written back to the same file before the
agent continues. Field defaults are filled in for older docs.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .schema import (
    DOC_VERSION,
    TASK_ID_RE,
    Task,
    TaskDoc,
    TaskState,
    VALID_STATES,
)


def _coerce_task(raw: Any) -> Optional[Task]:
    if not isinstance(raw, dict):
        return None
    tid = str(raw.get("id") or "").strip()
    if not tid or not TASK_ID_RE.match(tid):
        return None
    state = str(raw.get("state") or TaskState.TODO.value).strip()
    if state not in VALID_STATES:
        state = TaskState.TODO.value
    return Task(
        id=tid,
        parent_id=str(raw.get("parent_id") or "").strip(),
        title=str(raw.get("title") or "").strip(),
        state=state,
        description=str(raw.get("description") or ""),
        outcome=str(raw.get("outcome") or ""),
        criteria=str(raw.get("criteria") or ""),
        test=str(raw.get("test") or "").strip(),
        notes=str(raw.get("notes") or ""),
    )


def parse_task_doc(text: str) -> TaskDoc:
    """Parse *text* into a :class:`TaskDoc`.

    Raises ``ValueError`` if the JSON is malformed or the top-level shape is
    not a task document. Invalid individual task rows are ignored here; strict
    writer validation lives in :mod:`.update`.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"task plan JSON is malformed: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("task plan JSON must be an object.")

    tasks_raw = data.get("tasks") or []
    if not isinstance(tasks_raw, list):
        raise ValueError("task-doc 'tasks' must be a list.")

    tasks: list[Task] = []
    for item in tasks_raw:
        t = _coerce_task(item)
        if t is not None:
            tasks.append(t)

    return TaskDoc(
        name=str(data.get("name") or ""),
        version=str(data.get("version") or DOC_VERSION),
        tasks=tasks,
    )


def dump_task_doc(doc: dict[str, Any]) -> str:
    """Serialize a task plan dict in the canonical on-disk format."""
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


_SORT_LAST = (10**9,)


def _id_key(task_id: str) -> tuple[int, ...]:
    """Convert ``t-1.2`` to a sortable tuple ``(1, 2)``.

    Malformed ids (would only reach here if a future schema change
    relaxed ``TASK_ID_RE``) sort last instead of raising.
    """
    body = task_id[2:] if task_id.startswith("t-") else task_id
    try:
        return tuple(int(p) for p in body.split("."))
    except ValueError:
        return _SORT_LAST


_BLOCKING_PARENT_STATES = frozenset(
    {
        TaskState.SKIPPED.value,
        TaskState.BLOCKED.value,
        TaskState.FAILED.value,
    },
)


def find_next_runnable(doc: TaskDoc) -> Optional[Task]:
    """Pick the next leaf-todo task whose ancestors are all unblocked.

    Sorted by dotted-id order — produces "top-level serial, sibling
    sub-tasks ordered by id". SKILL.md tells the agent that sibling
    sub-tasks under one parent MAY be batched when independent; this
    function returns one task at a time.
    """
    ordered = sorted(doc.tasks, key=lambda t: _id_key(t.id))
    by_id = {t.id: t for t in ordered}
    has_child: set[str] = {t.parent_id for t in ordered if t.parent_id}

    # Resume mid-flight tasks first.
    for t in ordered:
        if t.state == TaskState.IN_PROGRESS.value and t.id not in has_child:
            return t

    def unblocked(t: Task) -> bool:
        cur = by_id.get(t.parent_id)
        while cur is not None:
            if cur.state in _BLOCKING_PARENT_STATES:
                return False
            cur = by_id.get(cur.parent_id)
        return True

    for t in ordered:
        if (
            t.state == TaskState.TODO.value
            and t.id not in has_child
            and unblocked(t)
        ):
            return t
    return None
