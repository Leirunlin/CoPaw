"""Patch one task's fields in a task HTML.

Usage:
    python scripts/update.py <name-or-path> <task_id> [--state X] [--title X] \
        [--description X] [--outcome X] [--criteria X] [--test X] [--notes X]

Only fields you pass are changed. Omit a flag to leave the existing value.
Allowed states: todo / in_progress / done / skipped / blocked / failed.

For multi-line notes, prefer ``$'one\\ntwo'`` (shell ANSI-C quoting) or
write the notes to a file first and pass via ``--notes "$(cat file)"``.
"""
from __future__ import annotations

import argparse
import sys

from common import (
    add_workspace_arg,
    die,
    genui_push,
    rel,
    resolve_task_path,
    resolve_workspace,
    task_structural_envelopes,
)
from qwenpaw.agents.task_html import set_task_field


_FIELDS = ("state", "title", "description", "outcome", "criteria", "test", "notes")


def main() -> int:
    p = argparse.ArgumentParser(description="Patch one task in a task HTML.")
    p.add_argument("path", help="Task name or relative path under tasks/.")
    p.add_argument("task_id", help="Dotted-path id (e.g. 't-1' or 't-1.2').")
    p.add_argument("--state")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--outcome")
    p.add_argument("--criteria")
    p.add_argument("--test")
    p.add_argument("--notes")
    add_workspace_arg(p)
    args = p.parse_args()

    ws = resolve_workspace(args)
    resolved = resolve_task_path(ws, args.path)
    if resolved is None or not resolved.exists():
        return die(f"cannot resolve / find '{args.path}'")

    fields: dict[str, str] = {}
    for k in _FIELDS:
        v = getattr(args, k)
        if v is not None and v != "":
            fields[k] = v
    if not fields:
        return die("nothing to update (no fields supplied)")

    try:
        html = resolved.read_text(encoding="utf-8")
        new_html = set_task_field(html, args.task_id, **fields)
    except (OSError, ValueError) as e:
        return die(str(e))

    resolved.write_text(new_html, encoding="utf-8")
    genui_push(task_structural_envelopes(new_html, rel(resolved, ws)))

    # Notes can be multi-line — show "notes updated" instead of repr-ing
    # the whole value into the success summary.
    summary = ", ".join(
        f"{k}={v!r}" for k, v in fields.items() if k != "notes"
    )
    if "notes" in fields:
        summary = (summary + ", " if summary else "") + "notes updated"
    print(f"OK: updated {args.task_id} in {rel(resolved, ws)} — {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
