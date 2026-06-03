# -*- coding: utf-8 -*-
"""Task plan schema: constants, dataclasses, enums.

The canonical task data is a JSON document under ``<workspace>/tasks``.
Generated UI is a projection of that JSON into A2UI envelopes; A2UI state is
never the durable source of truth. This keeps agent reads, user edits, and live
UI updates pointed at the same domain object.

Hierarchy is capped at TWO levels (top-level "stage" + direct children).
Top-level tasks execute SERIALLY; same-parent sub-tasks MAY run in
parallel when independent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

TASK_DIR = "tasks"
TASK_FILE_SUFFIX = ".task.json"
DOC_VERSION = "2"

# Dotted-path task ids: t-1 or t-1.1 (≤ 2 levels in v4).
TASK_ID_RE = re.compile(r"^t-\d+(?:\.\d+)?$")

# Cap a single task plan JSON document at 2 MiB.
MAX_TASK_BYTES = 2 * 1024 * 1024


class TaskState(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


VALID_STATES: frozenset[str] = frozenset(s.value for s in TaskState)


@dataclass
class Task:
    id: str
    parent_id: str
    title: str
    state: str = "todo"
    description: str = ""
    outcome: str = ""
    criteria: str = ""
    test: str = ""
    notes: str = ""


@dataclass
class TaskDoc:
    name: str
    version: str
    tasks: list[Task]
