"""Unit tests for the generative-UI (A2UI) interface.

Covers the catalog-aware validator, the JSON-Pointer data-model ops + surface
mirror, and an end-to-end task round-trip: render a task doc to a surface,
fire an action through the handler registry, and confirm the canonical HTML
mutated and the returned patch is correct.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.agents import genui as g
from qwenpaw.agents.task_html.schema import TASK_DOC_SCRIPT_ID


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validator_accepts_valid_surface():
    env = g.update_components(
        "s",
        [g.column("root", ["t"]), g.text("t", "hi", variant="h2")],
    )
    assert g.validate_envelope(env, expect_root=True) == []


@pytest.mark.unit
def test_validator_requires_exactly_one_message_key():
    bad = {"version": "v0.10", "createSurface": {"surfaceId": "s",
           "catalogId": g.BASIC_CATALOG_ID}, "deleteSurface": {"surfaceId": "s"}}
    errors = g.validate_envelope(bad)
    assert any("exactly one message key" in e["message"] for e in errors)


@pytest.mark.unit
def test_validator_requires_root():
    env = g.update_components("s", [g.text("t", "hi")])
    errors = g.validate_envelope(env, expect_root=True)
    assert any("root" in e["message"] for e in errors)


@pytest.mark.unit
def test_validator_rejects_unvendored_component():
    env = g.update_components("s", [{"id": "root", "component": "Modal"}])
    errors = g.validate_envelope(env, expect_root=True)
    assert any(e["path"].endswith("/component") for e in errors)
    assert "Modal" in g.first_error_message(errors)


@pytest.mark.unit
def test_validator_rejects_bad_pointer():
    env = g.update_data_model("s", "no-leading-slash", {"x": 1})
    errors = g.validate_envelope(env)
    assert any(e["path"] == "/updateDataModel/path" for e in errors)


@pytest.mark.unit
def test_validator_version_must_match():
    env = {"version": "v0.9", "deleteSurface": {"surfaceId": "s"}}
    errors = g.validate_envelope(env)
    assert any(e["path"] == "/version" for e in errors)


# ---------------------------------------------------------------------------
# JSON Pointer + surface mirror
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pointer_upsert_get_delete():
    d: dict = {}
    d = g.pointer_upsert(d, "/a/b", 1)
    assert g.pointer_get(d, "/a/b") == 1
    d = g.pointer_upsert(d, "/a/b", 2)
    assert g.pointer_get(d, "/a/b") == 2
    d = g.pointer_delete(d, "/a/b")
    assert g.pointer_get(d, "/a/b", "gone") == "gone"


@pytest.mark.unit
def test_surface_state_replace_and_snapshot():
    mgr = g.SurfaceStateManager()
    sid = "task:tasks/x.html"
    mgr.apply("run1", g.create_surface(sid))
    mgr.apply("run1", g.update_components(sid, [g.text("root", "v1")]))
    mgr.apply("run1", g.update_components(sid, [g.text("root", "v2")]))  # replace
    mgr.apply("run1", g.update_data_model(sid, "/k", "val"))

    snap = mgr.snapshot("run1", sid)
    kinds = [next(k for k in e if k != "version") for e in snap]
    assert kinds == ["createSurface", "updateComponents", "updateDataModel"]
    # id-replacement kept a single root with the latest text
    comps = snap[1]["updateComponents"]["components"]
    assert len(comps) == 1 and comps[0]["text"] == "v2"
    assert snap[2]["updateDataModel"]["value"] == {"k": "val"}


@pytest.mark.unit
def test_surface_state_unknown_returns_empty_snapshot():
    mgr = g.SurfaceStateManager()
    assert mgr.snapshot("run1", "nope") == []


# ---------------------------------------------------------------------------
# Task round-trip (render -> action -> canonical mutation + patch)
# ---------------------------------------------------------------------------


def _make_task_html(tmp_path: Path) -> tuple[Path, str]:
    doc = {
        "name": "Add login",
        "version": "2",
        "tasks": [
            {"id": "t-1", "parent_id": "", "title": "Backend", "state": "todo"},
            {"id": "t-1.1", "parent_id": "t-1", "title": "DB", "state": "todo"},
        ],
    }
    html = (
        '<html><body><script type="application/json" id="'
        + TASK_DOC_SCRIPT_ID
        + '">'
        + json.dumps(doc)
        + "</script></body></html>"
    )
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    f = tasks_dir / "add-login.html"
    f.write_text(html, encoding="utf-8")
    return f, html


@pytest.mark.unit
def test_task_render_produces_valid_surface(tmp_path):
    from qwenpaw.agents.task_html.render import render_html, surface_id_for

    _, html = _make_task_html(tmp_path)
    sid = surface_id_for("tasks/add-login.html")
    envs = render_html(html, sid)
    kinds = [next(k for k in e if k != "version") for e in envs]
    assert kinds == ["createSurface", "updateComponents", "updateDataModel"]
    for e in envs:
        assert g.validate_envelope(e, expect_root="updateComponents" in e) == []
    # root + per-task components exist
    ids = {c["id"] for c in envs[1]["updateComponents"]["components"]}
    assert "root" in ids and "title_t-1" in ids and "statebtn_t-1.1" in ids


@pytest.mark.unit
def test_task_state_action_cycles_and_returns_patch(tmp_path):
    from qwenpaw.app.routers import genui_handlers
    from qwenpaw.agents.task_html.render import surface_id_for

    f, _ = _make_task_html(tmp_path)
    sid = surface_id_for("tasks/add-login.html")

    class WS:
        workspace_dir = str(tmp_path)

    action = g.ClientAction(
        name="task.state",
        surface_id=sid,
        source_component_id="statebtn_t-1",
        context={"taskId": "t-1"},
    )
    envs = genui_handlers.dispatch(WS(), action)
    assert envs == [g.update_data_model(sid, "/tasks/t-1/state", "in_progress")]
    assert '"state": "in_progress"' in f.read_text(encoding="utf-8")


@pytest.mark.unit
async def test_emit_broadcasts_and_mirrors_surface():
    """emit() validates, folds into the mirror, and broadcasts an
    a2ui_response SSE frame through the tracker fan-out."""
    sid = "confirm:x"
    mgr = g.SurfaceStateManager()

    captured: list[tuple[str, str]] = []

    class StubTracker:
        async def broadcast(self, run_key: str, sse: str) -> bool:
            captured.append((run_key, sse))
            return True

    # Patch the module-level mirror emit() uses so the test is isolated.
    import qwenpaw.agents.genui.emitter as emitter

    monkey = emitter.SURFACE_STATE
    emitter.SURFACE_STATE = mgr
    try:
        envs = [
            g.create_surface(sid),
            g.update_components(sid, [g.text("root", "hi")]),
        ]
        errors = await g.emit(StubTracker(), "run1", envs, expect_root=False)
    finally:
        emitter.SURFACE_STATE = monkey

    assert errors == []
    assert len(captured) == 2
    # Frame is a proper SSE line carrying an a2ui_response envelope.
    run_key, frame = captured[1]
    assert run_key == "run1"
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    payload = json.loads(frame[len("data: "):].strip())
    assert payload["object"] == "a2ui_response"
    assert payload["data"]["a2ui"]["updateComponents"]["surfaceId"] == sid
    # Mirror reflects the surface.
    assert mgr.get_data("run1", sid) is not None


@pytest.mark.unit
def test_task_add_action_returns_structural_update(tmp_path):
    from qwenpaw.app.routers import genui_handlers
    from qwenpaw.agents.task_html.render import surface_id_for

    f, _ = _make_task_html(tmp_path)
    sid = surface_id_for("tasks/add-login.html")

    class WS:
        workspace_dir = str(tmp_path)

    action = g.ClientAction(
        name="task.add",
        surface_id=sid,
        source_component_id="addstage",
        context={"parentId": ""},
    )
    envs = genui_handlers.dispatch(WS(), action)
    kinds = [next(k for k in e if k != "version") for e in envs]
    assert kinds == ["updateComponents", "updateDataModel"]
    # a new top-level task was appended (t-2)
    assert '"id": "t-2"' in f.read_text(encoding="utf-8")
