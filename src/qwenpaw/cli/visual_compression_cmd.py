# -*- coding: utf-8 -*-
"""Paired OFF/ON evaluation for native visual context compression."""

# TODO: STALE: Evaluation-only CLI; remove with benchmark surfaces before
# production release.
# Its intentionally broad fixture/orchestration functions are kept readable
# as linear benchmark protocols rather than split into production abstractions.
# pylint: disable=R0911,R0912,R0915,R1735,W0640

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click


@dataclass(frozen=True)
class EvalTask:
    id: str
    category: str
    instruction: str
    expected: str
    fixture_kind: str
    seed_context: list[dict[str, Any]] | None = None
    seed_context_source: str | None = None
    seed_context_sha256: str | None = None
    seed_context_format: str | None = None
    verifier: str = "exact_response"
    difficulty: str = "short"
    artifact_path: str | None = None
    required_strings: tuple[str, ...] = ()
    required_source_citations: tuple[str, ...] = ()
    required_evidence_groups: tuple[dict[str, Any], ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    required_sections: tuple[str, ...] = ()
    min_artifact_chars: int = 0
    ground_truth: bool = True
    pytest_target: str = "test_module.py"
    fixture_spec: dict[str, Any] | None = None
    max_iters: int | None = None
    required_tools: tuple[str, ...] = ()
    scripted_turns: tuple[str, ...] = ()
    context_mode: str = "seeded"
    answer_probes: tuple[str, ...] = ()
    max_tool_calls: int | None = None
    tool_policy: str = "read_only"
    expected_artifact_json: dict[str, Any] | None = None
    phase_ids: tuple[str, ...] = ()
    phase_grades: tuple[dict[str, Any], ...] = ()
    max_input_file_bytes: int = 0
    tool_result_max_bytes: int = 0
    benchmark_visual_profile: str = "task_default"
    benchmark_max_images_per_request: int = 0


@dataclass(frozen=True)
class CostConfig:
    """Normalized weights and optional provider prices per million tokens."""

    input_weight: float = 1.0
    output_weight: float = 4.0
    cache_read_weight: float = 0.1
    cache_creation_weight: float = 1.25
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    cache_read_price_per_million: float | None = None
    cache_creation_price_per_million: float | None = None


def _adjusted_token_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    *,
    input_rate: float,
    output_rate: float,
    cache_read_rate: float,
    cache_creation_rate: float,
) -> float:
    """Cost without double-counting cache tokens included in input usage."""
    return max(
        0.0,
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read_tokens * (cache_read_rate - input_rate)
        + cache_creation_tokens * (cache_creation_rate - input_rate),
    )


def _cost_metrics(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    config: CostConfig,
) -> dict[str, Any]:
    # Headline comparison deliberately ignores cache pricing. Cache usage is
    # still recorded and a diagnostic cache-adjusted value is emitted, but
    # experiment acceptance must not depend on provider-specific cache policy.
    weighted = (
        input_tokens * config.input_weight
        + output_tokens * config.output_weight
    )
    cache_adjusted = _adjusted_token_cost(
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_creation_tokens,
        input_rate=config.input_weight,
        output_rate=config.output_weight,
        cache_read_rate=config.cache_read_weight,
        cache_creation_rate=config.cache_creation_weight,
    )
    estimated_usd = None
    if (
        config.input_price_per_million is not None
        and config.output_price_per_million is not None
    ):
        estimated_usd = (
            _adjusted_token_cost(
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_creation_tokens,
                input_rate=config.input_price_per_million,
                output_rate=config.output_price_per_million,
                cache_read_rate=(
                    config.cache_read_price_per_million
                    if config.cache_read_price_per_million is not None
                    else config.input_price_per_million
                ),
                cache_creation_rate=(
                    config.cache_creation_price_per_million
                    if config.cache_creation_price_per_million is not None
                    else config.input_price_per_million
                ),
            )
            / 1_000_000
        )
    return {
        "weighted_token_units": round(weighted, 4),
        "cache_adjusted_weighted_token_units": round(cache_adjusted, 4),
        "estimated_cost_usd": (
            round(estimated_usd, 8) if estimated_usd is not None else None
        ),
    }


def _text_msg(role: str, text: str, index: int) -> dict[str, Any]:
    return {
        "name": role,
        "role": role,
        "id": f"seed-{index}",
        "content": [{"type": "text", "text": text}],
    }


def build_agentic_suite() -> list[EvalTask]:
    """Build 20 deterministic tasks with novel per-task values."""
    tasks: list[EvalTask] = []
    for idx in range(1, 6):
        code = f"INCIDENT-{idx:02d}-ZX{idx * 7919}"
        tasks.append(
            EvalTask(
                id=f"log-{idx:02d}",
                category="log_diagnosis",
                fixture_kind="log",
                expected=code,
                instruction=(
                    "Use read_file to inspect events.log. Find the incident "
                    "code on the only line where level=FATAL "
                    "and subsystem=ledger. Reply exactly `FINAL: <code>`."
                ),
            ),
        )
    for idx in range(1, 6):
        expected = str((idx * 137 + 11) + (idx * 211 + 17))
        tasks.append(
            EvalTask(
                id=f"json-{idx:02d}",
                category="structured_data",
                fixture_kind="json",
                expected=expected,
                instruction=(
                    "Use read_file to inspect catalog.json. Sum the `amount` "
                    "values of the two records whose `selected` field is "
                    "true. Reply exactly `FINAL: <integer>`."
                ),
            ),
        )
    for idx in range(1, 6):
        first = f"STATE_ALPHA_{idx}_A{idx * 101}"
        last = f"STATE_OMEGA_{idx}_Z{idx * 313}"
        seed: list[dict[str, Any]] = []
        updates = [first, f"STATE_MID_{idx}_M{idx * 197}", last]
        update_at = {0: updates[0], 4: updates[1], 12: updates[2]}
        for turn in range(14):
            role = "user" if turn % 2 == 0 else "assistant"
            filler = (
                f"background-{idx}-{turn} lorem ipsum data " * 45
            ).strip()
            marker = (
                f"\nAuthoritative state update: ACTIVE_STATE={update_at[turn]}"
                if turn in update_at
                else ""
            )
            seed.append(_text_msg(role, filler + marker, turn))
        tasks.append(
            EvalTask(
                id=f"history-{idx:02d}",
                category="history_state",
                fixture_kind="none",
                expected=f"FIRST={first}; LAST={last}; COUNT=3",
                seed_context=seed,
                instruction=(
                    "From the earlier conversation, report the first and last "
                    "ACTIVE_STATE values and the number of authoritative "
                    "state updates. Reply exactly `FINAL: FIRST=<value>; "
                    "LAST=<value>; "
                    "COUNT=<integer>`."
                ),
            ),
        )
    for idx in range(1, 6):
        tasks.append(
            EvalTask(
                id=f"code-{idx:02d}",
                category="code_edit",
                fixture_kind="code",
                expected="fixed",
                verifier="pytest",
                instruction=(
                    "Use read_file and edit_file to fix select_target in "
                    "module.py so it returns the record whose priority "
                    f"equals {idx * 17}; keep its public signature. Reply "
                    "exactly `FINAL: fixed` when done."
                ),
            ),
        )
    return tasks


_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCHMARK_TASK_FILE = (
    _REPO_ROOT / "benchmarks" / "visual_compression" / "task.json"
)
_VISUAL_COMPONENT_ROOT = (
    _REPO_ROOT
    / "src"
    / "qwenpaw"
    / "agents"
    / "context"
    / "visual_compression"
)
_VISUAL_RUNTIME_FILES = tuple(sorted(_VISUAL_COMPONENT_ROOT.rglob("*.py")))

_VISUAL_IMPLEMENTATION_FILES = (
    *_VISUAL_RUNTIME_FILES,
    _REPO_ROOT / "src" / "qwenpaw" / "agents" / "middlewares.py",
    _REPO_ROOT / "src" / "qwenpaw" / "agents" / "model_factory.py",
    _REPO_ROOT / "src" / "qwenpaw" / "agents" / "tools" / "file_io.py",
    _REPO_ROOT / "src" / "qwenpaw" / "cli" / "task_cmd.py",
    _REPO_ROOT / "src" / "qwenpaw" / "config" / "config.py",
    _REPO_ROOT / "src" / "qwenpaw" / "cli" / "visual_compression_cmd.py",
    _REPO_ROOT / "src" / "qwenpaw" / "runtime" / "builder.py",
    _REPO_ROOT / "src" / "qwenpaw" / "token_usage" / "model_wrapper.py",
    _REPO_ROOT / "scripts" / "visual_compression_bench.sh",
    _VISUAL_COMPONENT_ROOT / "assets" / "JetBrainsMono-Regular.ttf",
    _VISUAL_COMPONENT_ROOT / "assets" / "Spleen-5x8.otb",
    _VISUAL_COMPONENT_ROOT / "assets" / "Unifont-16.0.04.otf",
    _VISUAL_COMPONENT_ROOT / "assets" / "atlas-gray.ts",
    _VISUAL_COMPONENT_ROOT / "assets" / "atlas-gray-jbmono10.ts",
)


def _implementation_fingerprint() -> dict[str, Any]:
    files = {
        str(path.relative_to(_REPO_ROOT)): hashlib.sha256(
            path.read_bytes(),
        ).hexdigest()
        for path in _VISUAL_IMPLEMENTATION_FILES
    }
    combined = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode(
            "utf-8",
        ),
    ).hexdigest()
    return {"sha256": combined, "files": files}


MAX_BENCHMARK_INPUT_FILE_BYTES = 32 * 1024
LONG_CONTEXT_MIN_TURNS = 24
LONG_CONTEXT_MIN_TOTAL_CHARS = 8_000
LONG_CONTEXT_MAX_TURN_CHARS = 1_500
BENCHMARK_CONTEXT_MIN_TURNS = 20

_IMPORTED_HISTORY_VISUAL_PROFILE_NAME = "history_only_v1"
_IMPORTED_HISTORY_VISUAL_PROFILE: dict[str, Any] = {
    "compress_system": False,
    "compress_tools": False,
    "compress_tool_results": False,
    "compress_history": True,
    "keep_recent_messages": 6,
    "history_collapse_grid_messages": 50,
    "history_chunk_messages": 10,
    "max_images_per_request": 64,
    "max_visual_cost_ratio": 0.90,
    "image_cost_safety_margin": 1.10,
    "emit_recoverable": True,
}

_JOINT_VISUAL_PROFILE_NAME = "joint_v1"
_JOINT_VISUAL_PROFILE: dict[str, Any] = {
    "compress_system": True,
    "compress_tools": True,
    "compress_tool_results": True,
    "compress_history": True,
    "emit_recoverable": True,
}

_FIXED_GRID_VISUAL_PROFILE_NAME = "fixed_grid_v1"
_FIXED_GRID_VISUAL_PROFILE: dict[str, Any] = {
    "compress_system": False,
    "compress_tools": False,
    "compress_tool_results": False,
    "compress_history": True,
    "keep_recent_messages": 6,
    "history_collapse_grid_messages": 50,
    "history_chunk_messages": 10,
    "max_images_per_request": 64,
    "render_variant": "v0_pxpipe",
    "image_cost_safety_margin": 1.10,
    "max_visual_cost_ratio": 0.90,
    "emit_recoverable": True,
}


def _task_visual_profile(task: EvalTask) -> dict[str, Any]:
    """Return benchmark-only region settings that must not drift by agent."""
    requested = task.benchmark_visual_profile
    if requested == _JOINT_VISUAL_PROFILE_NAME:
        profile: dict[str, Any] = {
            "name": _JOINT_VISUAL_PROFILE_NAME,
            **_JOINT_VISUAL_PROFILE,
        }
    elif requested == _FIXED_GRID_VISUAL_PROFILE_NAME:
        profile = {
            "name": _FIXED_GRID_VISUAL_PROFILE_NAME,
            **_FIXED_GRID_VISUAL_PROFILE,
        }
    elif requested != "task_default":
        raise ValueError(f"unknown benchmark visual profile: {requested}")
    elif task.context_mode == "imported_history":
        profile = {
            "name": _IMPORTED_HISTORY_VISUAL_PROFILE_NAME,
            **_IMPORTED_HISTORY_VISUAL_PROFILE,
        }
    else:
        profile = {"name": "agent_config_plus_cli_overrides"}
    if task.benchmark_max_images_per_request > 0:
        profile[
            "max_images_per_request"
        ] = task.benchmark_max_images_per_request
    return profile


def _apply_task_visual_profile(task: EvalTask, config: Any) -> None:
    """Apply the task's pinned visual region profile to a config object."""
    for key, value in _task_visual_profile(task).items():
        if key != "name":
            setattr(config, key, value)


def _seed_context_from_recipe(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    turns = int(recipe.get("turns", 0) or 0)
    filler_repeat = int(recipe.get("filler_repeat", 40) or 40)
    updates = {
        int(key): str(value)
        for key, value in (recipe.get("updates", {}) or {}).items()
    }
    events = {
        int(key): str(value)
        for key, value in (recipe.get("events", {}) or {}).items()
    }
    owner_turn = int(recipe.get("owner_turn", -1) or -1)
    owner = str(recipe.get("owner", ""))
    topic = str(recipe.get("topic", "project delivery"))
    discussion = (
        "The team compares current evidence, constraints, alternatives, test "
        "coverage, operational risk, ownership, and the next validation step. "
    )
    seed: list[dict[str, Any]] = []
    for turn in range(turns):
        role = "user" if turn % 2 == 0 else "assistant"
        marker = ""
        if turn in updates:
            marker = f"\nRecorded state change: PROJECT_STATE={updates[turn]}"
        if turn in events:
            marker += f"\nConversation event: {events[turn]}"
        if turn == owner_turn and owner:
            marker += f" OWNER={owner}"
        seed.append(
            _text_msg(
                role,
                (
                    f"Meeting note {turn} about {topic}. "
                    + discussion * filler_repeat
                )
                + marker,
                turn,
            ),
        )
    return seed


def _convert_openai_seed_context(
    turns: list[dict[str, Any]],
    *,
    tool_name_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert an imported OpenAI transcript into stable AgentScope messages.

    Imported benchmark histories are inert evidence, not tool executions. We
    still preserve their call/result protocol so provider formatters and
    PawFocus history chunking see the same boundaries as a live session.
    """
    mapping = {
        str(key): str(value) for key, value in (tool_name_map or {}).items()
    }
    call_names: dict[str, str] = {}
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError(f"seed turn {turn_index} is not an object")
        for call in turn.get("tool_calls", []) or []:
            if not isinstance(call, dict) or not isinstance(
                call.get("function"),
                dict,
            ):
                raise ValueError(
                    f"seed turn {turn_index} has an invalid tool call",
                )
            call_id = str(call.get("id", ""))
            raw_name = str(call["function"].get("name", ""))
            if not call_id or not raw_name:
                raise ValueError(
                    f"seed turn {turn_index} has a tool call without id/name",
                )
            if call_id in call_names:
                raise ValueError(f"duplicate seed tool call id: {call_id}")
            call_names[call_id] = mapping.get(raw_name, raw_name)

    converted: list[dict[str, Any]] = []
    open_calls: set[str] = set()
    for turn_index, turn in enumerate(turns):
        role = str(turn.get("role", ""))
        metadata = turn.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            raise ValueError(
                f"seed turn {turn_index} metadata is not an object",
            )
        blocks: list[dict[str, Any]] = []
        if role == "tool":
            call_id = str(turn.get("tool_call_id", ""))
            if call_id not in open_calls:
                raise ValueError(
                    f"orphan or out-of-order seed tool result: {call_id}",
                )
            output = turn.get("content", "")
            if not isinstance(output, str):
                raise ValueError(
                    f"seed tool result {call_id} content is not text",
                )
            blocks.append(
                {
                    "type": "tool_result",
                    "id": call_id,
                    "name": call_names[call_id],
                    "output": output,
                    "state": "success",
                },
            )
            open_calls.remove(call_id)
            msg_role = "assistant"
            msg_name = "tool"
        elif role in {"user", "assistant", "system"}:
            content = turn.get("content", "")
            if not isinstance(content, str):
                raise ValueError(
                    f"seed turn {turn_index} content is not text",
                )
            if content:
                blocks.append({"type": "text", "text": content})
            for call in turn.get("tool_calls", []) or []:
                call_id = str(call["id"])
                function = call["function"]
                arguments = function.get("arguments", "{}")
                if not isinstance(arguments, str):
                    arguments = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                blocks.append(
                    {
                        "type": "tool_call",
                        "id": call_id,
                        "name": call_names[call_id],
                        "input": arguments,
                        "state": "finished",
                    },
                )
                open_calls.add(call_id)
            msg_role = role
            msg_name = role
        else:
            raise ValueError(
                f"seed turn {turn_index} has unsupported role: {role!r}",
            )
        if not blocks:
            raise ValueError(f"seed turn {turn_index} has no content")
        converted.append(
            {
                "name": msg_name,
                "role": msg_role,
                "id": f"imported-seed-{turn_index:05d}",
                "metadata": metadata,
                "content": blocks,
            },
        )
    if open_calls:
        raise ValueError(
            "seed history ends with unresolved tool calls: "
            + ", ".join(sorted(open_calls)[:5]),
        )
    return converted


def _seed_context_from_file(
    task_file: Path,
    raw: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Load, authenticate, and normalize an external seed transcript."""
    relative = Path(str(raw["seed_context_file"]))
    source = (task_file.parent / relative).resolve()
    if relative.is_absolute() or not source.is_relative_to(task_file.parent):
        raise click.ClickException(
            f"seed context source escapes task directory: {relative}",
        )
    if not source.is_file():
        raise click.ClickException(f"seed context source not found: {source}")
    actual_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    expected_sha256 = str(raw.get("seed_context_sha256", ""))
    if not expected_sha256:
        raise click.ClickException(
            f"seed_context_sha256 is required for {relative}",
        )
    if actual_sha256 != expected_sha256:
        raise click.ClickException(
            f"seed context hash mismatch for {relative}: "
            f"expected {expected_sha256}, got {actual_sha256}",
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(
            f"invalid seed context source {source}: {exc}",
        ) from exc
    turns = payload.get("turns") if isinstance(payload, dict) else payload
    if not isinstance(turns, list):
        raise click.ClickException(
            f"seed context source must contain a turns list: {source}",
        )
    expected_id = raw.get("seed_context_id")
    if expected_id is not None and (
        not isinstance(payload, dict)
        or str(payload.get("tc_id", "")) != str(expected_id)
    ):
        raise click.ClickException(
            f"seed context id mismatch for {relative}: expected {expected_id}",
        )
    context_format = str(raw.get("seed_context_format", "agentscope"))
    try:
        if context_format == "openai_chat":
            turns = _convert_openai_seed_context(
                turns,
                tool_name_map=dict(
                    raw.get("seed_tool_name_map", {}) or {},
                ),
            )
        elif context_format != "agentscope":
            raise ValueError(
                f"unsupported seed_context_format: {context_format}",
            )
    except (TypeError, ValueError) as exc:
        raise click.ClickException(
            f"invalid seed context source {source}: {exc}",
        ) from exc
    return turns, relative.as_posix(), actual_sha256, context_format


def load_benchmark_tasks(
    task_file: Path | str | None = None,
) -> list[EvalTask]:
    """Load the maintainable benchmark contract from task.json."""
    path = (
        Path(task_file or DEFAULT_BENCHMARK_TASK_FILE).expanduser().resolve()
    )
    if not path.is_file():
        raise click.ClickException(f"benchmark task file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "qwenpaw.visual-bench.v1":
        raise click.ClickException(f"unsupported task schema in {path}")
    tasks: list[EvalTask] = []
    for raw in payload.get("tasks", []):
        fixture_spec = dict(raw.get("fixture", {}) or {})
        recipe = raw.get("seed_context_recipe")
        seed_context_source = None
        seed_context_sha256 = None
        seed_context_format = None
        seed_sources = sum(
            (
                isinstance(recipe, dict),
                raw.get("seed_context") is not None,
                raw.get("seed_context_file") is not None,
            ),
        )
        if seed_sources > 1:
            raise click.ClickException(
                f"task {raw.get('id')} declares multiple seed context sources",
            )
        if raw.get("seed_context_file") is not None:
            (
                seed_context,
                seed_context_source,
                seed_context_sha256,
                seed_context_format,
            ) = _seed_context_from_file(path, raw)
        elif isinstance(recipe, dict):
            seed_context = _seed_context_from_recipe(recipe)
        else:
            seed_context = raw.get("seed_context")
        tasks.append(
            EvalTask(
                id=str(raw["id"]),
                category=str(raw["category"]),
                difficulty=str(raw["difficulty"]),
                instruction=str(raw["instruction"]),
                expected=str(raw["expected"]),
                fixture_kind=str(
                    raw.get("fixture_kind")
                    or fixture_spec.get("kind")
                    or "none",
                ),
                seed_context=seed_context,
                seed_context_source=seed_context_source,
                seed_context_sha256=seed_context_sha256,
                seed_context_format=seed_context_format,
                verifier=str(raw.get("verifier", "exact_response")),
                artifact_path=raw.get("artifact_path"),
                required_strings=tuple(raw.get("required_strings", [])),
                required_source_citations=tuple(
                    raw.get("required_source_citations", []),
                ),
                required_evidence_groups=tuple(
                    dict(group)
                    for group in raw.get("required_evidence_groups", [])
                ),
                forbidden_patterns=tuple(raw.get("forbidden_patterns", [])),
                required_sections=tuple(raw.get("required_sections", [])),
                min_artifact_chars=int(raw.get("min_artifact_chars", 0) or 0),
                ground_truth=bool(raw.get("ground_truth", True)),
                pytest_target=str(raw.get("pytest_target", "test_module.py")),
                fixture_spec=fixture_spec,
                max_iters=(
                    int(raw["max_iters"])
                    if raw.get("max_iters") is not None
                    else None
                ),
                required_tools=tuple(raw.get("required_tools", [])),
                scripted_turns=tuple(
                    str(item) for item in raw.get("scripted_turns", [])
                ),
                context_mode=str(raw.get("context_mode", "seeded")),
                answer_probes=tuple(
                    str(item) for item in raw.get("answer_probes", [])
                ),
                max_tool_calls=(
                    int(raw["max_tool_calls"])
                    if raw.get("max_tool_calls") is not None
                    else None
                ),
                tool_policy=str(raw.get("tool_policy", "read_only")),
                expected_artifact_json=(
                    dict(raw["expected_artifact_json"])
                    if isinstance(raw.get("expected_artifact_json"), dict)
                    else None
                ),
                phase_ids=tuple(
                    str(item) for item in raw.get("phase_ids", [])
                ),
                phase_grades=tuple(
                    dict(item) for item in raw.get("phase_grades", [])
                ),
                max_input_file_bytes=int(
                    raw.get("max_input_file_bytes", 0) or 0,
                ),
                tool_result_max_bytes=int(
                    raw.get("tool_result_max_bytes", 0) or 0,
                ),
            ),
        )
    if not tasks:
        raise click.ClickException(f"no tasks found in {path}")
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise click.ClickException(f"duplicate task id in {path}")
    return tasks


def build_benchmark_suite(
    task_file: Path | str | None = None,
) -> list[EvalTask]:
    """Public benchmark loader kept stable for tests and integrations."""
    return load_benchmark_tasks(task_file)


def _incident_expected_value(expected: str) -> str:
    """Extract INCIDENT value from either a bare or composite expectation."""
    for part in expected.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == "INCIDENT":
            return value.strip()
    return expected


def _write_fixture(workspace: Path, task: EvalTask) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    fixture_spec = task.fixture_spec or {}
    artifact_sources = fixture_spec.get("artifact_sources") or []
    repo_root = Path(__file__).resolve().parents[3]
    for entry in artifact_sources:
        source = (repo_root / str(entry["source"])).resolve()
        target = (
            workspace / str(entry.get("target") or source.name)
        ).resolve()
        if not source.is_relative_to(repo_root):
            raise ValueError(f"artifact source escapes repository: {source}")
        if not target.is_relative_to(workspace.resolve()):
            raise ValueError(
                f"artifact target escapes task workspace: {target}",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise FileNotFoundError(
                f"artifact source does not exist: {source}",
            )
    custom_files = fixture_spec.get("files")
    if isinstance(custom_files, dict):
        _write_text_corpus(
            workspace,
            {str(path): str(text) for path, text in custom_files.items()},
            filler_lines=int(fixture_spec.get("filler_lines", 0) or 0),
        )
        return
    if task.fixture_kind == "log":
        idx = 1
        if task.id.startswith("log-"):
            idx = int(task.id.split("-")[1])
        lines = [
            f"ts=2026-07-16T00:{n % 60:02d}:00 level=INFO "
            f"subsystem=worker shard={n % 31} message=healthy"
            for n in range(220)
        ]
        # Keep the answer inside read_file's leading excerpt while retaining
        # a large result that exercises request-time compression.
        lines[120 + idx] = (
            "ts=2026-07-16T11:11:11 level=FATAL subsystem=ledger "
            f"incident={_incident_expected_value(task.expected)} "
            "message=checksum_mismatch"
        )
        (workspace / "events.log").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )
    elif task.fixture_kind == "json":
        idx = 1
        if task.id.startswith("json-"):
            idx = int(task.id.split("-")[1])
        records = [
            {
                "id": f"row-{n:05d}",
                "amount": (n * 37) % 1000,
                "selected": False,
                "description": "deterministic catalog filler",
            }
            for n in range(4000)
        ]
        records[100 + idx].update(amount=idx * 137 + 11, selected=True)
        records[170 + idx].update(amount=idx * 211 + 17, selected=True)
        (workspace / "catalog.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif task.fixture_kind == "code":
        idx = 1
        if task.id.startswith("code-"):
            idx = int(task.id.split("-")[1])
        target = idx * 17
        filler = "\n".join(
            f"    {{'name': 'record-{n:04d}', 'priority': {n}}},"
            for n in range(1, 81)
        )
        (workspace / "module.py").write_text(
            "RECORDS = [\n"
            + filler
            + "\n]\n\n"
            + "def select_target(records=RECORDS):\n"
            + "    # BUG: the target is not necessarily the first record.\n"
            + "    return records[0]\n",
            encoding="utf-8",
        )
        (workspace / "test_module.py").write_text(
            "from module import select_target\n\n"
            "def test_target():\n"
            f"    assert select_target()['priority'] == {target}\n",
            encoding="utf-8",
        )
    elif task.fixture_kind == "architecture_report":
        files = {
            "docs/overview.md": (
                "Architecture evidence: SERVICE_COUNT=4. The system has api, "
                "worker, ledger, and notifier services. PUBLIC_PORT=8443.\n"
            ),
            "config/runtime.env": "QUEUE=ledger-events\nRETRIES=7\n",
            "docs/risks.md": (
                "RISK-ID=ARCH-17: the ledger consumer has a single-region "
                "checkpoint dependency. Owner: reliability.\n"
            ),
            "services/api.md": (
                "API accepts HTTPS and dispatches ledger work.\n"
            ),
            "services/worker.md": "Worker consumes normalized jobs.\n",
            "services/ledger.md": "Ledger commits idempotent entries.\n",
            "services/notifier.md": "Notifier emits settlement updates.\n",
        }
        _write_text_corpus(workspace, files, filler_lines=80)
    elif task.fixture_kind == "postmortem":
        files = {
            "incident/summary.md": (
                "INCIDENT=PAY-4821\nREGION=ap-southeast-1\n"
                "Impact: delayed payment authorization.\n"
            ),
            "incident/timeline.log": (
                "10:01 alert fired\n10:07 cache inconsistency isolated\n"
                "10:19 routing cache flushed\n10:31 service recovered\n"
            ),
            "incident/root-cause.md": (
                "ROOT_CAUSE=stale-routing-cache\nA version skew prevented "
                "normal invalidation after the routing rollout.\n"
            ),
            "incident/actions.md": (
                "ACTION=ACT-903\nAdd version-aware cache invalidation and "
                "a cross-region canary before routing changes.\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=80)
    elif task.fixture_kind == "reconciliation":
        files = {
            "finance/source.csv": (
                "account,amount\nA,7200\nB,6150\nC,5100\n"
                "SOURCE_TOTAL=18450\n"
            ),
            "finance/ledger.csv": (
                "account,amount\nA,7200\nB,5825\nC,5100\n"
                "LEDGER_TOTAL=18125\n"
            ),
            "finance/exceptions.md": (
                "EXCEPTION_ID=REC-77\nAccount B missed a 325 unit posting.\n"
                "Expected reconciliation token: DELTA=325.\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=100)
    elif task.fixture_kind == "code_multi":
        (workspace / "discounts.py").write_text(
            "TIERS = {'standard': 0.05, 'gold': 0.15}\n\n"
            "def tier_discount(name):\n"
            "    return TIERS.get(name, 0.0)\n",
            encoding="utf-8",
        )
        (workspace / "pricing.py").write_text(
            "from discounts import tier_discount\n\n"
            "def final_price(amount, tier, rebate):\n"
            "    # BUG: rebate is applied before the tier discount.\n"
            "    return (amount - rebate) * (1 - tier_discount(tier))\n",
            encoding="utf-8",
        )
        (workspace / "test_pricing.py").write_text(
            "from pricing import final_price\n\n"
            "def test_discount_then_rebate():\n"
            "    assert final_price(100, 'gold', 10) == 75\n\n"
            "def test_floor_zero():\n"
            "    assert final_price(10, 'standard', 20) == 0\n",
            encoding="utf-8",
        )
    elif task.fixture_kind == "code_pipeline":
        (workspace / "parser.py").write_text(
            "def parse_record(raw):\n"
            "    return {\n"
            "        'id': raw['id'],\n"
            "        'amount': int(raw['amount']),\n"
            "        # BUG: bool('no') is True.\n"
            "        'active': bool(raw.get('active')),\n"
            "    }\n",
            encoding="utf-8",
        )
        (workspace / "pipeline.py").write_text(
            "from parser import parse_record\n\n"
            "def active_total(rows):\n"
            "    records = [parse_record(row) for row in rows]\n"
            "    # BUG: duplicate ids must keep only the latest revision.\n"
            "    return sum(record['amount'] for record in records "
            "if record['active'])\n",
            encoding="utf-8",
        )
        (workspace / "test_pipeline.py").write_text(
            "from pipeline import active_total\n\n"
            "def test_latest_revision_and_literal_yes():\n"
            "    rows = [\n"
            "        {'id': 'A', 'amount': '10', 'active': 'yes'},\n"
            "        {'id': 'B', 'amount': '99', 'active': 'no'},\n"
            "        {'id': 'A', 'amount': '17', 'active': 'yes'},\n"
            "        {'id': 'C', 'amount': '5', 'active': 'YES'},\n"
            "    ]\n"
            "    assert active_total(rows) == 22\n",
            encoding="utf-8",
        )
    elif task.fixture_kind == "release_readiness":
        files = {
            "release/manifest.md": (
                "RELEASE=2026.07.3\nCandidate contains 18 services and 42 "
                "database migrations.\n"
            ),
            "release/decision.md": (
                "DECISION=NO-GO\nThe release cannot proceed until the "
                "payment rollback rehearsal is complete.\n"
            ),
            "release/blockers.md": (
                "BLOCKER=REL-19\nRollback rehearsal lacks production-like "
                "ledger volume. OWNER=platform-sre.\n"
            ),
            "release/schedule.md": (
                "DEADLINE=2026-07-22\nNext review at 09:00 UTC.\n"
            ),
            "release/tests.md": (
                "Unit 100%; integration 98.7%; rollback pending.\n"
            ),
            "release/operations.md": (
                "Runbooks reviewed; paging rotation staffed.\n"
            ),
        }
        # Keep every result below test-ocr's 3 KiB old-result pruning limit.
        # The task requires correlating all six files, so larger independent
        # results create an artificial read/prune/reread loop in both arms.
        _write_text_corpus(workspace, files, filler_lines=35)
    elif task.fixture_kind == "security_audit":
        files = {
            "security/scope.md": (
                "Audit covers auth, upload, and audit logging.\n"
            ),
            "security/auth.py.txt": (
                "FINDING=SEC-201\nSEVERITY=HIGH\nReset tokens remain valid "
                "after password change because revocation is not checked.\n"
            ),
            "security/upload.py.txt": (
                "FINDING=SEC-305\nSEVERITY=MEDIUM\nArchive extraction does "
                "not cap expanded byte size.\n"
            ),
            "security/controls.md": (
                "CONTROL=CTRL-8\nRequire token-version revocation and bounded "
                "archive extraction in a disposable directory.\n"
            ),
            "security/evidence.log": (
                "No exploit observed in sampled traffic.\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=80)
    elif task.fixture_kind == "crosscheck_matrix":
        endpoints = ["/v1/payments", "/v1/refunds", "/v1/ledger"]
        codes = ["E101", "E203", "E409", "E503"]
        for shard in range(4):
            matrix_rows: list[dict[str, Any]] = []
            serial = 0
            for endpoint_index, endpoint in enumerate(endpoints):
                for code_index, code in enumerate(codes):
                    count = (shard + endpoint_index + code_index) % 3
                    for _ in range(count):
                        serial += 1
                        matrix_rows.append(
                            {
                                "seq": shard * 100 + serial,
                                "endpoint": endpoint,
                                "error_code": code,
                                "status": 500,
                                "trace_id": f"mx-{shard}-{serial:04d}",
                                "source": "matrix-v3",
                            },
                        )
            for filler_index in range(24):
                matrix_rows.append(
                    {
                        "seq": shard * 100 + 80 + filler_index,
                        "endpoint": endpoints[filler_index % len(endpoints)],
                        "error_code": codes[filler_index % len(codes)],
                        "status": 200 if filler_index % 2 == 0 else 429,
                        "trace_id": f"noise-{shard}-{filler_index:04d}",
                        "source": "matrix-v3",
                    },
                )
            path = workspace / "logs" / f"shard-{shard + 1}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True) for row in matrix_rows
                )
                + "\n",
                encoding="utf-8",
            )
    elif task.fixture_kind == "crosscheck_correlation":
        files = {
            "monthly/2026-05.csv": (
                "endpoint,requests,failures\n/v1/payments,10000,80\n"
                "/v1/refunds,8000,96\n/v1/ledger,12000,60\n"
            ),
            "monthly/2026-06.csv": (
                "endpoint,requests,failures\n/v1/payments,10000,100\n"
                "/v1/refunds,8000,320\n/v1/ledger,12000,72\n"
            ),
            "logs/gateway.log": (
                "trace=tr-9f8a7c endpoint=/v1/refunds status=500 "
                "error_code=E503 latency_ms=410\n"
            ),
            "logs/refund.log": (
                "trace=tr-9f8a7c stage=refund-engine error_code=E503 "
                "latency_ms=970 cause=downstream-timeout\n"
            ),
            "logs/ledger.log": (
                "trace=tr-9f8a7c stage=ledger-finalize error_code=E503 "
                "latency_ms=460 result=rollback\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=90)
    elif task.fixture_kind == "crosscheck_spec_decoy":
        (workspace / "SPEC.md").write_text(
            "# Policy rules\n"
            "R1: normalize_email must strip whitespace and lowercase text.\n"
            "R2: round_amount must use decimal ROUND_HALF_UP to two places.\n"
            "R3: record_attempt must append exactly one telemetry event.\n"
            "R4: validate_amount must raise ValueError for negative values.\n"
            "R5: preserve all public function signatures.\n",
            encoding="utf-8",
        )
        (workspace / "policy.py").write_text(
            "from decimal import Decimal\n\n"
            "EVENTS = []\n\n"
            "def normalize_email(value):\n"
            "    return value.strip().lower()\n\n"
            "def round_amount(value):\n"
            "    return round(Decimal(str(value)), 2)\n\n"
            "def record_attempt(value):\n"
            "    EVENTS.append(value)\n\n"
            "def validate_amount(value):\n"
            "    return Decimal(str(value))\n",
            encoding="utf-8",
        )
        (workspace / "test_policy.py").write_text(
            "from policy import normalize_email, record_attempt, EVENTS\n\n"
            "def test_satisfied_decoys():\n"
            "    assert normalize_email(' A@B.COM ') == 'a@b.com'\n"
            "    EVENTS.clear(); record_attempt('x'); "
            "assert EVENTS == ['x']\n",
            encoding="utf-8",
        )
    elif task.fixture_kind == "crosscheck_organic":
        files = {
            "organic/phase1.md": (
                "CODENAME=ORBIT-CEDAR\nScope is settlement recovery.\n"
            ),
            "organic/phase2.md": (
                "RETRY_THRESHOLD=17\nThe value supersedes 12.\n"
            ),
            "organic/phase3.md": (
                "FINAL_OWNER=runtime-sre\nOwner is authoritative.\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=110)
    elif task.fixture_kind == "crosscheck_cache_pressure":
        for name in ("a", "b", "c"):
            (workspace / f"state_{name}.txt").write_text(
                "VALUE=0\n",
                encoding="utf-8",
            )
    elif task.fixture_kind == "open_assessment":
        files = {
            "assessment/product.md": (
                "The product team values release speed and regional "
                "autonomy.\n"
            ),
            "assessment/operations.md": (
                "Operations reports recurring ownership gaps and slow "
                "rollback decisions during cross-region incidents.\n"
            ),
            "assessment/engineering.md": (
                "Engineering has strong unit coverage but inconsistent "
                "integration environments and duplicated service templates.\n"
            ),
            "assessment/customer.md": (
                "Customers prioritize predictable recovery and transparent "
                "status communication over feature velocity.\n"
            ),
            "assessment/constraints.md": (
                "Budget is fixed for two quarters; headcount cannot "
                "increase.\n"
            ),
        }
        _write_text_corpus(workspace, files, filler_lines=600)

    if fixture_spec.get("git_init"):
        initialized = subprocess.run(
            ["git", "init", "--quiet"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if initialized.returncode != 0:
            raise OSError(f"git init failed: {initialized.stderr.strip()}")
        staged = subprocess.run(
            ["git", "add", "--all"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if staged.returncode != 0:
            raise OSError(f"git add failed: {staged.stderr.strip()}")
        committed = subprocess.run(
            [
                "git",
                "-c",
                "user.name=QwenPaw Bench",
                "-c",
                "user.email=bench@localhost",
                "commit",
                "--quiet",
                "-m",
                "baseline",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if committed.returncode != 0:
            raise OSError(f"git commit failed: {committed.stderr.strip()}")


def _write_text_corpus(
    workspace: Path,
    files: dict[str, str],
    *,
    filler_lines: int,
) -> None:
    """Write deterministic multi-file research fixtures with long context."""
    for relative, evidence in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        filler = "".join(
            f"context-line-{idx:04d}: deterministic background evidence\n"
            for idx in range(filler_lines)
        )
        path.write_text(evidence + filler, encoding="utf-8")


def _artifact_files(workspace: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(
        item for item in workspace.rglob("*") if item.is_file()
    ):
        payload = path.read_bytes()
        files.append(
            {
                "path": str(path.relative_to(workspace)),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
    return files


def _fixture_text(workspace: Path, seed_context: list[dict] | None) -> str:
    chunks: list[str] = []
    for path in sorted(
        item for item in workspace.rglob("*") if item.is_file()
    ):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
    if seed_context:
        chunks.append(json.dumps(seed_context, ensure_ascii=False))
    return "\n".join(chunks)


def _gold_code_check(task: EvalTask, workspace: Path) -> bool:
    if task.verifier not in {"pytest", "pytest_hidden"}:
        return True
    with tempfile.TemporaryDirectory(prefix=f"vc-gold-{task.id}-") as tmp:
        gold = Path(tmp) / "workspace"
        shutil.copytree(workspace, gold)
        if task.fixture_kind == "code":
            path = gold / "module.py"
            text = path.read_text(encoding="utf-8")
            target_priority = 17
            if task.id.startswith("code-"):
                target_priority = int(task.id.split("-")[1]) * 17
            text = text.replace(
                "return records[0]",
                "return next(record for record in records "
                f"if record['priority'] == {target_priority})",
            )
            path.write_text(text, encoding="utf-8")
        elif task.fixture_kind == "code_multi":
            path = gold / "pricing.py"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "return (amount - rebate) * (1 - tier_discount(tier))",
                "return max(0, amount * (1 - tier_discount(tier)) - rebate)",
            )
            path.write_text(text, encoding="utf-8")
        elif task.fixture_kind == "code_pipeline":
            parser_path = gold / "parser.py"
            parser_text = parser_path.read_text(encoding="utf-8").replace(
                "'active': bool(raw.get('active'))",
                "'active': str(raw.get('active', '')).casefold() == 'yes'",
            )
            parser_path.write_text(parser_text, encoding="utf-8")
            pipeline_path = gold / "pipeline.py"
            pipeline_text = pipeline_path.read_text(encoding="utf-8").replace(
                "records = [parse_record(row) for row in rows]\n"
                "    # BUG: duplicate ids must keep only the latest "
                "revision.\n"
                "    return sum(record['amount'] for record in records "
                "if record['active'])",
                "latest = {}\n"
                "    for row in rows:\n"
                "        record = parse_record(row)\n"
                "        latest[record['id']] = record\n"
                "    return sum(record['amount'] for record in "
                "latest.values() if record['active'])",
            )
            pipeline_path.write_text(pipeline_text, encoding="utf-8")
        elif task.fixture_kind == "crosscheck_spec_decoy":
            path = gold / "policy.py"
            text = path.read_text(encoding="utf-8")
            text = (
                text.replace(
                    "from decimal import Decimal",
                    "from decimal import Decimal, ROUND_HALF_UP",
                )
                .replace(
                    "return round(Decimal(str(value)), 2)",
                    "return Decimal(str(value)).quantize(Decimal('0.01'), "
                    "rounding=ROUND_HALF_UP)",
                )
                .replace(
                    "def validate_amount(value):\n"
                    "    return Decimal(str(value))",
                    "def validate_amount(value):\n"
                    "    amount = Decimal(str(value))\n"
                    "    if amount < 0:\n"
                    "        raise ValueError('negative amount')\n"
                    "    return amount",
                )
            )
            path.write_text(text, encoding="utf-8")
        elif task.fixture_kind == "crosscheck_cache_pressure":
            for name, value in (("a", 1), ("b", 2), ("c", 3)):
                (gold / f"state_{name}.txt").write_text(
                    f"VALUE={value}\n",
                    encoding="utf-8",
                )
        if task.verifier == "pytest_hidden":
            hidden = str((task.fixture_spec or {}).get("hidden_test", ""))
            if not hidden:
                return False
            (gold / "_trusted_hidden_test.py").write_text(
                hidden,
                encoding="utf-8",
            )
            pytest_target = "_trusted_hidden_test.py"
        else:
            pytest_target = task.pytest_target
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", pytest_target],
            cwd=gold,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.returncode == 0


def _verifier_command_is_supported(command: list[str]) -> bool:
    """Allow only deterministic, local test commands from trusted tasks."""
    if not command:
        return False
    executable = Path(command[0]).name.casefold()
    if executable == "node":
        return len(command) >= 2
    return bool(
        executable.startswith("python")
        and len(command) >= 4
        and command[1:3] == ["-m", "pytest"],
    )


def _scripted_contract_is_supported(task: EvalTask) -> bool:
    if not (
        task.phase_grades
        and len(task.phase_grades) == len(task.scripted_turns) + 1
        and len(task.phase_ids) == len(task.phase_grades)
    ):
        return False
    return all(
        _verifier_command_is_supported(
            [str(item) for item in spec.get("run", [])],
        )
        for grade in task.phase_grades
        for spec in grade.get("commands", []) or []
    )


def _ground_truth_is_supported(task: EvalTask, workspace: Path) -> bool:
    if not task.ground_truth:
        return True
    if task.verifier == "scripted_declarative":
        contract_supported = _scripted_contract_is_supported(task)
        if task.context_mode != "imported_history":
            return contract_supported
        corpus = _fixture_text(workspace, task.seed_context)
        return bool(
            contract_supported
            and task.required_strings
            and all(token in corpus for token in task.required_strings),
        )
    if task.verifier in {"pytest", "pytest_hidden"}:
        return _gold_code_check(task, workspace)
    if task.verifier == "json_exact":
        return bool(
            task.artifact_path and task.expected_artifact_json is not None,
        )
    if task.fixture_kind == "json":
        records = json.loads((workspace / "catalog.json").read_text())
        total = sum(int(row["amount"]) for row in records if row["selected"])
        return str(total) == task.expected
    corpus = _fixture_text(workspace, task.seed_context)
    evidence = list(task.required_strings)
    if not evidence:
        evidence = [task.expected]
    if task.fixture_kind == "history_report":
        evidence = [
            "HIST_ALPHA_A11",
            "HIST_OMEGA_Z99",
            "release-council",
        ]
    return all(token in corpus for token in evidence)


def _history_visual_preflight(
    task: EvalTask,
    *,
    history_chunk_messages: int,
    render_profile: str,
    render_variant: str,
    min_block_chars: int,
    keep_recent_messages: int,
    max_visual_cost_ratio: float,
    pixels_per_token: float,
    chars_per_text_token: float,
) -> dict[str, Any]:
    """Prove every benchmark task triggers the real visual transformer."""
    if not task.seed_context:
        return {
            "required": True,
            "exercised": False,
            "skipped": False,
            "skip_reason": None,
            "reason": "no_seed_context",
        }
    from agentscope.message import Msg

    from ..agents.context.visual_compression.pipeline.request import (
        transform_model_request,
    )

    model = "preflight-visual-model"
    config_values = dict(
        enabled=True,
        experiment_arm="on",
        allowed_models=[model],
        compress_system=False,
        compress_tools=False,
        compress_tool_results=False,
        compress_history=True,
        min_block_chars=min_block_chars,
        min_static_tokens=500,
        keep_recent_messages=keep_recent_messages,
        history_chunk_messages=history_chunk_messages,
        history_collapse_grid_messages=50,
        max_images_per_request=64,
        max_images_per_tool_result=10,
        factsheet_limit=96,
        render_profile=render_profile,
        render_variant=render_variant,
        pixels_per_token=pixels_per_token,
        chars_per_text_token=chars_per_text_token,
        max_visual_cost_ratio=max_visual_cost_ratio,
        emit_factsheet=True,
        record_factsheet_text=True,
        receipt_dir=None,
    )
    config_values.update(
        {
            key: value
            for key, value in _task_visual_profile(task).items()
            if key != "name"
        },
    )
    config = SimpleNamespace(**config_values)
    messages = [Msg.model_validate(item) for item in (task.seed_context or [])]
    _, _, receipt = transform_model_request(
        messages,
        None,
        model=model,
        config=config,
    )
    # TODO: STALE: This preflight exists only for the temporary benchmark and
    # explicitly opts into the evaluation payload above.
    evaluation = receipt.evaluation
    if evaluation is None:
        raise RuntimeError("visual benchmark evaluation was not collected")
    factsheet_text_value = "\n".join(
        str(item.get("text", "")) for item in evaluation.factsheet_records
    )
    skipped = receipt.reason == "nothing_profitable"
    return {
        "required": True,
        "exercised": bool(
            evaluation.history_chunks > 0 and evaluation.image_count > 0,
        ),
        "skipped": skipped,
        "skip_reason": receipt.reason if skipped else None,
        "reason": receipt.reason,
        "history_chunks": evaluation.history_chunks,
        "image_count": evaluation.image_count,
        "compressed_chars": evaluation.compressed_chars,
        "original_estimated_tokens": evaluation.original_estimated_tokens,
        "transformed_estimated_tokens": (
            evaluation.transformed_estimated_tokens
        ),
        "factsheet_probe_matches": [
            probe
            for probe in task.answer_probes
            if probe in factsheet_text_value
        ],
        # TODO: STALE: Keep resolved geometry beside the benchmark profile so
        # the CLI's base render variant cannot be mistaken for a task-level
        # override. Remove with this preflight-only evidence.
        "render_geometry": evaluation.render_geometry,
        "benchmark_visual_profile": _task_visual_profile(task),
    }


def _prepare_task_artifacts(
    output_dir: Path,
    tasks: list[EvalTask],
    *,
    history_chunk_messages: int = 10,
    render_profile: str = "calibrated",
    render_variant: str = "v0_pxpipe",
    min_block_chars: int = 4000,
    keep_recent_messages: int = 6,
    max_visual_cost_ratio: float = 0.90,
    pixels_per_token: float = 750.0,
    chars_per_text_token: float = 4.0,
) -> dict[str, Any]:
    """Materialize immutable task inputs once and validate solvability."""
    root = output_dir / "task_artifacts"
    entries: list[dict[str, Any]] = []
    for task in tasks:
        workspace = root / task.id
        if workspace.exists():
            shutil.rmtree(workspace)
        _write_fixture(workspace, task)
        files = _artifact_files(workspace)
        seed_turn_chars = [
            len(json.dumps(message, ensure_ascii=False))
            for message in (task.seed_context or [])
        ]
        largest_file_bytes = max(
            (int(item["bytes"]) for item in files),
            default=0,
        )
        max_input_file_bytes = (
            task.max_input_file_bytes or MAX_BENCHMARK_INPUT_FILE_BYTES
        )
        files_are_bounded = largest_file_bytes <= max_input_file_bytes
        required_turns = (
            LONG_CONTEXT_MIN_TURNS
            if task.difficulty == "long"
            else BENCHMARK_CONTEXT_MIN_TURNS
        )
        organic_context = task.context_mode == "organic"
        imported_context = task.context_mode == "imported_history"
        prompt_hides_ground_truth = bool(
            not imported_context or task.expected not in task.instruction,
        )
        if organic_context:
            accumulated_context = bool(
                not task.seed_context and len(task.scripted_turns) >= 3,
            )
        elif imported_context:
            # Imported transcripts intentionally retain realistic large tool
            # results. The short-turn constraint used by synthetic histories
            # does not apply, but this must still be a genuinely long input.
            accumulated_context = bool(
                len(seed_turn_chars) >= required_turns
                and sum(seed_turn_chars) >= LONG_CONTEXT_MIN_TOTAL_CHARS,
            )
        else:
            accumulated_context = bool(
                len(seed_turn_chars) >= required_turns
                and sum(seed_turn_chars) >= LONG_CONTEXT_MIN_TOTAL_CHARS
                and max(seed_turn_chars, default=0)
                <= LONG_CONTEXT_MAX_TURN_CHARS,
            )
        history_visual = (
            {
                "required": False,
                "exercised": False,
                "skipped": False,
                "skip_reason": None,
                "reason": "runtime_organic_accumulation",
                "history_chunks": 0,
                "image_count": 0,
                "compressed_chars": 0,
                "original_estimated_tokens": 0,
                "transformed_estimated_tokens": 0,
                "factsheet_probe_matches": [],
            }
            if organic_context
            else _history_visual_preflight(
                task,
                history_chunk_messages=history_chunk_messages,
                render_profile=render_profile,
                render_variant=render_variant,
                min_block_chars=min_block_chars,
                keep_recent_messages=keep_recent_messages,
                max_visual_cost_ratio=max_visual_cost_ratio,
                pixels_per_token=pixels_per_token,
                chars_per_text_token=chars_per_text_token,
            )
        )
        artifact_contract = True
        source_citations_supported = True
        if task.verifier == "artifact_contract":
            output = Path(str(task.artifact_path or ""))
            artifact_contract = bool(
                task.artifact_path
                and not output.is_absolute()
                and ".." not in output.parts
                and task.required_sections
                and task.min_artifact_chars > 0,
            )
            relative_files = {
                str(path.relative_to(workspace))
                for path in workspace.rglob("*")
                if path.is_file()
            }
            basenames = {Path(path).name for path in relative_files}
            source_citations_supported = all(
                citation in relative_files or citation in basenames
                for citation in task.required_source_citations
            )
        pytest_target_exists = (
            (workspace / task.pytest_target).is_file()
            if task.verifier == "pytest"
            else True
        )
        scripted_contract = (
            _scripted_contract_is_supported(task)
            if task.verifier == "scripted_declarative"
            else True
        )
        has_inputs = bool(files or task.seed_context or task.scripted_turns)
        ground_truth_supported = _ground_truth_is_supported(task, workspace)
        checks = {
            "has_inputs": has_inputs,
            "files_are_bounded": files_are_bounded,
            "context_accumulated": accumulated_context,
            "visual_compression_ready": (
                True
                if organic_context
                else bool(
                    history_visual["exercised"]
                    or history_visual.get("skipped", False),
                )
            ),
            "artifact_contract": artifact_contract,
            "source_citations_supported": source_citations_supported,
            "pytest_target_exists": pytest_target_exists,
            "scripted_contract": scripted_contract,
            "ground_truth_supported": ground_truth_supported,
            "prompt_hides_ground_truth": prompt_hides_ground_truth,
        }
        entries.append(
            {
                "task_id": task.id,
                "difficulty": task.difficulty,
                "workspace": str(workspace.resolve()),
                "files": files,
                "input_shape": {
                    "largest_file_bytes": largest_file_bytes,
                    "max_file_bytes": max_input_file_bytes,
                    "seed_turns": len(seed_turn_chars),
                    "seed_total_chars": sum(seed_turn_chars),
                    "seed_max_turn_chars": max(seed_turn_chars, default=0),
                    "seed_context_source": task.seed_context_source,
                    "seed_context_sha256": task.seed_context_sha256,
                    "seed_context_format": task.seed_context_format,
                },
                "history_visual_preflight": history_visual,
                "benchmark_visual_profile": _task_visual_profile(task),
                "checks": checks,
                "solvable_contract": all(checks.values()),
            },
        )
    payload = {
        "status": (
            "pass"
            if entries and all(x["solvable_contract"] for x in entries)
            else "fail"
        ),
        "task_artifacts_root": str(root.resolve()),
        "tasks": entries,
    }
    (output_dir / "preflight.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _safe_workspace_path(workspace: Path, relative: str) -> Path | None:
    target = (workspace / relative).resolve()
    return target if target.is_relative_to(workspace.resolve()) else None


def _match_declarative_field(matcher: dict[str, Any], captured: str) -> bool:
    if len(matcher) != 1:
        return False
    kind, expected = next(iter(matcher.items()))
    actual = str(captured or "").strip()
    if kind == "eq":
        return actual == str(expected)
    if kind == "int":
        try:
            return int(re.sub(r"[,\s]", "", actual)) == int(expected)
        except ValueError:
            return False
    if kind == "num":
        try:
            return float(actual) == float(expected)
        except ValueError:
            return False
    if kind == "list" and isinstance(expected, list):
        got = [
            item.strip().casefold()
            for item in actual.split(",")
            if item.strip()
        ]
        want = [str(item).casefold() for item in expected]
        return got == want
    if kind == "set" and isinstance(expected, list):
        got = sorted(
            item.strip().upper() for item in actual.split(",") if item.strip()
        )
        want = sorted(str(item).upper() for item in expected)
        return got == want
    return False


def _evaluate_declarative_grade(
    grade: dict[str, Any],
    response: str,
    workspace: Path,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    keyword_spec = grade.get("keyword")
    if isinstance(keyword_spec, dict):
        must_hits = [
            str(term)
            for term in keyword_spec.get("must_any", []) or []
            if str(term) in response
        ]
        forbidden_hits = [
            str(term)
            for term in keyword_spec.get("must_not_any", []) or []
            if str(term) in response
        ]
        bonus_hits = [
            str(term)
            for term in keyword_spec.get("bonus_any", []) or []
            if str(term) in response
        ]
        checks["keyword"] = {
            "pass": bool(must_hits) and not forbidden_hits,
            "must_hits": must_hits,
            "forbidden_hits": forbidden_hits,
            "bonus_hits": bonus_hits,
        }
    answer_spec = grade.get("answer")
    if isinstance(answer_spec, dict):
        pattern = str(answer_spec.get("regex", ""))
        matches = [
            match
            for line in response.splitlines()
            if (match := re.search(pattern, line.strip())) is not None
        ]
        answer_match = matches[-1] if matches else None
        field_checks = []
        if answer_match is not None:
            field_checks = [
                _match_declarative_field(
                    matcher,
                    answer_match.group(index + 1),
                )
                for index, matcher in enumerate(answer_spec.get("fields", []))
                if index + 1 <= len(answer_match.groups())
            ]
        expected_fields = len(answer_spec.get("fields", []))
        answer_pass = bool(
            answer_match is not None
            and len(field_checks) == expected_fields
            and all(field_checks),
        )
        checks["answer"] = {
            "pass": answer_pass,
            "regex": pattern,
            "matched_line": (
                answer_match.string.strip() if answer_match else None
            ),
            "field_checks": field_checks,
        }

    file_checks: list[dict[str, Any]] = []
    for spec in grade.get("files", []) or []:
        relative = str(spec.get("path", ""))
        path = _safe_workspace_path(workspace, relative)
        actual = None
        error = None
        if path is None:
            error = "path escapes workspace"
        elif not path.is_file():
            error = "missing"
        else:
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                error = str(exc)
        file_checks.append(
            {
                "path": relative,
                "pass": error is None and actual == spec.get("json_equals"),
                "error": error,
            },
        )
    if file_checks:
        checks["files"] = file_checks

    first_line_checks: list[dict[str, Any]] = []
    first_line_spec = grade.get("files_first_line")
    if isinstance(first_line_spec, dict):
        wanted = str(first_line_spec.get("equals", ""))
        for relative_raw in first_line_spec.get("paths", []) or []:
            relative = str(relative_raw)
            path = _safe_workspace_path(workspace, relative)
            actual = None
            if path is not None and path.is_file():
                actual = (
                    path.read_text(encoding="utf-8").splitlines()[0].strip()
                )
            first_line_checks.append(
                {"path": relative, "pass": actual == wanted, "actual": actual},
            )
    if first_line_checks:
        checks["files_first_line"] = first_line_checks

    command_checks: list[dict[str, Any]] = []
    for spec in grade.get("commands", []) or []:
        command = [str(item) for item in spec.get("run", [])]
        expected_exit = int(spec.get("exit", 0))
        if not _verifier_command_is_supported(command):
            command_checks.append(
                {
                    "run": command,
                    "pass": False,
                    "error": "unsupported verifier",
                },
            )
            continue
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            command_checks.append(
                {
                    "run": command,
                    "pass": completed.returncode == expected_exit,
                    "returncode": completed.returncode,
                    "output": (completed.stdout + completed.stderr)[-2000:],
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            command_checks.append(
                {"run": command, "pass": False, "error": str(exc)},
            )
    if command_checks:
        checks["commands"] = command_checks

    tool_contract = grade.get("tool_contract")
    tool_contract_pass = True
    if isinstance(tool_contract, dict):
        observed = list(tool_calls or [])
        names = [str(item.get("name", "")) for item in observed]
        forbidden = [str(item) for item in tool_contract.get("forbidden", [])]
        forbidden_hits = [name for name in names if name in forbidden]
        maximum = tool_contract.get("max_calls")
        max_calls_pass = maximum is None or len(observed) <= int(maximum)
        required_checks = []
        for spec in tool_contract.get("required", []) or []:
            name = str(spec.get("name", ""))
            count = sum(item == name for item in names)
            required_checks.append(
                {
                    "name": name,
                    "count": count,
                    "minimum": int(spec.get("min_calls", 1) or 1),
                    "pass": count >= int(spec.get("min_calls", 1) or 1),
                },
            )
        input_checks = []
        for spec in tool_contract.get("input_contains", []) or []:
            name = str(spec.get("name", ""))
            needle = str(spec.get("text", ""))
            occurrences = sum(
                json.dumps(item.get("input", ""), ensure_ascii=False).count(
                    needle,
                )
                for item in observed
                if str(item.get("name", "")) == name
            )
            minimum = int(spec.get("min_occurrences", 1) or 1)
            input_checks.append(
                {
                    "name": name,
                    "text": needle,
                    "occurrences": occurrences,
                    "minimum": minimum,
                    "pass": occurrences >= minimum,
                },
            )
        tool_contract_pass = bool(
            not forbidden_hits
            and max_calls_pass
            and all(item["pass"] for item in required_checks)
            and all(item["pass"] for item in input_checks),
        )
        checks["tool_contract"] = {
            "pass": tool_contract_pass,
            "call_count": len(observed),
            "forbidden_hits": forbidden_hits,
            "max_calls_pass": max_calls_pass,
            "required_checks": required_checks,
            "input_checks": input_checks,
        }

    flattened = []
    if "keyword" in checks:
        flattened.append(bool(checks["keyword"]["pass"]))
    if "answer" in checks:
        flattened.append(bool(checks["answer"]["pass"]))
    flattened.extend(bool(item["pass"]) for item in file_checks)
    flattened.extend(bool(item["pass"]) for item in first_line_checks)
    flattened.extend(bool(item["pass"]) for item in command_checks)
    if isinstance(tool_contract, dict):
        flattened.append(tool_contract_pass)
    return {"pass": bool(flattened and all(flattened)), "checks": checks}


def _evaluate_task(
    task: EvalTask,
    result: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    """Return deterministic completion, accuracy and contract scores."""
    response = str(result.get("response", "")).strip()
    exact_response = response == f"FINAL: {task.expected}"
    semantic_answer = task.expected in response
    details: dict[str, Any] = {
        "exact_response": exact_response,
        "semantic_answer": semantic_answer,
    }
    artifact_paths: list[str] = []

    if task.verifier == "scripted_declarative":
        responses = [str(item) for item in result.get("phase_responses", [])]
        phase_records = list(result.get("phase_records", []) or [])
        phase_checks = []
        for index, grade in enumerate(task.phase_grades):
            response_text = responses[index] if index < len(responses) else ""
            phase_tool_calls = (
                list(phase_records[index].get("tool_calls", []) or [])
                if index < len(phase_records)
                else []
            )
            evaluated = _evaluate_declarative_grade(
                grade,
                response_text,
                workspace,
                phase_tool_calls,
            )
            phase_checks.append(
                {
                    "id": task.phase_ids[index],
                    "pass": evaluated["pass"],
                    "checks": evaluated["checks"],
                },
            )
        completion = (
            sum(
                bool(item.strip())
                for item in responses[: len(task.phase_grades)]
            )
            / len(task.phase_grades)
            if task.phase_grades
            else 0.0
        )
        accuracy = (
            sum(bool(item["pass"]) for item in phase_checks)
            / len(phase_checks)
            if phase_checks
            else 0.0
        )
        quality_pass = bool(
            len(responses) == len(task.phase_grades)
            and phase_checks
            and all(item["pass"] for item in phase_checks),
        )
        exact_response = bool(
            phase_checks
            and all(
                bool(
                    item["checks"]
                    .get(
                        "answer",
                        item["checks"].get("keyword", {}),
                    )
                    .get("pass"),
                )
                for item in phase_checks
            ),
        )
        details.update(
            {
                "phase_count": len(responses),
                "expected_phase_count": len(task.phase_grades),
                "phase_checks": phase_checks,
            },
        )
    elif task.verifier == "artifact_contract":
        artifact = workspace / str(task.artifact_path)
        exists = artifact.is_file()
        text = artifact.read_text(encoding="utf-8") if exists else ""
        if exists:
            artifact_paths.append(str(artifact.resolve()))
        checks = [exists]
        if task.min_artifact_chars > 0:
            checks.append(len(text) >= task.min_artifact_chars)
        section_checks = {
            section: section.casefold() in text.casefold()
            for section in task.required_sections
        }
        checks.extend(section_checks.values())
        completion = sum(bool(item) for item in checks) / max(len(checks), 1)
        fact_checks = {fact: fact in text for fact in task.required_strings}
        source_citation_checks = {
            citation: citation in text
            for citation in task.required_source_citations
        }
        evidence_group_checks = {
            str(
                group.get("id") or f"group-{index + 1}",
            ): _evidence_group_matches(
                text,
                tuple(str(term) for term in group.get("terms", [])),
                int(group.get("max_span_chars", 2500) or 2500),
            )
            for index, group in enumerate(task.required_evidence_groups)
        }
        forbidden_pattern_checks = {
            pattern: re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            is None
            for pattern in task.forbidden_patterns
        }
        accuracy_checks = [
            *fact_checks.values(),
            *source_citation_checks.values(),
            *evidence_group_checks.values(),
            *forbidden_pattern_checks.values(),
        ]
        accuracy = (
            sum(bool(item) for item in accuracy_checks) / len(accuracy_checks)
            if task.ground_truth and accuracy_checks
            else None
        )
        quality_pass = completion == 1.0 and (
            accuracy is None or accuracy == 1.0
        )
        details.update(
            {
                "artifact_exists": exists,
                "artifact_chars": len(text),
                "section_checks": section_checks,
                "fact_checks": fact_checks,
                "source_citation_checks": source_citation_checks,
                "evidence_group_checks": evidence_group_checks,
                "forbidden_pattern_checks": forbidden_pattern_checks,
            },
        )
    elif task.verifier == "json_exact":
        artifact = workspace / str(task.artifact_path)
        exists = artifact.is_file()
        actual: Any = None
        parse_error = None
        if exists:
            artifact_paths.append(str(artifact.resolve()))
            try:
                actual = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                parse_error = str(exc)
        exact_artifact = actual == task.expected_artifact_json
        completion = 1.0 if exists and parse_error is None else 0.0
        accuracy = 1.0 if exact_artifact and semantic_answer else 0.0
        quality_pass = exact_artifact and semantic_answer
        details.update(
            {
                "artifact_exists": exists,
                "artifact_json_exact": exact_artifact,
                "artifact_parse_error": parse_error,
            },
        )
    else:
        completion = 1.0 if response else 0.0
        test_pass = True
        if task.verifier in {"pytest", "pytest_hidden"}:
            pytest_target = task.pytest_target
            trusted_workspace: Path | None = None
            if task.verifier == "pytest_hidden":
                hidden = str((task.fixture_spec or {}).get("hidden_test", ""))
                trusted_workspace = Path(
                    tempfile.mkdtemp(prefix=f"vc-hidden-{task.id}-"),
                )
                shutil.copytree(
                    workspace,
                    trusted_workspace,
                    dirs_exist_ok=True,
                )
                (trusted_workspace / "_trusted_hidden_test.py").write_text(
                    hidden,
                    encoding="utf-8",
                )
                pytest_target = "_trusted_hidden_test.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    pytest_target,
                ],
                cwd=trusted_workspace or workspace,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            test_pass = completed.returncode == 0
            details["pytest_returncode"] = completed.returncode
            details["pytest_output"] = completed.stdout[-2000:]
            if trusted_workspace is not None:
                shutil.rmtree(trusted_workspace, ignore_errors=True)
        accuracy = 1.0 if semantic_answer and test_pass else 0.0
        quality_pass = semantic_answer and test_pass

    observed_tool_calls = int(
        (result.get("execution", {}) or {}).get("tool_calls", 0) or 0,
    )
    tool_limit_pass = (
        task.max_tool_calls is None
        or observed_tool_calls <= task.max_tool_calls
    )
    details["tool_limit"] = task.max_tool_calls
    details["observed_tool_calls"] = observed_tool_calls
    details["tool_limit_pass"] = tool_limit_pass
    quality_pass = bool(quality_pass and tool_limit_pass)
    if not tool_limit_pass:
        accuracy = 0.0

    return {
        "quality_pass": quality_pass,
        "format_pass": exact_response,
        "completion_score": round(completion, 4),
        "accuracy_score": (
            round(accuracy, 4) if accuracy is not None else None
        ),
        "review_required": not task.ground_truth,
        "artifact_paths": artifact_paths,
        "details": details,
    }


def _verify(task: EvalTask, result: dict[str, Any], workspace: Path) -> bool:
    """Backward-compatible boolean verifier used by focused tests."""
    return bool(_evaluate_task(task, result, workspace)["quality_pass"])


def _evidence_group_matches(
    text: str,
    terms: tuple[str, ...],
    max_span_chars: int,
) -> bool:
    """Require all claim terms to occur together in a bounded text span.

    Plain substring checks can mark a report correct when unrelated values are
    scattered across contradictory sections. A bounded evidence group keeps
    labels, model/run identity, and their metrics locally associated while
    remaining tolerant of prose and Markdown table layout.
    """
    if not terms or max_span_chars <= 0:
        return False
    folded = text.casefold()
    events: list[tuple[int, int, int]] = []
    for term_index, term in enumerate(terms):
        needle = term.casefold()
        if not needle:
            return False
        start = 0
        found = False
        while True:
            position = folded.find(needle, start)
            if position < 0:
                break
            found = True
            events.append((position, position + len(needle), term_index))
            start = position + 1
        if not found:
            return False
    events.sort()
    counts = [0] * len(terms)
    covered = 0
    left = 0
    for right, (_, right_end, term_index) in enumerate(events):
        if counts[term_index] == 0:
            covered += 1
        counts[term_index] += 1
        while covered == len(terms) and left <= right:
            left_start = events[left][0]
            if right_end - left_start <= max_span_chars:
                return True
            left_term = events[left][2]
            counts[left_term] -= 1
            if counts[left_term] == 0:
                covered -= 1
            left += 1
    return False


def _model_slot(value: str):
    from ..config.config import ModelSlotConfig

    if "/" not in value:
        raise click.ClickException("--model must be <provider>/<model-id>")
    provider, model = value.split("/", 1)
    return ModelSlotConfig(provider_id=provider, model=model)


def _eval_allowed_tools(task: EvalTask) -> set[str]:
    """Keep task solving within the smallest required tool surface."""
    allowed = set() if task.tool_policy == "none" else {"read_file"}
    if task.verifier in {"pytest", "pytest_hidden"}:
        allowed.add("edit_file")
    if task.artifact_path:
        allowed.update({"write_file", "edit_file"})
        if task.tool_policy != "no_search":
            allowed.update({"glob_search", "grep_search"})
    allowed.update(task.required_tools)
    return allowed


def _effective_max_iters(task: EvalTask, cli_max_iters: int) -> int:
    """Resolve a task limit under an optional suite-wide safety ceiling."""
    task_limit = int(task.max_iters or 30)
    if cli_max_iters > 0:
        return min(task_limit, int(cli_max_iters))
    return task_limit


def _phase_metric_rows(
    task: EvalTask,
    result: dict[str, Any],
    trace: list[dict[str, Any]],
    cost_config: CostConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in result.get("phase_records", []) or []:
        index = int(record.get("index", len(rows)) or 0)
        start = int(record.get("call_start", 0) or 0)
        end = int(record.get("call_end", start) or start)
        calls = trace[start:end]
        input_tokens = sum(
            int(call.get("prompt_tokens", 0) or 0) for call in calls
        )
        output_tokens = sum(
            int(call.get("completion_tokens", 0) or 0) for call in calls
        )
        cache_read_tokens = sum(
            int(call.get("cache_input_tokens", 0) or 0) for call in calls
        )
        cache_creation_tokens = sum(
            int(call.get("cache_creation_input_tokens", 0) or 0)
            for call in calls
        )
        visual = [call.get("visual_compression", {}) or {} for call in calls]
        factsheet_text = "\n".join(
            str(item.get("text", ""))
            for receipt in visual
            for item in receipt.get("factsheet_records", []) or []
        )
        rows.append(
            {
                "phase_index": index,
                "phase_id": (
                    task.phase_ids[index]
                    if index < len(task.phase_ids)
                    else f"phase-{index + 1}"
                ),
                "elapsed_seconds": float(
                    record.get("elapsed_seconds", 0) or 0,
                ),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_input_tokens": cache_read_tokens,
                "cache_creation_input_tokens": cache_creation_tokens,
                **_cost_metrics(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_creation_tokens,
                    cost_config,
                ),
                "llm_calls": len(calls),
                "failed_llm_attempts": sum(
                    (call.get("timing", {}) or {}).get("status") == "error"
                    for call in calls
                ),
                "provider_time_seconds": sum(
                    float(call.get("provider_time_seconds", 0) or 0)
                    for call in calls
                ),
                "compressed_chars": sum(
                    int(receipt.get("compressed_chars", 0) or 0)
                    for receipt in visual
                ),
                "image_count": sum(
                    int(receipt.get("image_count", 0) or 0)
                    for receipt in visual
                ),
                "history_chunks": sum(
                    int(receipt.get("history_chunks", 0) or 0)
                    for receipt in visual
                ),
                "factsheet_probe_matches": [
                    probe
                    for probe in task.answer_probes
                    if probe in factsheet_text
                ],
            },
        )
    return rows


def _result_row(
    task: EvalTask,
    arm: str,
    result: dict[str, Any],
    *,
    run_dir: Path,
    effective_max_iters: int,
    cost_config: CostConfig,
    resume_reused: bool = False,
) -> dict[str, Any]:
    """Build the scored metric row from a durable raw arm result."""
    workspace = run_dir / "workspace"
    verification = _evaluate_task(task, result, workspace)
    trace = result.get("trace", []) or []
    timing = [call.get("timing", {}) or {} for call in trace]
    successful_timing = [
        item for item in timing if item.get("status", "success") == "success"
    ]
    failed_timing = [item for item in timing if item.get("status") == "error"]
    raw_elapsed_seconds = float(result.get("elapsed_seconds", 0) or 0)
    # A task that eventually succeeds may contain failed provider attempts
    # transparently recovered by RetryChatModel. Keep those attempts for
    # infrastructure audit, but do not attribute their time/call count to
    # agent inference efficiency.
    excluded_retry_seconds = (
        sum(float(item.get("total_seconds", 0) or 0) for item in failed_timing)
        if result.get("status") == "success"
        else 0.0
    )
    normalized_elapsed_seconds = max(
        0.0,
        raw_elapsed_seconds - excluded_retry_seconds,
    )
    visual_receipts = [
        call.get("visual_compression", {}) or {} for call in trace
    ]
    task_usage = result.get("usage", {}) or {}
    input_tokens = int(task_usage.get("input_tokens", 0) or 0)
    output_tokens = int(task_usage.get("output_tokens", 0) or 0)
    cache_creation_tokens = sum(
        int(x.get("cache_creation_input_tokens", 0) or 0) for x in trace
    )
    cache_read_tokens = sum(
        int(x.get("cache_input_tokens", 0) or 0) for x in trace
    )
    cost_metrics = _cost_metrics(
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_creation_tokens,
        cost_config,
    )
    provider_seconds = sum(
        float(x.get("provider_time_seconds", 0) or 0) for x in trace
    )
    output_text_chars = sum(int(x.get("text_chars", 0) or 0) for x in timing)
    output_tool_use_chars = sum(
        int(x.get("tool_use_chars", 0) or 0) for x in timing
    )
    output_thinking_chars = sum(
        int(x.get("thinking_chars", 0) or 0) for x in timing
    )
    output_chars = (
        output_text_chars + output_tool_use_chars + output_thinking_chars
    )
    cache_rates = [
        int(call.get("cache_input_tokens", 0) or 0)
        / int(call.get("prompt_tokens", 0) or 1)
        for call in trace
        if int(call.get("prompt_tokens", 0) or 0) > 0
    ]
    cache_zero_calls = sum(
        int(call.get("cache_input_tokens", 0) or 0) == 0
        for call in trace
        if (call.get("timing", {}) or {}).get("status", "success") == "success"
    )
    prefix_breaks = 0
    history_sha_breaks = 0
    static_slab_sha_changes = 0
    previous_components: list[str] = []
    previous_history: list[str] = []
    previous_static: list[str] | None = None
    factsheet_corpus: list[str] = []
    call_diagnostics: list[dict[str, Any]] = []
    for call_index, call in enumerate(trace, 1):
        visual = call.get("visual_compression", {}) or {}
        components = list(visual.get("cacheable_prefix_components", []) or [])
        history_sha = [
            str(item.get("sha256"))
            for item in (visual.get("page_records", []) or [])
            if item.get("region") == "history" and item.get("sha256")
        ]
        static_sha = [
            str(item.get("sha256"))
            for item in (visual.get("page_records", []) or [])
            if item.get("region") == "static_slab" and item.get("sha256")
        ]
        if previous_components and components:
            prefix_breaks += int(
                components[: len(previous_components)] != previous_components
                and previous_components[: len(components)] != components,
            )
        if previous_history and history_sha:
            history_sha_breaks += int(
                history_sha[: len(previous_history)] != previous_history
                and previous_history[: len(history_sha)] != history_sha,
            )
        if previous_static is not None and static_sha:
            static_slab_sha_changes += int(static_sha != previous_static)
        if components:
            previous_components = components
        if history_sha:
            previous_history = history_sha
        if static_sha:
            previous_static = static_sha
        for item in visual.get("factsheet_records", []) or []:
            factsheet_corpus.append(str(item.get("text", "")))
        prompt_tokens = int(call.get("prompt_tokens", 0) or 0)
        cached_tokens = int(call.get("cache_input_tokens", 0) or 0)
        call_diagnostics.append(
            {
                "call": call_index,
                "render_variant": visual.get("render_variant", "v0_pxpipe"),
                "render_profile": visual.get("render_profile"),
                "render_geometry": visual.get("render_geometry", {}),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": int(
                    call.get("completion_tokens", 0) or 0,
                ),
                "cached_tokens": cached_tokens,
                "cache_rate": (
                    cached_tokens / prompt_tokens if prompt_tokens else None
                ),
                "output_chars": int(
                    (call.get("timing", {}) or {}).get("output_chars", 0) or 0,
                ),
                "history_chunks": int(visual.get("history_chunks", 0) or 0),
                "image_sha256": list(visual.get("image_sha256", []) or []),
                "history_image_sha256": history_sha,
                "static_slab_sha256": static_sha,
                "cacheable_prefix_digest": visual.get(
                    "cacheable_prefix_digest",
                ),
                "cacheable_prefix_components": components,
            },
        )
    factsheet_text_value = "\n".join(factsheet_corpus)
    factsheet_probe_matches = [
        probe for probe in task.answer_probes if probe in factsheet_text_value
    ]
    phase_metrics = _phase_metric_rows(task, result, trace, cost_config)
    phase_checks = {
        str(item.get("id")): bool(item.get("pass"))
        for item in verification.get("details", {}).get("phase_checks", [])
    }
    for phase in phase_metrics:
        phase["quality_pass"] = phase_checks.get(str(phase["phase_id"]))
    traced_seconds = sum(
        float(item.get("total_seconds", 0) or 0) for item in timing
    )
    unattributed_wait_seconds = max(0.0, raw_elapsed_seconds - traced_seconds)
    compressed_chars = sum(
        int(item.get("compressed_chars", 0) or 0) for item in visual_receipts
    )
    image_count = sum(
        int(item.get("image_count", 0) or 0) for item in visual_receipts
    )
    image_pixels = sum(
        int(item.get("image_pixels", 0) or 0) for item in visual_receipts
    )
    image_bytes = sum(
        int(item.get("image_bytes", 0) or 0) for item in visual_receipts
    )
    estimated_image_tokens = sum(
        int(item.get("estimated_image_tokens", 0) or 0)
        for item in visual_receipts
    )
    rendered_source_chars = sum(
        int(page.get("source_chars", 0) or 0)
        for receipt in visual_receipts
        for page in (receipt.get("page_records", []) or [])
    )
    render_geometry = next(
        (
            dict(item.get("render_geometry", {}) or {})
            for item in visual_receipts
            if item.get("render_geometry")
        ),
        {},
    )
    theoretical_chars_per_image = int(
        render_geometry.get("theoretical_ascii_chars_per_image", 0) or 0,
    )
    return {
        "task_id": task.id,
        "category": task.category,
        "difficulty": task.difficulty,
        "arm": arm,
        "render_variant": next(
            (
                str(item.get("render_variant"))
                for item in visual_receipts
                if item.get("render_variant")
            ),
            "v0_pxpipe",
        ),
        "effective_max_iters": effective_max_iters,
        "seed_context_turns": len(task.seed_context or []),
        "seed_context_chars": sum(
            len(json.dumps(message, ensure_ascii=False))
            for message in (task.seed_context or [])
        ),
        "status": result.get("status"),
        "quality_pass": verification["quality_pass"],
        "format_pass": verification["format_pass"],
        "completion_score": verification["completion_score"],
        "accuracy_score": verification["accuracy_score"],
        "review_required": verification["review_required"],
        "verification": verification["details"],
        "artifact_paths": verification["artifact_paths"],
        "elapsed_seconds": round(normalized_elapsed_seconds, 4),
        "raw_elapsed_seconds": round(raw_elapsed_seconds, 4),
        "excluded_retry_seconds": round(excluded_retry_seconds, 4),
        "input_tokens": input_tokens,
        "provider_input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "output_chars": output_chars,
        "output_text_chars": output_text_chars,
        "output_tool_use_chars": output_tool_use_chars,
        "output_thinking_chars": output_thinking_chars,
        "chars_per_output_token": (
            output_chars / output_tokens if output_tokens > 0 else None
        ),
        "usage_source": task_usage.get("source", "recorder_trace"),
        "recorder_tokens": task_usage.get("recorder_tokens"),
        "provider_time_seconds": provider_seconds,
        "traced_attempt_seconds": traced_seconds,
        "unattributed_wait_seconds": unattributed_wait_seconds,
        "network_timing_anomaly": unattributed_wait_seconds
        > max(30.0, provider_seconds * 0.5),
        "output_tokens_per_second": (
            output_tokens / provider_seconds if provider_seconds > 0 else None
        ),
        "cache_creation_input_tokens": cache_creation_tokens,
        "cache_input_tokens": cache_read_tokens,
        "cache_zero_calls": cache_zero_calls,
        "cache_rate_mean": _mean(cache_rates),
        "cache_tokens_are_prompt_subset": all(
            int(call.get("cache_input_tokens", 0) or 0)
            <= int(call.get("prompt_tokens", 0) or 0)
            for call in trace
        ),
        **cost_metrics,
        "llm_calls": (
            len(successful_timing)
            if trace
            else int(task_usage.get("llm_calls", 0) or 0)
        ),
        "raw_llm_attempts": (
            len(trace) if trace else int(task_usage.get("llm_calls", 0) or 0)
        ),
        "failed_llm_attempts": len(failed_timing),
        "agent_iterations": int(
            (result.get("execution", {}) or {}).get("agent_iterations", 0)
            or 0,
        ),
        "tool_calls": int(
            (result.get("execution", {}) or {}).get("tool_calls", 0) or 0,
        ),
        "recovery_calls": int(
            (
                (result.get("execution", {}) or {}).get(
                    "tool_calls_by_name",
                    {},
                )
                or {}
            ).get("recover_visual_context", 0)
            or 0,
        ),
        "context_messages": int(
            (result.get("execution", {}) or {}).get("context_messages", 0)
            or 0,
        ),
        "ttft_seconds": sum(
            float(x.get("ttft_seconds", 0) or 0) for x in successful_timing
        ),
        "transform_ms": sum(
            float(x.get("transform_ms", 0) or 0) for x in visual_receipts
        ),
        "estimated_image_tokens": estimated_image_tokens,
        "gate_text_tokens": sum(
            int(x.get("gate_text_tokens", 0) or 0) for x in visual_receipts
        ),
        "gate_visual_tokens": sum(
            int(x.get("gate_visual_tokens", 0) or 0) for x in visual_receipts
        ),
        "gate_candidates": sum(
            int(x.get("gate_candidates", 0) or 0) for x in visual_receipts
        ),
        "gate_accepted": sum(
            int(x.get("gate_accepted", 0) or 0) for x in visual_receipts
        ),
        "original_estimated_tokens": sum(
            int(x.get("original_estimated_tokens", 0) or 0)
            for x in visual_receipts
        ),
        "transformed_estimated_tokens": sum(
            int(x.get("transformed_estimated_tokens", 0) or 0)
            for x in visual_receipts
        ),
        "compressed_chars": compressed_chars,
        "image_count": image_count,
        "image_pixels": image_pixels,
        "image_bytes": image_bytes,
        "rendered_source_chars": rendered_source_chars,
        "theoretical_ascii_chars_per_image": theoretical_chars_per_image,
        "chars_per_image": (
            compressed_chars / image_count if image_count > 0 else None
        ),
        "rendered_source_chars_per_image": (
            rendered_source_chars / image_count if image_count > 0 else None
        ),
        "page_capacity_utilization": (
            rendered_source_chars / (image_count * theoretical_chars_per_image)
            if image_count > 0 and theoretical_chars_per_image > 0
            else None
        ),
        "chars_per_estimated_image_token": (
            compressed_chars / estimated_image_tokens
            if estimated_image_tokens > 0
            else None
        ),
        "chars_per_megapixel": (
            compressed_chars / (image_pixels / 1_000_000)
            if image_pixels > 0
            else None
        ),
        "unique_image_count": len(
            {
                sha
                for receipt in visual_receipts
                for sha in (receipt.get("image_sha256", []) or [])
            },
        ),
        "compression_calls": sum(
            bool(receipt.get("applied")) for receipt in visual_receipts
        ),
        "factsheet_entries": sum(
            int(x.get("factsheet_entries", 0) or 0) for x in visual_receipts
        ),
        "history_chunks": sum(
            int(x.get("history_chunks", 0) or 0) for x in visual_receipts
        ),
        "prefix_component_breaks": prefix_breaks,
        "history_sha_prefix_breaks": history_sha_breaks,
        "static_slab_sha_changes": static_slab_sha_changes,
        "factsheet_probe_matches": factsheet_probe_matches,
        "factsheet_probe_leak": bool(factsheet_probe_matches),
        "phase_metrics": phase_metrics,
        "call_diagnostics": call_diagnostics,
        "provider_input_includes_images": True,
        "provider_image_tokens": None,
        "provider_image_token_breakdown_available": False,
        "tool_or_agent_result": str(result.get("response", "")),
        "run_dir": str(run_dir.resolve()),
        "resume_reused": resume_reused,
    }


def _load_resume_rows(
    output_dir: Path,
    tasks: list[EvalTask],
    *,
    arms: list[str],
    max_iters: int,
    cost_config: CostConfig,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Re-score durable arm results and identify tasks needing a clean pair."""
    reusable: list[dict[str, Any]] = []
    invalid_tasks: set[str] = set()
    for task in tasks:
        task_rows: list[dict[str, Any]] = []
        for arm in arms:
            run_dir = output_dir / "runs" / task.id / arm
            result_path = run_dir / "result.json"
            if not result_path.is_file():
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                row = _result_row(
                    task,
                    arm,
                    result,
                    run_dir=run_dir,
                    effective_max_iters=_effective_max_iters(task, max_iters),
                    cost_config=cost_config,
                    resume_reused=True,
                )
            except (OSError, ValueError, json.JSONDecodeError):
                invalid_tasks.add(task.id)
                continue
            if row.get("status") != "success" or not row.get("quality_pass"):
                invalid_tasks.add(task.id)
            task_rows.append(row)
        if task.id not in invalid_tasks:
            reusable.extend(task_rows)
    return reusable, invalid_tasks


def _write_checkpoint(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rows": sorted(rows, key=lambda row: (row["task_id"], row["arm"])),
    }
    (output_dir / "checkpoint.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _activate_workspace_alias(workspace: Path, alias: Path | None) -> Path:
    """Point a stable model-visible path at one isolated run workspace."""
    if alias is None:
        return workspace
    alias.parent.mkdir(parents=True, exist_ok=True)
    if alias.is_symlink():
        alias.unlink()
    elif alias.exists():
        raise RuntimeError(
            f"workspace alias exists and is not a symlink: {alias}",
        )
    alias.symlink_to(workspace, target_is_directory=True)
    return alias


async def _run_pair(
    task: EvalTask,
    *,
    base_config: Any,
    model_slot: Any,
    output_dir: Path,
    workspace_alias: Path | None,
    timeout: int,
    provider_retries: bool,
    max_iters: int,
    arm_order: list[str],
    render_profile: str,
    render_variant: str,
    history_chunk_messages: int,
    min_block_chars: int,
    keep_recent_messages: int,
    max_visual_cost_ratio: float,
    pixels_per_token: float,
    chars_per_text_token: float,
    cost_config: CostConfig,
) -> list[dict[str, Any]]:
    from .task_cmd import _run_task

    rows: list[dict[str, Any]] = []
    for arm in arm_order:
        run_dir = output_dir / "runs" / task.id / arm
        if run_dir.exists():
            shutil.rmtree(run_dir)
        workspace = run_dir / "workspace"
        template = output_dir / "task_artifacts" / task.id
        if not template.is_dir():
            raise RuntimeError(f"missing preflight task artifact: {template}")
        shutil.copytree(template, workspace, dirs_exist_ok=True)
        active_workspace = _activate_workspace_alias(
            workspace,
            workspace_alias,
        )
        cfg = base_config.model_copy(deep=True)
        cfg.active_model = model_slot
        cfg.workspace_dir = str(active_workspace)
        effective_max_iters = _effective_max_iters(task, max_iters)
        cfg.running.max_iters = effective_max_iters
        cfg.running.llm_retry_enabled = provider_retries
        cfg.running.auto_title_config.enabled = False
        # Use the real workspace registry but expose only deterministic local
        # file operations. Both arms get identical schemas and no network or
        # cross-agent tools can pollute the paired measurement.
        if cfg.tools is None:
            from ..config.config import ToolsConfig

            cfg.tools = ToolsConfig()
        allowed_tools = _eval_allowed_tools(task)
        for name, tool_cfg in cfg.tools.builtin_tools.items():
            tool_cfg.enabled = name in allowed_tools
        lcc = cfg.running.light_context_config
        lcc.strategy = "native"
        lcc.context_compact_config.enabled = False
        if task.tool_result_max_bytes > 0:
            pruning = lcc.tool_result_pruning_config
            pruning.pruning_recent_n = 10
            pruning.pruning_old_msg_max_bytes = task.tool_result_max_bytes
            pruning.pruning_recent_msg_max_bytes = task.tool_result_max_bytes
        visual = lcc.visual_compression_config
        # Keep the model/tool surface identical across paired arms. The arm
        # flag alone controls transformation; enabled stays true so both arms
        # expose the same recovery tool schema.
        visual.enabled = True
        visual.experiment_arm = arm
        visual.emit_factsheet = arm != "on_nofactsheet"
        visual.record_factsheet_text = True
        visual.allowed_models = [model_slot.model]
        visual.receipt_dir = str(run_dir / "receipts")
        visual.render_profile = render_profile
        visual.render_variant = render_variant
        visual.history_chunk_messages = history_chunk_messages
        visual.min_block_chars = min_block_chars
        visual.min_static_tokens = 500
        visual.history_collapse_grid_messages = 50
        visual.max_images_per_request = 64
        visual.max_images_per_tool_result = 10
        visual.factsheet_limit = 96
        visual.keep_recent_messages = keep_recent_messages
        visual.max_visual_cost_ratio = max_visual_cost_ratio
        visual.pixels_per_token = pixels_per_token
        visual.chars_per_text_token = chars_per_text_token
        _apply_task_visual_profile(task, visual)
        cfg.coding_mode.enabled = False
        cfg.coding_mode.project_dir = None
        session_id = f"vceval-{task.id}-{arm}"
        result = await _run_task(
            instruction=task.instruction,
            agent_config=cfg,
            request_context={
                "session_id": session_id,
                "user_id": "visual-compression-eval",
                "channel": "console",
                "agent_id": cfg.id,
                "_headless_tool_guard": "false",
            },
            max_iters=effective_max_iters,
            timeout=timeout,
            output_dir=str(run_dir),
            seed_context=task.seed_context,
            scripted_turns=list(task.scripted_turns),
        )
        rows.append(
            _result_row(
                task,
                arm,
                result,
                run_dir=run_dir,
                effective_max_iters=effective_max_iters,
                cost_config=cost_config,
            ),
        )
    return rows


def _bootstrap_ci(values: list[float], seed: int = 36) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(2000):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [means[49], means[1949]]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _arm_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accuracies = [
        float(row["accuracy_score"])
        for row in rows
        if row.get("accuracy_score") is not None
    ]
    elapsed = sum(float(row.get("elapsed_seconds", 0) or 0) for row in rows)
    provider = sum(
        float(row.get("provider_time_seconds", 0) or 0) for row in rows
    )
    compressed_chars = sum(
        int(row.get("compressed_chars", 0) or 0) for row in rows
    )
    rendered_source_chars = sum(
        int(row.get("rendered_source_chars", 0) or 0) for row in rows
    )
    image_inputs = sum(int(row.get("image_count", 0) or 0) for row in rows)
    image_pixels = sum(int(row.get("image_pixels", 0) or 0) for row in rows)
    image_bytes = sum(int(row.get("image_bytes", 0) or 0) for row in rows)
    estimated_image_tokens = sum(
        int(row.get("estimated_image_tokens", 0) or 0) for row in rows
    )
    return {
        "runs": len(rows),
        "successes": sum(row.get("status") == "success" for row in rows),
        "quality_passes": sum(bool(row.get("quality_pass")) for row in rows),
        "format_passes": sum(bool(row.get("format_pass")) for row in rows),
        "completion_mean": _mean(
            [float(row.get("completion_score", 0) or 0) for row in rows],
        ),
        "accuracy_mean": _mean(accuracies),
        "input_tokens": sum(
            int(row.get("input_tokens", 0) or 0) for row in rows
        ),
        "output_tokens": sum(
            int(row.get("output_tokens", 0) or 0) for row in rows
        ),
        "output_chars": sum(
            int(row.get("output_chars", 0) or 0) for row in rows
        ),
        "output_text_chars": sum(
            int(row.get("output_text_chars", 0) or 0) for row in rows
        ),
        "output_tool_use_chars": sum(
            int(row.get("output_tool_use_chars", 0) or 0) for row in rows
        ),
        "output_thinking_chars": sum(
            int(row.get("output_thinking_chars", 0) or 0) for row in rows
        ),
        "cache_read_tokens": sum(
            int(row.get("cache_input_tokens", 0) or 0) for row in rows
        ),
        "cache_creation_tokens": sum(
            int(row.get("cache_creation_input_tokens", 0) or 0) for row in rows
        ),
        "cache_zero_calls": sum(
            int(row.get("cache_zero_calls", 0) or 0) for row in rows
        ),
        "weighted_token_units": sum(
            float(row.get("weighted_token_units", 0) or 0) for row in rows
        ),
        "cache_adjusted_weighted_token_units": sum(
            float(row.get("cache_adjusted_weighted_token_units", 0) or 0)
            for row in rows
        ),
        "estimated_cost_usd": (
            sum(float(row.get("estimated_cost_usd", 0) or 0) for row in rows)
            if rows
            and all(row.get("estimated_cost_usd") is not None for row in rows)
            else None
        ),
        "llm_calls": sum(int(row.get("llm_calls", 0) or 0) for row in rows),
        "raw_llm_attempts": sum(
            int(row.get("raw_llm_attempts", 0) or 0) for row in rows
        ),
        "failed_llm_attempts": sum(
            int(row.get("failed_llm_attempts", 0) or 0) for row in rows
        ),
        "agent_iterations": sum(
            int(row.get("agent_iterations", 0) or 0) for row in rows
        ),
        "tool_calls": sum(int(row.get("tool_calls", 0) or 0) for row in rows),
        "recovery_calls": sum(
            int(row.get("recovery_calls", 0) or 0) for row in rows
        ),
        "elapsed_seconds": elapsed,
        "raw_elapsed_seconds": sum(
            float(row.get("raw_elapsed_seconds", 0) or 0) for row in rows
        ),
        "excluded_retry_seconds": sum(
            float(row.get("excluded_retry_seconds", 0) or 0) for row in rows
        ),
        "provider_time_seconds": provider,
        "ttft_seconds": sum(
            float(row.get("ttft_seconds", 0) or 0) for row in rows
        ),
        "non_provider_overhead_seconds": max(0.0, elapsed - provider),
        "compressed_chars": compressed_chars,
        "rendered_source_chars": rendered_source_chars,
        "image_inputs": image_inputs,
        "image_pixels": image_pixels,
        "image_bytes": image_bytes,
        "chars_per_image": (
            compressed_chars / image_inputs if image_inputs > 0 else None
        ),
        "rendered_source_chars_per_image": (
            rendered_source_chars / image_inputs if image_inputs > 0 else None
        ),
        "chars_per_estimated_image_token": (
            compressed_chars / estimated_image_tokens
            if estimated_image_tokens > 0
            else None
        ),
        "chars_per_megapixel": (
            compressed_chars / (image_pixels / 1_000_000)
            if image_pixels > 0
            else None
        ),
        "unique_images": sum(
            int(row.get("unique_image_count", 0) or 0) for row in rows
        ),
        "estimated_image_tokens": estimated_image_tokens,
        "transform_ms": sum(
            float(row.get("transform_ms", 0) or 0) for row in rows
        ),
        "factsheet_entries": sum(
            int(row.get("factsheet_entries", 0) or 0) for row in rows
        ),
        "history_chunks": sum(
            int(row.get("history_chunks", 0) or 0) for row in rows
        ),
        "prefix_component_breaks": sum(
            int(row.get("prefix_component_breaks", 0) or 0) for row in rows
        ),
        "history_sha_prefix_breaks": sum(
            int(row.get("history_sha_prefix_breaks", 0) or 0) for row in rows
        ),
        "static_slab_sha_changes": sum(
            int(row.get("static_slab_sha_changes", 0) or 0) for row in rows
        ),
        "factsheet_probe_leaks": sum(
            bool(row.get("factsheet_probe_leak")) for row in rows
        ),
        "network_timing_anomalies": sum(
            bool(row.get("network_timing_anomaly")) for row in rows
        ),
    }


def _group_aggregates(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = sorted({str(row.get(key, "unknown")) for row in rows})
    arms = sorted({str(row.get("arm")) for row in rows})
    return {
        value: {
            arm: _arm_aggregate(
                [
                    row
                    for row in rows
                    if str(row.get(key, "unknown")) == value
                    and row.get("arm") == arm
                ],
            )
            for arm in arms
        }
        for value in values
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(row["task_id"], row["arm"]): row for row in rows}
    task_ids = sorted({row["task_id"] for row in rows})
    pairs = []
    token_deltas: list[float] = []
    time_deltas: list[float] = []
    for task_id in task_ids:
        off = by_key.get((task_id, "off"))
        on = by_key.get((task_id, "on"))
        if not off or not on:
            continue
        token_saving = (
            1 - on["input_tokens"] / off["input_tokens"]
            if off["input_tokens"] > 0
            else 0.0
        )
        time_saving = (
            1 - on["elapsed_seconds"] / off["elapsed_seconds"]
            if off["elapsed_seconds"] > 0
            else 0.0
        )
        token_deltas.append(token_saving)
        time_deltas.append(time_saving)
        pairs.append(
            {
                "task_id": task_id,
                "difficulty": off.get("difficulty", "short"),
                "token_saving_ratio": token_saving,
                "time_saving_ratio": time_saving,
                "quality_off": off["quality_pass"],
                "quality_on": on["quality_pass"],
                "format_off": off.get("format_pass", False),
                "format_on": on.get("format_pass", False),
                "completion_off": off.get("completion_score"),
                "completion_on": on.get("completion_score"),
                "accuracy_off": off.get("accuracy_score"),
                "accuracy_on": on.get("accuracy_score"),
                "llm_calls_off": off.get("llm_calls", 0),
                "llm_calls_on": on.get("llm_calls", 0),
                "agent_iterations_off": off.get("agent_iterations", 0),
                "agent_iterations_on": on.get("agent_iterations", 0),
                "tool_calls_off": off.get("tool_calls", 0),
                "tool_calls_on": on.get("tool_calls", 0),
                "recovery_calls_off": off.get("recovery_calls", 0),
                "recovery_calls_on": on.get("recovery_calls", 0),
            },
        )
    off_rows = [row for row in rows if row["arm"] == "off"]
    on_rows = [row for row in rows if row["arm"] == "on"]
    nofactsheet_rows = [row for row in rows if row["arm"] == "on_nofactsheet"]
    phase_pairs: list[dict[str, Any]] = []
    for task_id in task_ids:
        off_row = by_key.get((task_id, "off"))
        on_row = by_key.get((task_id, "on"))
        if not off_row or not on_row:
            continue
        off_phases = {
            str(item["phase_id"]): item
            for item in off_row.get("phase_metrics", []) or []
        }
        on_phases = {
            str(item["phase_id"]): item
            for item in on_row.get("phase_metrics", []) or []
        }
        for phase_id in sorted(
            off_phases.keys() & on_phases.keys(),
            key=lambda value: int(off_phases[value].get("phase_index", 0)),
        ):
            off_phase = off_phases[phase_id]
            on_phase = on_phases[phase_id]
            off_input = int(off_phase.get("input_tokens", 0) or 0)
            on_input = int(on_phase.get("input_tokens", 0) or 0)
            off_cache_adjusted = float(
                off_phase.get("cache_adjusted_weighted_token_units", 0) or 0,
            )
            on_cache_adjusted = float(
                on_phase.get("cache_adjusted_weighted_token_units", 0) or 0,
            )
            phase_pairs.append(
                {
                    "task_id": task_id,
                    "phase_id": phase_id,
                    "quality_off": off_phase.get("quality_pass"),
                    "quality_on": on_phase.get("quality_pass"),
                    "input_tokens_off": off_input,
                    "input_tokens_on": on_input,
                    "input_saving_ratio": (
                        1 - on_input / off_input if off_input > 0 else None
                    ),
                    "cache_adjusted_units_off": off_cache_adjusted,
                    "cache_adjusted_units_on": on_cache_adjusted,
                    "cache_adjusted_saving_ratio": (
                        1 - on_cache_adjusted / off_cache_adjusted
                        if off_cache_adjusted > 0
                        else None
                    ),
                    "output_tokens_off": int(
                        off_phase.get("output_tokens", 0) or 0,
                    ),
                    "output_tokens_on": int(
                        on_phase.get("output_tokens", 0) or 0,
                    ),
                    "cache_read_off": int(
                        off_phase.get("cache_input_tokens", 0) or 0,
                    ),
                    "cache_read_on": int(
                        on_phase.get("cache_input_tokens", 0) or 0,
                    ),
                    "cache_creation_off": int(
                        off_phase.get("cache_creation_input_tokens", 0) or 0,
                    ),
                    "cache_creation_on": int(
                        on_phase.get("cache_creation_input_tokens", 0) or 0,
                    ),
                    "elapsed_off": float(
                        off_phase.get("elapsed_seconds", 0) or 0,
                    ),
                    "elapsed_on": float(
                        on_phase.get("elapsed_seconds", 0) or 0,
                    ),
                    "llm_calls_off": int(off_phase.get("llm_calls", 0) or 0),
                    "llm_calls_on": int(on_phase.get("llm_calls", 0) or 0),
                    "factsheet_probe_matches_on": list(
                        on_phase.get("factsheet_probe_matches", []) or [],
                    ),
                },
            )
    off_tokens = sum(row["input_tokens"] for row in off_rows)
    on_tokens = sum(row["input_tokens"] for row in on_rows)
    off_time = sum(float(row["elapsed_seconds"]) for row in off_rows)
    on_time = sum(float(row["elapsed_seconds"]) for row in on_rows)
    off_quality = sum(bool(row["quality_pass"]) for row in off_rows)
    on_quality = sum(bool(row["quality_pass"]) for row in on_rows)
    token_saving = 1 - on_tokens / off_tokens if off_tokens > 0 else 0.0
    time_saving = 1 - on_time / off_time if off_time > 0 else 0.0
    quality_delta = (
        on_quality / len(on_rows) - off_quality / len(off_rows)
        if on_rows and off_rows
        else 0.0
    )
    all_runs_successful = bool(rows) and all(
        row.get("status") == "success" for row in rows
    )
    all_quality_passed = bool(rows) and all(
        bool(row.get("quality_pass")) for row in rows
    )
    review_pending = any(bool(row.get("review_required")) for row in rows)
    comparison_available = bool(off_rows and on_rows)
    visual_rows = [*on_rows, *nofactsheet_rows]
    compression_exercised = bool(visual_rows) and all(
        row.get("arm") in {"on", "on_nofactsheet"}
        and int(row.get("compressed_chars", 0) or 0) > 0
        and int(row.get("image_count", 0) or 0) > 0
        for row in on_rows
    )
    valid_experiment = (
        comparison_available
        and all_runs_successful
        and all_quality_passed
        and compression_exercised
        and not review_pending
    )
    arm_totals = {
        "off": _arm_aggregate(off_rows),
        "on": _arm_aggregate(on_rows),
    }
    if nofactsheet_rows:
        arm_totals["on_nofactsheet"] = _arm_aggregate(nofactsheet_rows)
    off_weighted = float(arm_totals["off"]["weighted_token_units"] or 0)
    on_weighted = float(arm_totals["on"]["weighted_token_units"] or 0)
    off_cache_adjusted = float(
        arm_totals["off"]["cache_adjusted_weighted_token_units"] or 0,
    )
    on_cache_adjusted = float(
        arm_totals["on"]["cache_adjusted_weighted_token_units"] or 0,
    )
    return {
        "tasks": len(task_ids),
        "runs": len(rows),
        "off_quality": off_quality,
        "on_quality": on_quality,
        "off_input_tokens": off_tokens,
        "on_input_tokens": on_tokens,
        "input_token_saving_ratio": token_saving,
        "elapsed_time_saving_ratio": time_saving,
        "quality_rate_delta": quality_delta,
        "weighted_token_saving_ratio": (
            1 - on_weighted / off_weighted if off_weighted > 0 else 0.0
        ),
        "cache_adjusted_weighted_token_saving_ratio": (
            1 - on_cache_adjusted / off_cache_adjusted
            if off_cache_adjusted > 0
            else 0.0
        ),
        "arm_totals": arm_totals,
        "by_difficulty": _group_aggregates(rows, "difficulty"),
        "by_category": _group_aggregates(rows, "category"),
        "acceptance": {
            "comparison_available": comparison_available,
            "all_runs_successful": all_runs_successful,
            "all_quality_passed": all_quality_passed,
            "compression_exercised": compression_exercised,
            "review_pending": review_pending,
            "valid_experiment": valid_experiment,
            "quality_noninferior": (
                all_runs_successful
                and bool(off_rows)
                and off_quality > 0
                and quality_delta >= -0.05
            ),
            "token_reduction_at_least_20pct": (
                valid_experiment and token_saving >= 0.20
            ),
            "latency_improved": valid_experiment and time_saving > 0,
            "may_claim_token_improvement": (
                valid_experiment
                and quality_delta >= -0.05
                and token_saving >= 0.20
            ),
            "may_claim_latency_improvement": (
                valid_experiment
                and quality_delta >= -0.05
                and token_saving >= 0.20
                and time_saving > 0
            ),
        },
        "paired_token_saving_ci95": _bootstrap_ci(token_deltas),
        "paired_time_saving_ci95": _bootstrap_ci(time_deltas),
        "pairs": pairs,
        "phase_pairs": phase_pairs,
    }


def _has_run_failures(
    rows: list[dict[str, Any]],
    acceptance: dict[str, Any],
    requested_arms: list[str],
) -> bool:
    """Single-arm OFF is a valid data-collection run, not an A/B failure."""
    return bool(
        any(row.get("status") != "success" for row in rows)
        or not acceptance.get("all_quality_passed", False)
        or (
            bool({"on", "on_nofactsheet"}.intersection(requested_arms))
            and not acceptance.get("compression_exercised", False)
        ),
    )


def _write_report(output_dir: Path, payload: dict[str, Any]) -> None:
    (output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = payload.get("summary", {})
    rows = payload.get("rows", []) or []
    csv_fields = [
        "task_id",
        "category",
        "difficulty",
        "arm",
        "render_variant",
        "status",
        "quality_pass",
        "format_pass",
        "completion_score",
        "accuracy_score",
        "effective_max_iters",
        "seed_context_turns",
        "seed_context_chars",
        "llm_calls",
        "raw_llm_attempts",
        "failed_llm_attempts",
        "agent_iterations",
        "tool_calls",
        "recovery_calls",
        "input_tokens",
        "provider_input_tokens",
        "output_tokens",
        "output_chars",
        "output_text_chars",
        "output_tool_use_chars",
        "output_thinking_chars",
        "chars_per_output_token",
        "cache_input_tokens",
        "cache_creation_input_tokens",
        "cache_zero_calls",
        "cache_rate_mean",
        "weighted_token_units",
        "cache_adjusted_weighted_token_units",
        "estimated_cost_usd",
        "elapsed_seconds",
        "raw_elapsed_seconds",
        "excluded_retry_seconds",
        "provider_time_seconds",
        "ttft_seconds",
        "compressed_chars",
        "image_count",
        "image_pixels",
        "image_bytes",
        "rendered_source_chars",
        "theoretical_ascii_chars_per_image",
        "chars_per_image",
        "rendered_source_chars_per_image",
        "page_capacity_utilization",
        "chars_per_estimated_image_token",
        "chars_per_megapixel",
        "unique_image_count",
        "estimated_image_tokens",
        "gate_text_tokens",
        "gate_visual_tokens",
        "gate_candidates",
        "gate_accepted",
        "transform_ms",
        "factsheet_entries",
        "history_chunks",
        "prefix_component_breaks",
        "history_sha_prefix_breaks",
        "static_slab_sha_changes",
        "factsheet_probe_leak",
        "network_timing_anomaly",
        "unattributed_wait_seconds",
        "resume_reused",
        "run_dir",
    ]
    with (output_dir / "results.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=csv_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    review_queue = [
        {
            "task_id": row.get("task_id"),
            "arm": row.get("arm"),
            "artifact_paths": row.get("artifact_paths", []),
            "completion_score": row.get("completion_score"),
            "verification": row.get("verification", {}),
            "run_dir": row.get("run_dir"),
        }
        for row in rows
        if row.get("review_required")
    ]
    (output_dir / "review_queue.json").write_text(
        json.dumps(review_queue, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run_artifacts = []
    for row in rows:
        run_dir = Path(str(row.get("run_dir", "")))
        images = sorted(
            str(path.resolve())
            for path in (run_dir / "receipts" / "images").glob("*.png")
        )
        run_artifacts.append(
            {
                "task_id": row.get("task_id"),
                "arm": row.get("arm"),
                "run_dir": str(run_dir.resolve()),
                "workspace": str((run_dir / "workspace").resolve()),
                "result": str((run_dir / "result.json").resolve()),
                "generated_artifacts": row.get("artifact_paths", []),
                "rendered_images": images,
            },
        )
    artifact_index = {
        "evaluation_root": str(output_dir.resolve()),
        "task_snapshot": str((output_dir / "task.snapshot.json").resolve()),
        "task_artifacts": str((output_dir / "task_artifacts").resolve()),
        "preflight": str((output_dir / "preflight.json").resolve()),
        "manifest": str((output_dir / "manifest.json").resolve()),
        "results_json": str((output_dir / "results.json").resolve()),
        "results_csv": str((output_dir / "results.csv").resolve()),
        "report": str((output_dir / "report.md").resolve()),
        "review_queue": str((output_dir / "review_queue.json").resolve()),
        "runs": run_artifacts,
    }
    (output_dir / "artifact_index.json").write_text(
        json.dumps(artifact_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    arm_totals = summary.get("arm_totals", {})
    off = arm_totals.get("off", {})
    on = arm_totals.get("on", {})
    nofactsheet = arm_totals.get("on_nofactsheet", {})
    lines = [
        "# Agentic visual compression A/B report",
        "",
        f"- Model: `{payload.get('model')}`",
        f"- Suite: `{payload.get('suite')}`",
        f"- Tasks: {summary.get('tasks', 0)}; runs: {summary.get('runs', 0)}",
        "- Quality OFF/ON: "
        f"{summary.get('off_quality', 0)}/{summary.get('on_quality', 0)}",
        "- Strict format passes OFF/ON: "
        f"{off.get('format_passes', 0)}/{on.get('format_passes', 0)}",
        (
            "- Provider input tokens OFF/ON: "
            f"{summary.get('off_input_tokens', 0):,}/"
            f"{summary.get('on_input_tokens', 0):,}"
        ),
        f"- Output tokens OFF/ON: {off.get('output_tokens', 0):,}/"
        f"{on.get('output_tokens', 0):,}",
        f"- Measured output chars OFF/ON: {off.get('output_chars', 0):,}/"
        f"{on.get('output_chars', 0):,}",
        f"- Cache-read tokens OFF/ON: {off.get('cache_read_tokens', 0):,}/"
        f"{on.get('cache_read_tokens', 0):,}",
        f"- Cached-token-zero calls OFF/ON: {off.get('cache_zero_calls', 0)}/"
        f"{on.get('cache_zero_calls', 0)}",
        "- Cache-creation tokens OFF/ON: "
        f"{off.get('cache_creation_tokens', 0):,}/"
        f"{on.get('cache_creation_tokens', 0):,}",
        "- Cache policy: observed and reported, but excluded from headline "
        "weighted units, acceptance, and benefit claims.",
        "- Weighted token units OFF/ON: "
        f"{float(off.get('weighted_token_units') or 0):,.1f}/"
        f"{float(on.get('weighted_token_units') or 0):,.1f}",
        "- Cache-adjusted weighted units OFF/ON (diagnostic only): "
        f"{float(off.get('cache_adjusted_weighted_token_units') or 0):,.1f}/"
        f"{float(on.get('cache_adjusted_weighted_token_units') or 0):,.1f}",
        "- Input-token saving: "
        f"{summary.get('input_token_saving_ratio', 0):.1%}",
        "- Weighted-token saving: "
        f"{summary.get('weighted_token_saving_ratio', 0):.1%}",
        "- Cache-adjusted weighted saving (diagnostic only): "
        f"{summary.get('cache_adjusted_weighted_token_saving_ratio', 0):.1%}",
        "- Elapsed-time saving: "
        f"{summary.get('elapsed_time_saving_ratio', 0):.1%}",
        "- Completion mean OFF/ON: "
        f"{float(off.get('completion_mean') or 0):.1%}/"
        f"{float(on.get('completion_mean') or 0):.1%}",
        "- Accuracy mean OFF/ON: "
        f"{float(off.get('accuracy_mean') or 0):.1%}/"
        f"{float(on.get('accuracy_mean') or 0):.1%}",
        (
            "- LLM calls OFF/ON: "
            f"{off.get('llm_calls', 0)}/{on.get('llm_calls', 0)}"
        ),
        "- Failed infrastructure attempts OFF/ON (excluded): "
        f"{off.get('failed_llm_attempts', 0)}/"
        f"{on.get('failed_llm_attempts', 0)}",
        "- Excluded retry time OFF/ON: "
        f"{float(off.get('excluded_retry_seconds') or 0):.2f}s/"
        f"{float(on.get('excluded_retry_seconds') or 0):.2f}s",
        "- Agent iterations OFF/ON: "
        f"{off.get('agent_iterations', 0)}/{on.get('agent_iterations', 0)}",
        (
            "- Tool calls OFF/ON: "
            f"{off.get('tool_calls', 0)}/{on.get('tool_calls', 0)}"
        ),
        "- Recovery calls OFF/ON: "
        f"{off.get('recovery_calls', 0)}/{on.get('recovery_calls', 0)}",
        "- Prefix component breaks OFF/ON: "
        f"{off.get('prefix_component_breaks', 0)}/"
        f"{on.get('prefix_component_breaks', 0)}",
        "- History SHA prefix breaks OFF/ON: "
        f"{off.get('history_sha_prefix_breaks', 0)}/"
        f"{on.get('history_sha_prefix_breaks', 0)}",
        "- Factsheet answer-probe leaks OFF/ON: "
        f"{off.get('factsheet_probe_leaks', 0)}/"
        f"{on.get('factsheet_probe_leaks', 0)}",
        "- Provider time OFF/ON: "
        f"{float(off.get('provider_time_seconds') or 0):.2f}s/"
        f"{float(on.get('provider_time_seconds') or 0):.2f}s",
        "- Estimated USD OFF/ON: "
        f"{off.get('estimated_cost_usd')}/{on.get('estimated_cost_usd')}",
        "- Acceptance: "
        f"`{json.dumps(summary.get('acceptance', {}), sort_keys=True)}`",
        (
            "- Artifact index: `"
            f"{(output_dir / 'artifact_index.json').resolve()}`"
        ),
        (
            "- Human review queue: `"
            f"{(output_dir / 'review_queue.json').resolve()}`"
        ),
        *(
            [
                "- ON-no-factsheet: "
                f"runs={nofactsheet.get('runs', 0)}, "
                f"quality={nofactsheet.get('quality_passes', 0)}, "
                f"input={nofactsheet.get('input_tokens', 0):,}, "
                f"output={nofactsheet.get('output_tokens', 0):,}",
            ]
            if nofactsheet
            else []
        ),
        "",
        "| task | horizon | quality O/N | completion O/N | accuracy O/N | "
        "LLM calls O/N | iterations O/N | token saving | time saving |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pair in summary.get("pairs", []):
        acc_off = pair.get("accuracy_off")
        acc_on = pair.get("accuracy_on")
        lines.append(
            f"| {pair['task_id']} | {pair.get('difficulty')} | "
            f"{int(pair['quality_off'])}/{int(pair['quality_on'])} | "
            f"{float(pair.get('completion_off') or 0):.0%}/"
            f"{float(pair.get('completion_on') or 0):.0%} | "
            f"{('-' if acc_off is None else f'{float(acc_off):.0%}')}/"
            f"{('-' if acc_on is None else f'{float(acc_on):.0%}')} | "
            f"{pair.get('llm_calls_off', 0)}/{pair.get('llm_calls_on', 0)} | "
            f"{pair.get('agent_iterations_off', 0)}/"
            f"{pair.get('agent_iterations_on', 0)} | "
            f"{pair['token_saving_ratio']:.1%} | "
            f"{pair['time_saving_ratio']:.1%} |",
        )
    if summary.get("phase_pairs"):
        lines.extend(
            [
                "",
                "| phase | quality O/N | input O/N | input saving | "
                "cache-adjusted O/N | cache-adjusted saving | output O/N | "
                "cache-read O/N | calls O/N |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ],
        )
        for phase in summary["phase_pairs"]:
            input_saving = phase.get("input_saving_ratio")
            cache_saving = phase.get("cache_adjusted_saving_ratio")
            lines.append(
                f"| {phase['phase_id']} | "
                f"{int(bool(phase.get('quality_off')))}/"
                f"{int(bool(phase.get('quality_on')))} | "
                f"{phase['input_tokens_off']:,}/"
                f"{phase['input_tokens_on']:,} | "
                f"{('-' if input_saving is None else f'{input_saving:.1%}')} "
                "| "
                f"{phase['cache_adjusted_units_off']:,.1f}/"
                f"{phase['cache_adjusted_units_on']:,.1f} | "
                f"{('-' if cache_saving is None else f'{cache_saving:.1%}')} "
                "| "
                f"{phase['output_tokens_off']:,}/"
                f"{phase['output_tokens_on']:,} | "
                f"{phase['cache_read_off']:,}/{phase['cache_read_on']:,} | "
                f"{phase['llm_calls_off']}/{phase['llm_calls_on']} |",
            )
    lines.extend(
        [
            "",
            "Latency improvement must only be claimed when the paired result "
            "is positive; token estimates are diagnostic, while this report's "
            "headline uses provider-reported usage from both real arms.",
            "Provider input_tokens already include multimodal/image input as "
            "reported by the endpoint. DashScope exposes no separate image "
            "token breakdown; gate_visual_tokens/estimated_image_tokens are "
            "pre-request diagnostics only and never enter cost or acceptance.",
            "Open-ended tasks remain review_pending until their artifacts are "
            "reviewed from review_queue.json; they block final improvement "
            "claims even when structural checks pass.",
        ],
    )
    (output_dir / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


@click.group("visual-compression")
def visual_compression_group() -> None:
    """Experiment with request-time visual context compression."""


@visual_compression_group.command("eval")
@click.option(
    "--model",
    default=None,
    help="Target as <provider>/<model-id>; defaults to the agent model.",
)
@click.option(
    "--suite",
    default="benchmark-v2",
    type=click.Choice(["agentic-v1", "benchmark-v2"]),
    show_default=True,
)
@click.option(
    "--task-file",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="benchmark-v2 task.json; defaults to the repository benchmark file.",
)
@click.option("--arms", default="off,on", show_default=True)
@click.option(
    "--arm-order-seed",
    default=36,
    type=int,
    show_default=True,
    help="Deterministic per-repeat seed for within-task arm interleaving.",
)
@click.option("--confirm", is_flag=True, help="Allow real model calls.")
@click.option(
    "--fail-fast/--no-fail-fast",
    default=True,
    show_default=True,
    help="Stop after the first task pair with a semantic/contract failure.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Defaults to <agent-workspace>/visual_compression/evals/<timestamp>.",
)
@click.option(
    "--workspace-alias",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help=(
        "Stable logical workspace symlink used in model-visible context while "
        "artifacts remain isolated under --output-dir."
    ),
)
@click.option("--agent-id", default="default", show_default=True)
@click.option("--timeout", default=900, type=int, show_default=True)
@click.option(
    "--provider-retries/--no-provider-retries",
    default=True,
    show_default=True,
    help=(
        "Retry transient provider failures; v3 disables this for clean "
        "timing."
    ),
)
@click.option(
    "--max-iters",
    default=0,
    type=click.IntRange(min=0),
    show_default=True,
    help=(
        "Positive value is a suite-wide safety ceiling; 0 uses each task "
        "limit (or 30 when absent). It never raises a task's declared limit."
    ),
)
@click.option(
    "--limit",
    default=0,
    type=int,
    help="Limit task count; 0 means all.",
)
@click.option(
    "--task-id",
    "task_ids",
    multiple=True,
    help="Repeat to select exact task ids for a fresh/subset evaluation.",
)
@click.option(
    "--horizon",
    "horizons",
    multiple=True,
    type=click.Choice(["short", "medium", "long"]),
    help="Repeat to select horizons; defaults to all.",
)
@click.option(
    "--exclude-review-tasks",
    is_flag=True,
    help="Skip open-ended tasks that require post-run human review.",
)
@click.option(
    "--resume",
    is_flag=True,
    help=(
        "Resume an existing --output-dir: reuse re-verified successful arms, "
        "rerun both arms of failed tasks, and run only missing arms."
    ),
)
@click.option("--input-weight", default=1.0, type=float, show_default=True)
@click.option("--output-weight", default=4.0, type=float, show_default=True)
@click.option(
    "--cache-read-weight",
    default=0.1,
    type=float,
    show_default=True,
)
@click.option(
    "--cache-creation-weight",
    default=1.25,
    type=float,
    show_default=True,
)
@click.option("--input-price-per-million", default=None, type=float)
@click.option("--output-price-per-million", default=None, type=float)
@click.option("--cache-read-price-per-million", default=None, type=float)
@click.option("--cache-creation-price-per-million", default=None, type=float)
@click.option(
    "--history-chunk-messages",
    default=10,
    type=click.IntRange(min=2, max=50),
    show_default=True,
    help="Message-grid width for accumulated-history visual chunks.",
)
@click.option(
    "--benchmark-visual-profile",
    default="task_default",
    type=click.Choice(
        [
            "task_default",
            "joint_v1",
            "fixed_grid_v1",
        ],
    ),
    show_default=True,
    help=(
        "Evaluation-only region policy. joint_v1 enables every region; "
        "fixed_grid_v1 pins the single selected history baseline. Every "
        "resolved policy is recorded."
    ),
)
@click.option(
    "--benchmark-max-images-per-request",
    default=0,
    type=click.IntRange(min=0, max=100),
    show_default=True,
    help="Evaluation-only global image cap; 0 keeps the task/profile default.",
)
@click.option(
    "--min-block-chars",
    default=4000,
    type=click.IntRange(min=256),
    show_default=True,
    help="Benchmark compression candidate size floor.",
)
@click.option(
    "--keep-recent-messages",
    default=6,
    type=click.IntRange(min=1, max=100),
    show_default=True,
    help="Recent messages kept as native text during benchmark runs.",
)
@click.option(
    "--max-visual-cost-ratio",
    default=0.90,
    type=click.FloatRange(min=0.5, max=2.0),
    show_default=True,
    help="Allow estimated visual input cost up to this multiple of text cost.",
)
@click.option(
    "--pixels-per-token",
    default=750.0,
    type=click.FloatRange(min=1.0),
    show_default=True,
    help="Qwen visual-token planning divisor used by the profitability gate.",
)
@click.option(
    "--chars-per-text-token",
    default=4.0,
    type=click.FloatRange(min=1.0, max=8.0),
    show_default=True,
    help="Fallback only; the gate normally uses the bundled Qwen tokenizer.",
)
@click.option(
    "--render-profile",
    default="calibrated",
    type=click.Choice(["calibrated", "5x8", "7x10", "9x12"]),
    show_default=True,
)
@click.option(
    "--render-variant",
    default="v0_pxpipe",
    type=click.Choice(
        [
            "v0_pxpipe",
            "v1_dark",
            "v2_square",
            "v3_jbmono10",
            "v4_preserve_newlines",
            "density_640x384_5x8",
            "density_768x512_5x8",
            "density_960x512_5x8",
            "density_1280x640_5x8",
            "density_1568x728_5x8",
            "density_1920x896_5x8",
            "density_1568x728_jbmono10",
            "density_1568x728_jbmono12",
            "format_light_regular",
            "format_dark_regular",
            "format_light_bold",
            "format_dark_bold",
            "format_dark_amber",
            "format_light_blue",
        ],
    ),
    show_default=True,
    help="Controlled image-rendering ablation recorded in every manifest.",
)
def eval_command(
    model: str | None,
    suite: str,
    task_file: Path | None,
    arms: str,
    arm_order_seed: int,
    confirm: bool,
    fail_fast: bool,
    output_dir: str | None,
    workspace_alias: Path | None,
    agent_id: str,
    timeout: int,
    provider_retries: bool,
    max_iters: int,
    limit: int,
    task_ids: tuple[str, ...],
    horizons: tuple[str, ...],
    exclude_review_tasks: bool,
    resume: bool,
    input_weight: float,
    output_weight: float,
    cache_read_weight: float,
    cache_creation_weight: float,
    input_price_per_million: float | None,
    output_price_per_million: float | None,
    cache_read_price_per_million: float | None,
    cache_creation_price_per_million: float | None,
    history_chunk_messages: int,
    min_block_chars: int,
    keep_recent_messages: int,
    max_visual_cost_ratio: float,
    pixels_per_token: float,
    chars_per_text_token: float,
    render_profile: str,
    render_variant: str,
    benchmark_visual_profile: str,
    benchmark_max_images_per_request: int,
) -> None:
    """Run or dry-run the reproducible OFF/ON agent task suite."""
    from ..config.config import load_agent_config

    cfg = load_agent_config(agent_id)
    if model:
        slot = _model_slot(model)
    else:
        slot = cfg.active_model
        if not slot or not slot.provider_id or not slot.model:
            raise click.ClickException(
                f"agent {agent_id!r} has no active model; pass --model",
            )
        model = f"{slot.provider_id}/{slot.model}"
    arm_list = [
        item.strip().lower() for item in arms.split(",") if item.strip()
    ]
    if (
        not arm_list
        or len(arm_list) != len(set(arm_list))
        or not set(arm_list).issubset({"off", "on", "on_nofactsheet"})
    ):
        raise click.ClickException(
            "--arms must use off, on, and/or on_nofactsheet without "
            "duplicates",
        )
    if resume and not output_dir:
        raise click.ClickException(
            "--resume requires an existing --output-dir",
        )
    if resume and (limit > 0 or horizons or task_ids or exclude_review_tasks):
        raise click.ClickException(
            "--resume restores the original task selection; do not combine it "
            "with --limit, --horizon, --task-id, or --exclude-review-tasks",
        )
    if output_dir:
        out = Path(output_dir).expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = (
            Path(cfg.workspace_dir).expanduser()
            / "visual_compression"
            / "evals"
            / stamp
        ).resolve()
    if resume and not out.is_dir():
        raise click.ClickException(
            f"resume output directory does not exist: {out}",
        )
    out.mkdir(parents=True, exist_ok=True)
    logical_workspace = (
        workspace_alias.expanduser().absolute()
        if workspace_alias is not None
        else None
    )
    previous_manifest: dict[str, Any] | None = None
    if resume:
        previous_manifest_path = out / "manifest.json"
        if not previous_manifest_path.is_file():
            raise click.ClickException(
                f"resume manifest does not exist: {previous_manifest_path}",
            )
        try:
            previous_manifest = json.loads(
                previous_manifest_path.read_text(encoding="utf-8"),
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise click.ClickException(
                f"invalid resume manifest: {exc}",
            ) from exc
    resolved_task_file = (
        Path(task_file or DEFAULT_BENCHMARK_TASK_FILE).expanduser().resolve()
        if suite == "benchmark-v2"
        else None
    )
    tasks = (
        build_benchmark_suite(resolved_task_file)
        if suite == "benchmark-v2"
        else build_agentic_suite()
    )
    tasks = [
        replace(
            task,
            benchmark_visual_profile=benchmark_visual_profile,
            benchmark_max_images_per_request=(
                benchmark_max_images_per_request
            ),
        )
        for task in tasks
    ]
    known_task_ids = {task.id for task in tasks}
    unknown_task_ids = sorted(set(task_ids) - known_task_ids)
    if unknown_task_ids:
        raise click.ClickException(
            "unknown --task-id values: " + ", ".join(unknown_task_ids),
        )
    if task_ids:
        selected = set(task_ids)
        tasks = [task for task in tasks if task.id in selected]
    if previous_manifest is not None:
        previous_ids = [
            str(item["id"]) for item in previous_manifest.get("tasks", [])
        ]
        missing_ids = [
            task_id
            for task_id in previous_ids
            if task_id not in known_task_ids
        ]
        if missing_ids:
            raise click.ClickException(
                "resume task ids are missing from the current task file: "
                + ", ".join(missing_ids),
            )
        by_id = {task.id: task for task in tasks}
        tasks = [by_id[task_id] for task_id in previous_ids]
    if horizons:
        tasks = [task for task in tasks if task.difficulty in set(horizons)]
    if exclude_review_tasks:
        tasks = [task for task in tasks if task.ground_truth]
    if limit > 0:
        tasks = tasks[:limit]
    if not tasks:
        raise click.ClickException("task selection is empty")
    cost_config = CostConfig(
        input_weight=input_weight,
        output_weight=output_weight,
        cache_read_weight=cache_read_weight,
        cache_creation_weight=cache_creation_weight,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
        cache_read_price_per_million=cache_read_price_per_million,
        cache_creation_price_per_million=cache_creation_price_per_million,
    )
    if previous_manifest is not None:
        expected_resume_config = {
            "suite": suite,
            "model": model,
            "arms": arm_list,
            "arm_order_seed": arm_order_seed,
            "provider_retries": provider_retries,
            "render_profile": render_profile,
            "render_variant": render_variant,
            "workspace_alias": (
                str(logical_workspace)
                if logical_workspace is not None
                else None
            ),
            "history_chunk_messages": history_chunk_messages,
            "benchmark_visual_profile": benchmark_visual_profile,
            "benchmark_max_images_per_request": (
                benchmark_max_images_per_request
            ),
            "min_block_chars": min_block_chars,
            "min_static_tokens": 500,
            "history_collapse_grid_messages": 50,
            "max_images_per_request": 64,
            "max_images_per_tool_result": 10,
            "keep_recent_messages": keep_recent_messages,
            "max_visual_cost_ratio": max_visual_cost_ratio,
            "pixels_per_token": pixels_per_token,
            "chars_per_text_token": chars_per_text_token,
            "max_iters_ceiling": max_iters,
            "cost_config": asdict(cost_config),
            "task_visual_profiles": {
                task.id: _task_visual_profile(task) for task in tasks
            },
        }
        mismatches = [
            key
            for key, value in expected_resume_config.items()
            if previous_manifest.get(key) != value
        ]
        if mismatches:
            raise click.ClickException(
                "resume configuration differs from the original manifest: "
                + ", ".join(mismatches),
            )
        backup = out / "manifest.before-resume.json"
        if not backup.exists():
            shutil.copy2(out / "manifest.json", backup)
    if resolved_task_file:
        shutil.copy2(resolved_task_file, out / "task.snapshot.json")
    try:
        preflight = _prepare_task_artifacts(
            out,
            tasks,
            history_chunk_messages=history_chunk_messages,
            render_profile=render_profile,
            render_variant=render_variant,
            min_block_chars=min_block_chars,
            keep_recent_messages=keep_recent_messages,
            max_visual_cost_ratio=max_visual_cost_ratio,
            pixels_per_token=pixels_per_token,
            chars_per_text_token=chars_per_text_token,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(
            f"benchmark preflight failed: {exc}",
        ) from exc
    reusable_rows: list[dict[str, Any]] = []
    invalid_resume_tasks: set[str] = set()
    if resume:
        reusable_rows, invalid_resume_tasks = _load_resume_rows(
            out,
            tasks,
            arms=arm_list,
            max_iters=max_iters,
            cost_config=cost_config,
        )
    reusable_keys = {
        (str(row["task_id"]), str(row["arm"])) for row in reusable_rows
    }
    run_plan: list[dict[str, Any]] = []
    plan_rng = random.Random(arm_order_seed)
    for task in tasks:
        order = list(arm_list)
        plan_rng.shuffle(order)
        if task.id in invalid_resume_tasks:
            planned_arms = order
        else:
            planned_arms = [
                arm for arm in order if (task.id, arm) not in reusable_keys
            ]
        if planned_arms:
            run_plan.append({"task_id": task.id, "arms": planned_arms})
    manifest = {
        "suite": suite,
        "model": model,
        "arms": arm_list,
        "arm_order_seed": arm_order_seed,
        "provider_retries": provider_retries,
        "render_profile": render_profile,
        "render_variant": render_variant,
        "workspace_alias": (
            str(logical_workspace) if logical_workspace is not None else None
        ),
        "history_chunk_messages": history_chunk_messages,
        "benchmark_visual_profile": benchmark_visual_profile,
        "benchmark_max_images_per_request": (benchmark_max_images_per_request),
        "min_block_chars": min_block_chars,
        "min_static_tokens": 500,
        "history_collapse_grid_messages": 50,
        "max_images_per_request": 64,
        "max_images_per_tool_result": 10,
        "keep_recent_messages": keep_recent_messages,
        "max_visual_cost_ratio": max_visual_cost_ratio,
        "pixels_per_token": pixels_per_token,
        "chars_per_text_token": chars_per_text_token,
        "resume": resume,
        "resume_reused_arms": len(reusable_rows),
        "resume_invalid_tasks": sorted(invalid_resume_tasks),
        "run_plan": run_plan,
        "fail_fast": fail_fast,
        "max_iters_ceiling": max_iters,
        "horizons": list(horizons) or ["short", "medium", "long"],
        "cost_config": asdict(cost_config),
        "task_visual_profiles": {
            task.id: _task_visual_profile(task) for task in tasks
        },
        "cost_weighting_rationale": (
            "Headline weighted units use input and output only. Cache usage "
            "and market-style cache reweighting are retained as diagnostics "
            "but excluded from experiment acceptance and conclusions."
        ),
        "task_file": str(resolved_task_file) if resolved_task_file else None,
        "task_file_sha256": (
            hashlib.sha256(resolved_task_file.read_bytes()).hexdigest()
            if resolved_task_file
            else None
        ),
        "implementation_fingerprint": _implementation_fingerprint(),
        "task_snapshot": (
            str((out / "task.snapshot.json").resolve())
            if resolved_task_file
            else None
        ),
        "preflight": str((out / "preflight.json").resolve()),
        "preflight_status": preflight["status"],
        "task_artifacts_root": preflight["task_artifacts_root"],
        "image_billing_note": (
            "Provider input_tokens is the authoritative multimodal total. "
            "DashScope does not expose a separate image-token breakdown; "
            "gate estimates are never used for reported cost or acceptance."
        ),
        "tasks": [
            {
                **asdict(task),
                "effective_max_iters": _effective_max_iters(task, max_iters),
            }
            for task in tasks
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if preflight["status"] != "pass":
        failed = [
            item["task_id"]
            for item in preflight["tasks"]
            if not item["solvable_contract"]
        ]
        raise click.ClickException(
            "benchmark preflight found incomplete tasks: " + ", ".join(failed),
        )
    if not confirm:
        click.echo(
            json.dumps(
                {
                    "status": "dry-run",
                    "task_count": len(tasks),
                    "planned_minimum_model_calls": sum(
                        len(item["arms"]) for item in run_plan
                    ),
                    "planned_model_calls": sum(
                        len(item["arms"]) for item in run_plan
                    ),
                    "resume": resume,
                    "reused_arms": len(reusable_rows),
                    "invalid_existing_tasks": sorted(invalid_resume_tasks),
                    "run_plan": run_plan,
                    "note_model_calls": (
                        "Agentic tasks usually require multiple LLM calls per "
                        "arm; planned_minimum_model_calls is not a cost cap."
                    ),
                    "manifest": str((out / "manifest.json").resolve()),
                    "preflight": str((out / "preflight.json").resolve()),
                    "task_artifacts": preflight["task_artifacts_root"],
                    "note": "Re-run with --confirm to incur real model usage.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        return

    async def run_all() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = list(reusable_rows)
        rng = random.Random(arm_order_seed)
        for task in tasks:
            order = list(arm_list)
            rng.shuffle(order)
            if task.id in invalid_resume_tasks:
                rows = [row for row in rows if row["task_id"] != task.id]
            else:
                order = [
                    arm for arm in order if (task.id, arm) not in reusable_keys
                ]
            if not order:
                continue
            pair_rows = await _run_pair(
                task,
                base_config=cfg,
                model_slot=slot,
                output_dir=out,
                workspace_alias=logical_workspace,
                timeout=timeout,
                provider_retries=provider_retries,
                max_iters=max_iters,
                arm_order=order,
                render_profile=render_profile,
                render_variant=render_variant,
                history_chunk_messages=history_chunk_messages,
                min_block_chars=min_block_chars,
                keep_recent_messages=keep_recent_messages,
                max_visual_cost_ratio=max_visual_cost_ratio,
                pixels_per_token=pixels_per_token,
                chars_per_text_token=chars_per_text_token,
                cost_config=cost_config,
            )
            rows.extend(pair_rows)
            _write_checkpoint(out, rows)
            partial_payload = {
                **manifest,
                "rows": rows,
                "summary": _summarize(rows),
            }
            _write_report(out, partial_payload)
            if fail_fast and any(
                row.get("status") != "success" or not row.get("quality_pass")
                for row in pair_rows
            ):
                break
        return rows

    rows = asyncio.run(run_all())
    _write_checkpoint(out, rows)
    payload = {**manifest, "rows": rows, "summary": _summarize(rows)}
    _write_report(out, payload)
    acceptance = payload["summary"]["acceptance"]
    has_failures = _has_run_failures(rows, acceptance, arm_list)
    if has_failures:
        status = "complete_with_failures"
    elif acceptance.get("review_pending", False):
        status = "complete_review_pending"
    else:
        status = "complete"
    click.echo(
        json.dumps(
            {
                "status": status,
                "results": str((out / "results.json").resolve()),
                "report": str((out / "report.md").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    if has_failures:
        raise click.exceptions.Exit(1)
