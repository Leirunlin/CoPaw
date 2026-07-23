# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import click

logger = logging.getLogger(__name__)


_SKILL_FS_NAMES = {"skills", "skill", "skill.json", ".skill.json.lock"}


@contextmanager
def _isolated_skills_workspace(
    skills_dir: str | None,
    base_workspace: Path | None,
) -> Iterator[Path | None]:
    """Create a temporary overlay workspace when *skills_dir* is given.

    The overlay symlinks the external skills directory as ``skills/`` and
    pre-populates a manifest with every discovered skill enabled.  Non-skill
    files from *base_workspace* are symlinked so that prompt/bootstrap files
    remain accessible.  All manifest writes land in the temporary directory,
    keeping the real workspace untouched.
    """
    if not skills_dir:
        yield base_workspace
        return

    with tempfile.TemporaryDirectory(prefix="qwenpaw_headless_") as tmp:
        tmp_path = Path(tmp)
        resolved = Path(skills_dir).resolve()
        (tmp_path / "skills").symlink_to(resolved)

        skill_entries: dict = {}
        if resolved.is_dir():
            for p in sorted(resolved.iterdir()):
                if p.is_dir() and (p / "SKILL.md").exists():
                    skill_entries[p.name] = {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "headless",
                    }
        (tmp_path / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "workspace-skill-manifest.v1",
                    "version": 1,
                    "skills": skill_entries,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if base_workspace and base_workspace.is_dir():
            for item in base_workspace.iterdir():
                if item.name in _SKILL_FS_NAMES or item.name.startswith(
                    ".skill_",
                ):
                    continue
                target = tmp_path / item.name
                if not target.exists():
                    target.symlink_to(item)

        yield tmp_path


def _read_instruction(raw: str) -> str:
    """Return instruction text; read from file if *raw* is a valid path."""
    p = Path(raw)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return raw


def _build_headless_workspace(workspace_dir: Path, agent_id: str):
    """Create an unstarted UI-equivalent workspace with builtin tools.

    TODO: STALE: This UI-parity workspace exists for the temporary visual
    benchmark. Restore the simpler headless task path when that suite is gone.
    """
    from ..agents.tools import discover_builtin_tool_funcs
    from ..app.workspace.workspace import Workspace

    workspace = Workspace(agent_id=agent_id, workspace_dir=str(workspace_dir))
    workspace.bootstrap_plugins(
        builtin_tool_funcs=discover_builtin_tool_funcs(),
    )
    return workspace


async def _run_task(  # pylint: disable=R0912,R0915
    instruction: str,
    agent_config,
    request_context: dict[str, str],
    max_iters: int,
    timeout: int,
    output_dir: str | None,
    skills_dir: str | None = None,
    # TODO: STALE: Seeded context and scripted turns are benchmark inputs.
    seed_context: list[dict] | None = None,
    scripted_turns: list[str] | None = None,
) -> dict:
    from types import SimpleNamespace

    from agentscope.message import (
        Msg,
        TextBlock,
        ToolCallBlock,
        ToolResultBlock,
    )

    from ..runtime.builder import AgentBuilder
    from ..schemas import AgentRequest

    agent_config.running.max_iters = max_iters

    base_workspace: Path | None = None
    if agent_config.workspace_dir:
        base_workspace = Path(agent_config.workspace_dir).expanduser()

    with _isolated_skills_workspace(skills_dir, base_workspace) as workspace:
        # TODO: STALE: Benchmark UI-parity setup. Headless tasks bypass the
        # normal PRE_DISPATCH lifecycle hook, so
        # establish the same ContextVars explicitly. This is required both
        # for workspace-scoped tools and per-session usage traces.
        from ..app.agent_context import (
            set_current_agent_id,
            set_current_channel,
            set_current_session_id as set_app_session_id,
            set_current_user_id,
        )
        from ..config.context import (
            set_current_session_id,
            set_current_workspace_dir,
        )

        session_id = request_context.get("session_id", "headless-task")
        set_current_agent_id(request_context.get("agent_id", "default"))
        set_current_session_id(session_id)
        set_app_session_id(session_id)
        set_current_user_id(request_context.get("user_id", "headless"))
        set_current_channel(request_context.get("channel", "console"))
        if workspace is not None:
            set_current_workspace_dir(workspace)
        # Mirror the UI runtime's local workspace/tool registry. Previously
        # headless tasks used ``ctx.workspace=None`` and silently lost every
        # normal file/search/edit tool.
        runtime_workspace = None
        if workspace is not None:
            runtime_workspace = _build_headless_workspace(
                workspace,
                request_context.get("agent_id", "default"),
            )
        req = AgentRequest(
            input=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": instruction}],
                },
            ],
            session_id=session_id,
            user_id=request_context.get("user_id", "headless"),
            channel=request_context.get("channel", "console"),
            request_context=request_context,
        )
        ctx = SimpleNamespace(
            request=req,
            session_id=req.session_id,
            agent_id=request_context.get("agent_id", "default"),
            root_session_id=req.session_id,
            root_agent_id=request_context.get("agent_id", "default"),
            workspace_dir=workspace,
            workspace=runtime_workspace,
            app_services=None,
            # TODO: STALE: Explicit override keeps --model and experiment-arm
            # changes
            # isolated in memory; AgentBuilder otherwise loads agent.json.
            agent_config=agent_config,
            session_state=None,
        )
        builder = AgentBuilder()
        agent = await builder.build(ctx)
        # TODO: STALE: Direct state seeding is benchmark-only.
        if seed_context:
            agent.state.context.extend(
                Msg.model_validate(item) for item in seed_context
            )
        # TODO: STALE: Imported benchmark history can contain hundreds of
        # historical tool calls. Execution metrics must start after seeding
        # or a recovery regression is hidden inside the transcript baseline.
        execution_context_start = len(
            list(getattr(agent.state, "context", []) or []),
        )

        t0 = time.monotonic()
        native_usage = None
        # TODO: STALE: Multi-phase records support scripted benchmark tasks.
        phase_responses: list[str] = []
        phase_records: list[dict[str, object]] = []
        try:
            from ..token_usage.model_wrapper import TokenRecordingModelWrapper

            # TODO: STALE: Per-call tracing is evaluation-only. Remove this
            # opt-in together with scripted turns and the visual benchmark.
            TokenRecordingModelWrapper.start_trace_for_session(session_id)
            trace_length = TokenRecordingModelWrapper.trace_length_for_session
            prompts = [*(scripted_turns or []), instruction]
            response = None
            for phase_index, prompt in enumerate(prompts):
                phase_started = time.monotonic()
                message_start = len(
                    list(getattr(agent.state, "context", []) or []),
                )
                call_start = trace_length(session_id)
                remaining = max(0.001, timeout - (time.monotonic() - t0))
                response = await asyncio.wait_for(
                    agent.reply(
                        [
                            Msg(
                                name="user",
                                role="user",
                                content=[TextBlock(text=prompt)],
                            ),
                        ],
                    ),
                    timeout=remaining,
                )
                phase_responses.append(
                    response.get_text_content() if response else "",
                )
                phase_tool_calls = []
                phase_messages = list(
                    getattr(agent.state, "context", []) or [],
                )[message_start:]
                for message in phase_messages:
                    for block in getattr(message, "content", []) or []:
                        if isinstance(block, ToolCallBlock):
                            phase_tool_calls.append(
                                {"name": block.name, "input": block.input},
                            )
                phase_records.append(
                    {
                        "index": phase_index,
                        "prompt": prompt,
                        "response": phase_responses[-1],
                        "tool_calls": phase_tool_calls,
                        "call_start": call_start,
                        "call_end": trace_length(session_id),
                        "elapsed_seconds": round(
                            time.monotonic() - phase_started,
                            4,
                        ),
                    },
                )
            elapsed = time.monotonic() - t0
            result: dict = {
                "status": "success",
                "elapsed_seconds": round(elapsed, 2),
                "response": (response.get_text_content() if response else ""),
                "phase_responses": phase_responses,
                "phase_records": phase_records,
                "scripted_turn_count": len(scripted_turns or []),
            }
            # One AgentScope reply usage covers its internal tool loop, but it
            # does not cover earlier replies in a scripted multi-turn task.
            # For those tasks the per-call recorder trace below is the only
            # correctly aggregated provider source.
            if len(prompts) == 1:
                native_usage = getattr(response, "usage", None)
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            result = {
                "status": "timeout",
                "elapsed_seconds": round(elapsed, 2),
                "timeout_seconds": timeout,
                "response": "",
                "phase_responses": phase_responses,
                "phase_records": phase_records,
            }
        except Exception as exc:
            elapsed = time.monotonic() - t0
            result = {
                "status": "error",
                "elapsed_seconds": round(elapsed, 2),
                "error": str(exc),
                "response": "",
                "phase_responses": phase_responses,
                "phase_records": phase_records,
            }

        # TODO: STALE: Execution counters are benchmark report evidence.
        context_messages = list(getattr(agent.state, "context", []) or [])
        live_messages = context_messages[execution_context_start:]
        tool_call_names: dict[str, str] = {}
        tool_result_ids: set[str] = set()
        for message in live_messages:
            for block in getattr(message, "content", []) or []:
                if isinstance(block, ToolCallBlock):
                    tool_call_names.setdefault(block.id, block.name)
                elif isinstance(block, ToolResultBlock):
                    tool_result_ids.add(block.id)
        tool_calls_by_name: dict[str, int] = {}
        for name in tool_call_names.values():
            tool_calls_by_name[name] = tool_calls_by_name.get(name, 0) + 1
        result["execution"] = {
            "agent_iterations": int(getattr(agent.state, "cur_iter", 0) or 0),
            "context_messages": len(context_messages),
            "live_context_messages": len(live_messages),
            "tool_calls": len(tool_call_names),
            "tool_results": len(tool_result_ids),
            "tool_calls_by_name": tool_calls_by_name,
        }

    # TODO: STALE: Per-call aggregation and trace export are benchmark-only.
    usage: dict = {}
    trace: list[dict] = []
    try:
        from ..token_usage.model_wrapper import TokenRecordingModelWrapper

        trace = TokenRecordingModelWrapper.pop_trace_for_session(
            request_context.get("session_id", "headless-task"),
        )
        if trace:
            usage = {
                "input_tokens": sum(
                    int(call.get("prompt_tokens", 0) or 0) for call in trace
                ),
                "output_tokens": sum(
                    int(call.get("completion_tokens", 0) or 0)
                    for call in trace
                ),
                "llm_calls": len(trace),
            }
        native_input = int(
            (
                getattr(native_usage, "input_tokens", 0) or 0
                if native_usage is not None
                else 0
            ),
        )
        native_output = int(
            (
                getattr(native_usage, "output_tokens", 0) or 0
                if native_usage is not None
                else 0
            ),
        )
        if native_input > 0 or native_output > 0:
            recorded_input = int(usage.get("input_tokens", 0) or 0)
            recorded_output = int(usage.get("output_tokens", 0) or 0)
            usage.update(
                {
                    "input_tokens": native_input,
                    "output_tokens": native_output,
                    "source": "agentscope_message",
                },
            )
            if (recorded_input, recorded_output) != (
                native_input,
                native_output,
            ) and (recorded_input > 0 or recorded_output > 0):
                usage["recorder_tokens"] = {
                    "input_tokens": recorded_input,
                    "output_tokens": recorded_output,
                }
        model = getattr(agent, "model", None)
        if model is not None and not trace:
            monitor = getattr(model, "monitor", None)
            if monitor is not None:
                metrics = (
                    monitor.get_metrics()
                    if callable(getattr(monitor, "get_metrics", None))
                    else {}
                )
                usage["input_tokens"] = metrics.get("prompt_tokens", 0)
                usage["output_tokens"] = metrics.get("completion_tokens", 0)
                usage["cost_usd"] = metrics.get("cost_usd")
    except Exception:
        logger.debug("Failed to extract token usage", exc_info=True)
    result["usage"] = usage
    result["trace"] = trace

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return result


@click.command("task")
@click.option(
    "-i",
    "--instruction",
    required=True,
    help="Task instruction text or path to a .md file.",
)
@click.option(
    "-m",
    "--model",
    default=None,
    help="Model override (e.g. 'anthropic/claude-sonnet-4-5').",
)
@click.option(
    "--max-iters",
    default=30,
    type=int,
    show_default=True,
    help="Max ReAct loop iterations.",
)
@click.option(
    "-t",
    "--timeout",
    default=900,
    type=int,
    show_default=True,
    help="Max execution time in seconds.",
)
@click.option(
    "--no-guard",
    is_flag=True,
    default=False,
    help="Disable tool guard security checks.",
)
@click.option(
    "--skills-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Direct skills directory path (bypasses manifest).",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Directory for execution logs and result.json.",
)
@click.option(
    "--agent-id",
    default="default",
    show_default=True,
    help="Agent ID to use.",
)
def task_cmd(
    instruction: str,
    model: str | None,
    max_iters: int,
    timeout: int,
    no_guard: bool,
    skills_dir: str | None,
    output_dir: str | None,
    agent_id: str,
) -> None:
    """Run a single task instruction headlessly (no web server)."""
    from ..config.config import load_agent_config
    from ..config.config import ModelSlotConfig
    from ..utils.logging import setup_logger

    setup_logger("info")

    instruction_text = _read_instruction(instruction)
    if not instruction_text.strip():
        click.echo("Error: instruction is empty.", err=True)
        sys.exit(1)

    try:
        agent_config = load_agent_config(agent_id)
    except ValueError as exc:
        click.echo(f"Error loading agent config: {exc}", err=True)
        sys.exit(1)

    if model:
        parts = model.split("/", 1)
        if len(parts) == 2:
            agent_config.active_model = ModelSlotConfig(
                provider_id=parts[0],
                model=parts[1],
            )
        else:
            agent_config.active_model = ModelSlotConfig(
                provider_id="",
                model=model,
            )

    request_context: dict[str, str] = {
        "session_id": "headless-task",
        "user_id": "headless",
        "channel": "console",
        "agent_id": agent_id,
    }
    if no_guard:
        request_context["_headless_tool_guard"] = "false"

    result = asyncio.run(
        _run_task(
            instruction=instruction_text,
            agent_config=agent_config,
            request_context=request_context,
            max_iters=max_iters,
            timeout=timeout,
            output_dir=output_dir,
            skills_dir=skills_dir,
        ),
    )

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] == "success" else 1)
