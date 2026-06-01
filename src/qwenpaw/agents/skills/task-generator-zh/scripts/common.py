"""Shared helpers for the task-generator skill's CLI scripts.

The heavy lifting (parse / mutate / validate / path-resolution) lives in
``qwenpaw.agents.task_html`` — the library is shared with the REST API
that backs the in-iframe interactions. Scripts here are thin CLI shims
over that library, invoked by the LLM through ``execute_shell_command``.

Workspace detection:
* ``--workspace`` flag on every script overrides everything.
* Otherwise the script walks up from its file path. At runtime the skill
  is synced to ``<workspace>/skills/<skill>/scripts/<name>.py``, so
  ``Path(__file__).resolve().parents[3]`` is the workspace root.
* Running from the source tree (``src/qwenpaw/agents/skills/.../scripts/``)
  yields ``src/qwenpaw/agents/`` for ``parents[3]`` — that's not a
  workspace, so we refuse and demand ``--workspace`` explicitly.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import sys
from pathlib import Path
from typing import Any

from qwenpaw.agents.task_html import (
    TASK_HTML_DIR,
    rel_to_workspace,
    resolve_task_path,
    tasks_dir,
)

__all__ = [
    "TASK_HTML_DIR",
    "add_workspace_arg",
    "die",
    "normalize_task_doc",
    "rel",
    "render_template",
    "resolve_task_path",
    "resolve_workspace",
    "serialize_task",
    "tasks_dir",
]

# UI template — owned by this skill at references/. The REST API does
# NOT read this; it only mutates the embedded JSON in already-written
# files. Path: <skill_dir>/references/task_plan_template.html, reached
# from this file at <skill_dir>/scripts/common.py.
TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "references" / "task_plan_template.html"
)


def _detect_workspace() -> Path:
    """Walk up from this file's location to find the workspace root.

    At runtime the skill is synced to ``<workspace>/skills/<skill>/scripts/``
    so ``parents[3]`` resolves to ``<workspace>``. When the scripts are run
    from the source tree directly we refuse — there's no usable default;
    the caller must pass ``--workspace`` explicitly.
    """
    here = Path(__file__).resolve()
    candidate = here.parents[3]
    # Refuse the source-tree case: any path containing /qwenpaw/agents/
    # is the dev checkout, not a synced workspace.
    if "qwenpaw" in candidate.parts and "agents" in candidate.parts:
        raise SystemExit(
            "ERROR: cannot infer workspace when running from the source tree; "
            "pass --workspace <path> explicitly.",
        )
    return candidate


def add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: walk up from script location).",
    )


def resolve_workspace(args: argparse.Namespace) -> Path:
    if args.workspace:
        return Path(args.workspace).resolve()
    return _detect_workspace()


def rel(p: Path, ws: Path) -> str:
    return rel_to_workspace(ws, p)


def render_template(name: str, task_doc: dict) -> str:
    """Read the template and substitute the two placeholders.

    JSON lives inside ``<script type="application/json">``; a literal
    ``</`` would close the host script tag early, so we escape it as
    ``<\\/`` — still valid JSON, browsers parse identically.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    escaped_name = html_lib.escape(name, quote=True)
    doc_json = json.dumps(task_doc, ensure_ascii=False, indent=2)
    doc_json = doc_json.replace("</", "<\\/")
    return template.replace("__TASK_NAME__", escaped_name).replace(
        "__TASK_DOC_JSON__",
        doc_json,
    )


def normalize_task_doc(name: str, raw: Any) -> dict:
    """Coerce LLM-supplied task_doc into the canonical shape."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"task_doc string is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("task_doc must be a JSON object.")
    tasks = raw.get("tasks") or []
    if not isinstance(tasks, list):
        raise ValueError("task_doc['tasks'] must be a list.")

    defaults = {
        "parent_id": "",
        "state": "todo",
        "description": "",
        "outcome": "",
        "criteria": "",
        "test": "",
        "notes": "",
    }
    norm: list[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            raise ValueError(f"tasks item is not an object: {t!r}")
        if "id" not in t or "title" not in t:
            raise ValueError(f"task missing required id/title: {t!r}")
        out = {"id": str(t["id"]).strip(), "title": str(t["title"]).strip()}
        for k, d in defaults.items():
            v = t.get(k, d)
            out[k] = "" if v is None else str(v)
        norm.append(out)

    return {
        "name": str(raw.get("name") or name),
        "version": str(raw.get("version") or "2"),
        "tasks": norm,
    }


def serialize_task(task) -> dict:
    return {
        "id": task.id,
        "parent_id": task.parent_id,
        "title": task.title,
        "state": task.state,
        "description": task.description,
        "outcome": task.outcome,
        "criteria": task.criteria,
        "test": task.test,
        "notes": task.notes,
    }


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1
