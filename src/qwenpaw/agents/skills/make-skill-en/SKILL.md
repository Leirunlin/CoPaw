---
name: make-skill
description: "Create a focused workspace Skill from reusable decisions, knowledge, templates, or workflows in the current conversation. Use for /make-skill with a focus argument and requests such as save this workflow or turn this into a skill; do not use for one-off summaries or ordinary file creation."
metadata:
  builtin_skill_version: "2.1"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

# Make Skill

Create one new workspace Skill from the raw current conversation. Use the scripts in this directory for the lifecycle below; do not rely on a make-skill-specific core tool, mode, or state store.

Resolve `<workspace>` from the runtime directory context: use the current agent's absolute workspace path (also the working directory when no separate project is configured). Pass that same value throughout the lifecycle, independently of the task's project directory and the script `cwd`. Lifecycle artifacts belong under `<workspace>/.qwenpaw/make-skill/`; published Skills belong under `<workspace>/skills/`.

Run each documented `python scripts/...` command through `execute_shell_command`, setting `cwd` to this Skill's `<dir>` from the available-skills entry; every script reads one JSON object from stdin (or `--input <file>`) and writes one JSON object to stdout.

## Plan

The focus in `/make-skill <focus>` is required. For a natural-language request, infer it from the request and current conversation. Later user corrections replace conflicting earlier rules. Preserve stable guidance, contracts, templates, and workflows that should change future behavior; exclude one-off data, temporary paths, secrets, and retry chatter.

Read [primary type and package](references/type-and-package.md), then choose one primary type and only the files it needs. When the proposed test mode is not `off`, read [behavior testing](references/behavior-testing.md) before defining its target.

### Batch workflows

A stored batch is a parameterized `run_tool_batch` program bundled with a workflow Skill. Use `batch: true` when a reusable region's actions, branches, and success condition can be stated before execution and one stored entrypoint saves meaningful agent-tool round trips. The region may be the whole workflow, one substantial helper, or one semantic tool-native action; action count is not the criterion. Runtime data, observations, and a final agent review do not prevent batching when the rule for handling them is already known.

Use `batch: false` only when execution must invent the next action or success condition at runtime, or a shared entrypoint has no practical reuse value. If the user explicitly requests Batch, apply that choice to the plan without reopening eligibility.

Only after selecting `batch: true`, read [run batch](references/run-batch.md) before finalizing the workflow and file tree. When `batch: false`, do not read it.

Planning is read-only except for the plan record saved by `python scripts/create_plan.py`: use conversation evidence and existing artifacts, but do not execute or probe the proposed workflow, create package files, or initialize a draft. Pass the workspace and candidate through stdin:

```json
{
  "workspace": "<workspace>",
  "plan": {
    "revision": 1,
    "focus": "One-sentence extraction scope",
    "name": "lowercase-hyphen-name",
    "goal": "Outcome for a future agent",
    "type": "workflow",
    "batch": true,
    "steps": ["A user-reviewable workflow step"],
    "package": ["SKILL.md", "scripts/run.batch.json"],
    "execution": "foreground",
    "test": {"mode": "off", "target": ""},
    "warnings": []
  }
}
```

The script saves a separate plan record under `<workspace>/.qwenpaw/make-skill/plans/<plan_id>/plan.json` and returns its `plan_id` with the normalized `plan`. Keep that ID for Build; a stored plan is not evidence of user approval. Cancelling planning retains the record without creating a draft.

Render the normalized plan in English and show the selected value together with every available choice so the user can revise it without knowing the schema. The user-visible plan must contain this compact options table; do not replace it with prose or an approval hint. Omit the `Batch` row for a non-workflow:

| Option | Selected | Available |
|---|---|---|
| Type | current English label | instruction / template / workflow |
| Batch (workflow only) | enabled or disabled | enabled / disabled |
| Execution | foreground or background | foreground / background |
| Behavior test | current English label | off / smoke / eval (full behavioral evaluation) |

Also show the name, goal, workflow, complete file tree, test target when applicable, and warnings. Pass the internal values `instruction/template/workflow`, `true/false`, `foreground/background`, and `off/smoke/eval` to the script. Do not invent a `full` enum or any choice outside the script schema. Do not show a Batch closing reason, schema, revision, or internal enum. Ask the user to approve, modify, or cancel, then end the response without further tool calls.

Only a new user message explicitly approving the latest displayed `create_plan.py` result permits Build. Invoking `/make-skill` starts planning; earlier task discussion or a hand-written outline does not replace this plan and approval step.

- After a modification, merge the latest feedback, increment `revision`, rerun `create_plan.py`, and show the complete returned plan for approval. Use its new `plan_id`; earlier approval does not carry over to the revised plan.
- Stop on cancellation. Distinguish acknowledgment from approval; if the user's intent is unclear, ask one brief confirmation and wait.
- Do not ask separately about execution or testing.

This version creates new Skills only. Resolve a name conflict through a newly approved revision; never overwrite an existing Skill.

## Build

After approval, run `python scripts/init_draft.py` with JSON through stdin:

```json
{"workspace": "<workspace>", "plan_id": "returned-plan-id"}
```

Initialization reads the stored plan; it does not accept an inline replacement. If the plan is missing or invalid, return to planning instead of proceeding to Build.

`execution` selects whether the current agent or a background subagent completes Skill creation. After initialization, for `background`, give the generic subagent the complete approved plan, latest corrections, workspace path, and draft path to author the files, validate, run the approved behavior test, and publish without requesting approval again. Report the creation result when finished; running the generated Skill outside the approved behavior test requires a separate user request.

Create only approved files under the returned `skill_dir`. Start the generated `SKILL.md` with valid frontmatter:

```yaml
---
name: lowercase-hyphen-name
description: Briefly state the capability and when to use it.
---
```

Keep the body to essential procedure and constraints without repeating the description. Type metadata is unnecessary.

Before validation, read the package from the perspective of a future agent that cannot see the source conversation. Remove references to source task directories, prior outputs, temporary IDs, current-case examples, or make-skill draft/publish language unless that resource is deliberately packaged and reusable. When adapting an existing helper, generalize its paths, docstrings, and reporting, and check that its implementation still matches the final reusable rules. Keep this as one authoring pass; do not add case-specific lifecycle checks.

## Validate, test, and publish

Before executing any draft script or batch, run `python scripts/validate_skill.py` with JSON through stdin:

```json
{"workspace": "<workspace>", "draft_id": "returned-draft-id"}
```

Fix reported static or security errors in the draft and validate again. Testing is independent of Batch: run exactly the approved behavior test according to [behavior testing](references/behavior-testing.md), and let `off` perform no draft execution. When a test or Batch run fails, retain the draft, report the concrete error, revise the Skill if the correction is clear, then validate again; do not hide the failure behind a fallback.

Publish the unchanged validated draft by running `python scripts/publish_skill.py` with JSON through stdin:

```json
{"workspace": "<workspace>", "draft_id": "returned-draft-id", "expected_digest": "digest-from-validation"}
```

On success, report the package tree, validation summary, test result when one ran, and invocation `/<name>`. On conflict or failure, retain the draft and report the error. Publishing a Skill is already persistent; do not also write it to `MEMORY.md` or daily memory unless the user separately asks.
