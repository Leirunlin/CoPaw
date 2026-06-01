"""Create a task plan HTML at ``<workspace>/tasks/<name>.html``.

Usage:
    python scripts/materialize.py <name> <<'EOTASKDOC'
    {"name":"...","version":"2","tasks":[...]}
    EOTASKDOC

Reads ``task_doc`` JSON from stdin only. Writes a minimal HTML shell
holding the JSON in the embedded ``<script id="task-doc">`` block to
``<workspace>/tasks/<name>.html``. The interactive board renders
natively in-app from that JSON (genui / A2UI).

Prints ``[task-html:<rel>]`` on success (the marker the agent watches
for) and exits 0; on failure writes ``ERROR: ...`` to stderr, exit 1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime

from common import (
    add_workspace_arg,
    die,
    genui_push,
    normalize_task_doc,
    rel,
    render_shell,
    resolve_workspace,
    task_full_envelopes,
    tasks_dir,
)
from qwenpaw.agents.task_html import MAX_HTML_BYTES, upsert_entry, validate

# Filename stem allowlist: ASCII word chars + . + - + CJK.
NAME_RE = re.compile(r"^[\w.\-一-鿿]+$")


def main() -> int:
    p = argparse.ArgumentParser(description="Create a task plan HTML.")
    p.add_argument("name", help="Filename stem (no path, no extension).")
    p.add_argument(
        "--summary",
        default="",
        help="Optional one-sentence task summary (stored in manifest, "
             "shown by list.py for cross-session resume).",
    )
    add_workspace_arg(p)
    args = p.parse_args()

    if not NAME_RE.match(args.name):
        return die(
            f"invalid name '{args.name}' "
            "(allowed: letters, digits, '_', '.', '-', CJK)",
        )

    raw_text = sys.stdin.read()
    if not raw_text.strip():
        return die("task_doc empty (pipe JSON via stdin)")

    try:
        task_doc = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return die(f"task_doc is not valid JSON: {e}")

    try:
        doc = normalize_task_doc(args.name, task_doc)
    except ValueError as e:
        return die(str(e))

    rendered = render_shell(doc["name"], doc)

    if len(rendered.encode("utf-8")) > MAX_HTML_BYTES:
        return die(f"rendered HTML exceeds {MAX_HTML_BYTES // 1024} KiB")

    errors = validate(rendered)
    if errors:
        print("ERROR: schema validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    ws = resolve_workspace(args)
    td = tasks_dir(ws)
    target = td / f"{args.name}.html"

    try:
        target.resolve().relative_to(td.resolve())
    except ValueError:
        return die("refusing to write outside tasks/")

    if target.exists():
        return die(
            f"file '{args.name}.html' already exists. "
            f"Use scripts/update.py to modify it, or pick a fresh name "
            f"(e.g. '{args.name}-v2').",
        )

    td.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile in the same dir, then rename. Avoids a
    # truncated file if the process is killed mid-write — which the next
    # read.py would reject.
    fd, tmp = tempfile.mkstemp(
        prefix=f".{args.name}.",
        suffix=".html.tmp",
        dir=str(td),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        os.replace(tmp, target)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return die(f"write failed: {e}")

    # Manifest is a soft extension store. HTML is the source of truth;
    # failure to record metadata shouldn't roll back a successful task
    # creation — warn and move on.
    try:
        upsert_entry(
            ws,
            args.name,
            name=doc["name"],
            summary=args.summary or "",
            created=datetime.now().isoformat(),
        )
    except OSError as e:
        print(f"WARNING: manifest write failed: {e}", file=sys.stderr)

    rel_path = rel(target, ws)
    genui_push(task_full_envelopes(rendered, rel_path))

    print("OK: task HTML created")
    print(f"[task-html:{rel_path}]")
    print(f"file: {rel_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
