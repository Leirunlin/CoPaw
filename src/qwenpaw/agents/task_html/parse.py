"""Parse task HTML → :class:`TaskDoc`.

The canonical state is the JSON object inside the embedded
``<script type="application/json" id="task-doc">…</script>`` block.
We locate it by regex (faster + tolerant of HTML quirks) and decode
it with the stdlib ``json`` parser. Field defaults are filled in if
older docs lack the v4 additions (``description`` / ``outcome`` /
``criteria``).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .schema import (
    DOC_VERSION,
    TASK_DOC_SCRIPT_ID,
    TASK_ID_RE,
    Task,
    TaskDoc,
    TaskState,
    VALID_STATES,
)

# Match the data script tag (id may appear in any attr order; case-insensitive).
_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\bid\s*=\s*"' + re.escape(TASK_DOC_SCRIPT_ID) + r'"[^>]*>'
    r"(?P<body>.*?)</script\s*>",
    re.DOTALL | re.IGNORECASE,
)


def _extract_doc_json(html: str) -> Optional[str]:
    m = _SCRIPT_RE.search(html)
    return m.group("body") if m else None


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


def parse_task_doc(html: str) -> TaskDoc:
    """Parse *html* into a :class:`TaskDoc`. Raises ``ValueError`` if the
    script tag is missing or its JSON is malformed."""
    raw = _extract_doc_json(html)
    if raw is None:
        raise ValueError(
            f'Not a task HTML document: missing '
            f'<script id="{TASK_DOC_SCRIPT_ID}">.',
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"task-doc JSON is malformed: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("task-doc JSON must be an object.")

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
