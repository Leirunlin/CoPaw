# -*- coding: utf-8 -*-
"""JSON-canonical task plan system rendered through A2UI.

Backs the ``/task-generator`` built-in skill. A task file is a plain JSON
domain document; the board is a generated A2UI surface projected from that
state. This package owns the schema, parser, mutations, validators, and
path-resolution policy shared between the skill CLI scripts and the GenUI
action handler.
"""

from .manifest import (
    MANIFEST_NAME,
    manifest_path,
    read_manifest,
    remove_entry,
    upsert_entry,
)
from .parse import dump_task_doc, find_next_runnable, parse_task_doc
from .paths import rel_to_workspace, resolve_task_path, tasks_dir
from .schema import (
    DOC_VERSION,
    MAX_TASK_BYTES,
    TASK_DIR,
    TASK_FILE_SUFFIX,
    TASK_ID_RE,
    Task,
    TaskDoc,
    TaskState,
    VALID_STATES,
)
from .update import (
    add_task,
    delete_task,
    set_task_field,
    validate,
)

__all__ = [
    "DOC_VERSION",
    "MANIFEST_NAME",
    "MAX_TASK_BYTES",
    "TASK_DIR",
    "TASK_FILE_SUFFIX",
    "TASK_ID_RE",
    "Task",
    "TaskDoc",
    "TaskState",
    "VALID_STATES",
    "add_task",
    "delete_task",
    "dump_task_doc",
    "find_next_runnable",
    "manifest_path",
    "parse_task_doc",
    "read_manifest",
    "rel_to_workspace",
    "remove_entry",
    "resolve_task_path",
    "set_task_field",
    "tasks_dir",
    "upsert_entry",
    "validate",
]
