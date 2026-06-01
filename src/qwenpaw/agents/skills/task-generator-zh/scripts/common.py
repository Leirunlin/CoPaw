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
import os
import sys
from pathlib import Path
from typing import Any

from qwenpaw.agents.task_html import (
    TASK_DOC_SCRIPT_ID,
    TASK_HTML_DIR,
    rel_to_workspace,
    resolve_task_path,
    tasks_dir,
)

__all__ = [
    "TASK_HTML_DIR",
    "add_workspace_arg",
    "die",
    "genui_push",
    "normalize_task_doc",
    "rel",
    "render_shell",
    "resolve_task_path",
    "resolve_workspace",
    "serialize_task",
    "task_full_envelopes",
    "task_structural_envelopes",
    "tasks_dir",
]


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


def render_shell(name: str, task_doc: dict) -> str:
    """Minimal HTML shell carrying the canonical task-doc JSON.

    The interactive board renders natively in-app from this JSON (genui /
    A2UI); the file is a portable canonical store, not a self-contained UI.
    ``</`` is escaped as ``<\\/`` so task text can't close the host script tag.
    """
    escaped_name = html_lib.escape(name, quote=True)
    doc_json = json.dumps(task_doc, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escaped_name}</title>\n</head>\n<body>\n"
        f'<script type="application/json" id="{TASK_DOC_SCRIPT_ID}">\n'
        f"{doc_json}\n</script>\n</body>\n</html>\n"
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


# Generative-UI (A2UI) live push. The board also cold-loads from disk, so the
# push is best-effort: failures (no server / no run key) are swallowed.


def task_full_envelopes(html: str, rel_path: str) -> list:
    """Full surface (createSurface + components + data) from task HTML."""
    from qwenpaw.agents.task_html.render import render_html, surface_id_for

    return render_html(html, surface_id_for(rel_path))


def task_structural_envelopes(html: str, rel_path: str) -> list:
    """Component refresh + data (no createSurface) — for in-place updates."""
    from qwenpaw.agents.task_html import parse_task_doc
    from qwenpaw.agents.task_html.render import structural_update, surface_id_for

    return structural_update(parse_task_doc(html), surface_id_for(rel_path))


def genui_push(envelopes: list) -> None:
    """POST envelopes to the local ``/genui/emit`` endpoint (best-effort)."""
    run_key = os.environ.get("QWENPAW_SESSION_ID", "")
    if not run_key or not envelopes:
        return
    try:
        from qwenpaw.config.utils import read_last_api

        last_api = read_last_api()
        if not last_api:
            return
        host, port = last_api
        import urllib.request

        body = json.dumps(
            {"runKey": run_key, "envelopes": envelopes},
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        agent_id = os.environ.get("QWENPAW_AGENT_ID", "")
        if agent_id:
            headers["X-Agent-Id"] = agent_id
        req = urllib.request.Request(
            f"http://{host}:{port}/api/genui/emit",
            data=body,
            headers=headers,
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()  # noqa: S310
    except Exception:  # noqa: BLE001 — push is best-effort
        pass
