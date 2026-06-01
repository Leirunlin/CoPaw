"""Task HTML schema: constants, dataclasses, enums.

The canonical task data lives inside a single embedded
``<script type="application/json" id="task-doc">…</script>`` block in
the HTML file. The surrounding HTML/CSS/JS is owned by the per-locale
skill templates at ``agents/skills/task-generator-{en,zh}/references/
task_plan_template.html`` and is never written by the LLM — the LLM
only emits the JSON dict; ``materialize.py`` merges it into the template.

Hierarchy is capped at TWO levels (top-level "stage" + direct children).
Top-level tasks execute SERIALLY; same-parent sub-tasks MAY run in
parallel when independent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

TASK_HTML_DIR = "tasks"
DOC_VERSION = "2"

# Dotted-path task ids: t-1 or t-1.1 (≤ 2 levels in v4).
TASK_ID_RE = re.compile(r"^t-\d+(?:\.\d+)?$")

# Cap a single task HTML at 2 MiB.
MAX_HTML_BYTES = 2 * 1024 * 1024

# Embedded data script tag id; parsers / writers locate it by this id.
TASK_DOC_SCRIPT_ID = "task-doc"


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
