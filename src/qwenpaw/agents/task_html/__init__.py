"""HTML-as-canonical-state task system.

Backs the ``/task-generator`` built-in skill. The HTML template lives at
``agents/skills/task-generator-{en,zh}/references/task_plan_template.html``
(one copy per locale, owned by the skill); this package owns the schema,
parser, mutations, validators, and path-resolution policy shared between
the skill CLI scripts and the REST router.
"""
from .manifest import (
    MANIFEST_NAME,
    manifest_path,
    read_manifest,
    remove_entry,
    upsert_entry,
)
from .parse import find_next_runnable, parse_task_doc
from .paths import rel_to_workspace, resolve_task_path, tasks_dir
from .schema import (
    DOC_VERSION,
    MAX_HTML_BYTES,
    TASK_DOC_SCRIPT_ID,
    TASK_HTML_DIR,
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
    set_task_state,
    set_task_title,
    validate,
)

__all__ = [
    "DOC_VERSION",
    "MANIFEST_NAME",
    "MAX_HTML_BYTES",
    "TASK_DOC_SCRIPT_ID",
    "TASK_HTML_DIR",
    "TASK_ID_RE",
    "Task",
    "TaskDoc",
    "TaskState",
    "VALID_STATES",
    "add_task",
    "delete_task",
    "find_next_runnable",
    "manifest_path",
    "parse_task_doc",
    "read_manifest",
    "rel_to_workspace",
    "remove_entry",
    "resolve_task_path",
    "set_task_field",
    "set_task_state",
    "set_task_title",
    "tasks_dir",
    "upsert_entry",
    "validate",
]
