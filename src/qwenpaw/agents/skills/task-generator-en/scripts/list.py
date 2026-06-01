"""List task HTML files under ``<workspace>/tasks/`` newest-first.

Output: pure JSON.

    {
      "files": [
        {"path": "tasks/<stem>.html",
         "name": "<task_doc.name from manifest, or stem fallback>",
         "summary": "<from manifest, or empty>",
         "created": "<ISO, from manifest, or st_ctime fallback>",
         "modified": "<ISO, from st_mtime>"},
        ...
      ]
    }

Reads the manifest (``tasks/manifest.json``) for ``name`` / ``summary`` /
``created``; if missing or corrupt, those fall back to filesystem stat
or stem. Never parses the embedded HTML — list.py is metadata-only.

Use this as the session-resume primitive: one call gives the agent
all task identifiers, summaries, and timestamps. To load per-task
state (next_runnable, progress counts) call ``read.py <stem>`` after
the user picks which task to resume.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from common import add_workspace_arg, rel, resolve_workspace, tasks_dir
from qwenpaw.agents.task_html import MANIFEST_NAME, read_manifest


def main() -> int:
    p = argparse.ArgumentParser(
        description="List task HTML files newest-first; emit JSON metadata.",
    )
    add_workspace_arg(p)
    args = p.parse_args()

    ws = resolve_workspace(args)
    td = tasks_dir(ws)

    if not td.exists():
        print(json.dumps({"files": []}, ensure_ascii=False))
        return 0

    manifest = read_manifest(ws)

    files = sorted(
        (
            f
            for f in td.glob("*.html")
            if f.is_file() and f.name != MANIFEST_NAME
        ),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    entries = []
    for f in files:
        st = f.stat()
        meta = manifest.get(f.stem) or {}
        entries.append(
            {
                "path": rel(f, ws),
                "name": meta.get("name") or f.stem,
                "summary": meta.get("summary") or "",
                "created": (
                    meta.get("created")
                    or datetime.fromtimestamp(st.st_ctime).isoformat()
                ),
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
            },
        )

    print(json.dumps({"files": entries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
