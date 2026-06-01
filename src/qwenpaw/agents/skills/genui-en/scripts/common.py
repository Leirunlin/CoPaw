"""Shared helper for the genui skill's CLI: push A2UI envelopes onto the live
run stream via the local ``/genui/emit`` endpoint.

The heavy lifting (validation, surface-state mirror, SSE fan-out) lives in
``qwenpaw.agents.genui`` and the ``/genui`` router. This shim just validates
locally for a fast error message and forwards to the server. Best-effort: if no
run key / server is available, it reports that and exits non-zero so the agent
knows the surface was not delivered.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any


def validate_envelopes(envelopes: list[dict[str, Any]]) -> list[str]:
    """Return human-readable validation errors (empty = OK)."""
    from qwenpaw.agents.genui import first_error_message, validate_envelope

    messages: list[str] = []
    for env in envelopes:
        expect_root = "updateComponents" in env
        errors = validate_envelope(env, expect_root=expect_root)
        msg = first_error_message(errors)
        if msg:
            messages.append(msg)
    return messages


def push(envelopes: list[dict[str, Any]]) -> tuple[bool, str]:
    """POST envelopes to ``/genui/emit``. Returns ``(ok, detail)``."""
    run_key = os.environ.get("QWENPAW_SESSION_ID", "")
    if not run_key:
        return False, "no run key (QWENPAW_SESSION_ID) — run inside an agent turn"
    try:
        from qwenpaw.config.utils import read_last_api

        last_api = read_last_api()
        if not last_api:
            return False, "no local API endpoint recorded"
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
        resp = urllib.request.urlopen(req, timeout=10).read()  # noqa: S310
        data = json.loads(resp.decode("utf-8"))
        if not data.get("ok", False):
            return False, f"server validation failed: {data.get('errors')}"
        return True, "pushed"
    except Exception as exc:  # noqa: BLE001
        return False, f"emit failed: {exc}"


def read_envelopes_from_stdin() -> list[dict[str, Any]]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("no input (pipe a JSON array of A2UI envelopes via stdin)")
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array of envelopes (or one envelope)")
    return data
