"""Read a task plan JSON file and print its parsed contents.

Usage:
    python scripts/read.py <name-or-path>

Prints to stdout:

    {
      "path": "tasks/<name>.task.json",
      "name": "...",
      "version": "2",
      "tasks": [ {id, parent_id, title, state, description, outcome,
                  criteria, test, notes}, ... ],
      "next_runnable": {…} | null
    }

Call at the start of every execute-loop iteration so user mid-flight
edits (badge clicks, edits, adds, deletes) propagate.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from common import (
    add_workspace_arg,
    die,
    rel,
    resolve_task_path,
    resolve_workspace,
    serialize_task,
)
from qwenpaw.agents.task_plan import (
    TASK_DIR,
    find_next_runnable,
    parse_task_doc,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Read a task plan; emit parsed JSON.")
    p.add_argument("path", help="Task name or relative path under tasks/.")
    add_workspace_arg(p)
    args = p.parse_args()

    ws = resolve_workspace(args)
    resolved = resolve_task_path(ws, args.path)
    if resolved is None:
        return die(
            f"cannot resolve '{args.path}' under <workspace>/{TASK_DIR}/",
        )
    if not resolved.exists():
        return die(f"file not found: {rel(resolved, ws)}")

    try:
        text = resolved.read_text(encoding="utf-8")
        doc = parse_task_doc(text)
    except (OSError, ValueError) as e:
        return die(str(e))

    nxt = find_next_runnable(doc)
    payload = {
        "path": rel(resolved, ws),
        "name": doc.name,
        "version": doc.version,
        "tasks": [asdict(t) for t in doc.tasks],
        "next_runnable": serialize_task(nxt) if nxt else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
