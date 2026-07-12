# Code-Grounded Build Plan (traced from Hermes source)

> Produced by tracing the actual Hermes code under this repo. All claims cite `file:line`. Pairs with the other `kaizen/*.md` docs. Where this and earlier docs disagree, this doc wins on code facts (notably: SOUL.md not profile.md; process-per-tenant confirmed).

## Invocation

The in-process single-turn primitive is **`AIAgent.run_conversation(...)`** (`run_agent.py:5787`). Synchronous, in-process (no subprocess), so from async FastAPI run it in a threadpool. The CLI oneshot (`hermes_cli/oneshot.py:_run_agent` `:297-420`) is the cleanest template: build `AIAgent(...)`, call `agent.run_conversation(prompt)`, read the result dict.

- Signature: `run_conversation(user_message, system_message=None, conversation_history=None, task_id=None, stream_callback=None, ...) -> dict`. Prompt → `user_message`; per-turn persona → `system_message`/`ephemeral_system_prompt`; concurrency isolation → `task_id`.
- Return dict: `final_response`, `messages` (full transcript with tool_calls + tool results), `api_calls`, `completed`, and on failure `failed`/`error`/`partial`. **No `events` key** — observability is via callbacks or post-hoc from `messages`.
- No `hermes_home` param — home is resolved from env/ContextVar (see tenancy verdict).

Observability:
- Live push callbacks on the `AIAgent` constructor: `step_callback`, `tool_start_callback`, `tool_complete_callback`, `tool_progress_callback`, `event_callback` (`conversation_loop.py:670`, `tool_executor.py:548/939`, `run_agent.py:460`).
- Post-hoc pull: `agent._convert_to_trajectory_format(messages, query, completed)` (`run_agent.py:1952`); `save_trajectories=True` writes JSONL (`agent/trajectory.py`).

```python
from starlette.concurrency import run_in_threadpool
from run_agent import AIAgent  # import AFTER HERMES_HOME env is set (in the worker process)

async def run_tenant_turn(prompt, persona, toolsets, emit):
    agent = AIAgent(
        model="", enabled_toolsets=toolsets, ephemeral_system_prompt=persona,
        step_callback=lambda n, prev: emit("step", {"iter": n}),
        tool_start_callback=lambda i, name, a: emit("tool_start", {"name": name}),
        tool_complete_callback=lambda i, name, a, r: emit("tool_complete", {"name": name}),
        event_callback=lambda ev, p: emit(ev, p),
    )
    result = await run_in_threadpool(agent.run_conversation, prompt)
    traj = agent._convert_to_trajectory_format(result["messages"], prompt, result["completed"])
    return {"final_response": result["final_response"], "trajectory": traj, "completed": result["completed"]}
```

## Subagents

Real feature: tool `delegate_task` in `tools/delegate_tool.py` (in-process threads via `DaemonThreadPoolExecutor`, not subprocesses). Child = an `AIAgent` built by `_build_child_agent` (`:1044`) with `ephemeral_system_prompt` from `goal`+`context`, `skip_context_files=True`, `skip_memory=True`. Only `final_response` re-enters the parent. Child inherits the parent's HERMES_HOME (contextvars copied, `thread_context.py:64`).

Limitation: the **model-facing** schema can't choose a child's model or narrow its toolset (`delegate_tool.py:2519`). The **Python** API and `tasks:[{...,toolsets}]` entries can (`:2382`, intersected `:1126`). **Recommendation:** for deterministic per-specialist tools, have FastAPI construct one `AIAgent` per role with explicit `enabled_toolsets` + persona, rather than relying on `delegate_task`. Keep `delegate_task` only for the "manager spawns a specialist on the fly" org-L5 demo moment.

## Agent + skill definitions (where prompts/skills live)

- **Skill = a directory `$HERMES_HOME/skills/<category>/<name>/SKILL.md`** (YAML frontmatter + Markdown; only `name`+`description` required; resolver `skills_tool.py:146` resolves live per call). Hermes/Anthropic Agent-Skills format, not agentskills.io. No per-skill `tools:` field; gate via `metadata.hermes.requires_toolsets`.
- **Persona = `$HERMES_HOME/SOUL.md`**, one per profile, loaded into the system prompt (`prompt_builder.py:load_soul_md` `:1819`, call-time resolved = tenant-safe). No per-subagent SOUL file.
- **MCP servers = per profile** in `$HERMES_HOME/config.yaml` under `mcp_servers:` (`cli-config.yaml.example:928`). Each becomes toolset `mcp-<name>`; scope a specialist to it via that agent's `enabled_toolsets`. No per-agent MCP block.

**Storage decision (confirmed):** specialist personas + skills live in the **repo** (SKILL.md / persona .md, version-controlled = eval-L5 points), synced into each tenant's `HERMES_HOME` at provisioning. Per-tenant **data** (brand profile content, generated content, runs) lives in Convex/Honcho.

## Multi-tenancy verdict (LOCKED)

**Process-per-tenant with `HERMES_HOME` set in the worker's env before Python import.** In-process ContextVar override is NOT a safe wall. Three load-bearing subsystems freeze their path at import and ignore the override:

| Location | Cached value | Safe under override? |
|---|---|---|
| `hermes_state.py:123` | `DEFAULT_DB_PATH = get_hermes_home()/"state.db"` (the sessions DB; `AIAgent` opens `SessionDB()` with no path, `run_agent.py:586`) | **NO** |
| `agent/auxiliary_client.py:662` | `_AUTH_JSON_PATH = get_hermes_home()/"auth.json"` (provider credentials) | **NO** |
| `plugins/memory/honcho/client.py:742` | process-global Honcho client singleton, keyed by nothing (first tenant wins) | **NO** |
| plus `run_agent.py:125` (.env), `cli.py:180`, cron/gateway/checkpoint module constants | assorted | **NO** |

Override-safe subsystems (call-time resolution): skills (`skills_tool.py:146`), memory dir (`memory_tool.py:55`), memory init (`memory_manager.py:1125`), SOUL.md (`prompt_builder.py:1819`), Honcho config path (`client.py:80`, but not the client object). Setting `HERMES_HOME` in the worker env before import makes every path resolve correctly by construction — Hermes's own documented intent (`hermes_constants.py:65-69`). Keep the ContextVar override only as a secondary optimization inside a worker.

## Memory + the brand profile file (CORRECTION: use SOUL.md, not profile.md)

- **Honcho:** selected by `memory.provider` (`agent_init.py:1358`); config keys `api_key`/`baseUrl`/`workspace`/`aiPeer` in `$HERMES_HOME/honcho.json` (`honcho/client.py`). Read into the turn (`turn_context.py:558`, `conversation_loop.py:801`), written after (`run_agent.py:3367` → `sync_turn`). Per-tenant workspace/peer derived per profile. Client singleton is process-global → another reason for process-per-tenant.
- **There is NO `profile.md` convention in Hermes.** The only HERMES_HOME-relative file every agent auto-reads is **`$HERMES_HOME/SOUL.md`** (`load_soul_md` `:1819`). So the per-tenant brand profile that all agents read must be written to **`SOUL.md`** (brand DNA + guardrails), optionally supplemented by an `AGENTS.md` in the tenant's working dir (`prompt_builder.py:build_context_files_prompt` `:1947`, CWD-scoped). Size cap `context_file_max_chars` default 20,000, content is injection-scanned.

## FastAPI integration surface

| Operation | Hermes mapping | Process model |
|---|---|---|
| Provision tenant | scaffold `/data/hermes/profiles/<brand_id>/` with `config.yaml` (memory.provider: honcho, mcp_servers, skills), `honcho.json` (per-tenant workspace), `SOUL.md` | filesystem, before worker import |
| Run a turn (profile build / content gen) | launch/reuse worker with `HERMES_HOME=<profile>` env → `AIAgent(enabled_toolsets, ephemeral_system_prompt).run_conversation(...)` | subprocess wall; turn is sync in-process → threadpool |
| Collect run events | constructor callbacks in worker → forward over IPC (JSON-lines/pipe/Redis) → FastAPI SSE; final trajectory via `_convert_to_trajectory_format` | in-process callbacks streamed out |

## Files to create — NOW scope (no core Hermes edits)
- `kaizen/tenancy.py` — `provision_tenant(brand_id, brand_config) -> Path`: scaffolds the profile dir + `config.yaml` + `honcho.json` + `SOUL.md`.
- `kaizen/worker.py` — per-tenant worker entrypoint: reads `HERMES_HOME` env, builds `AIAgent` with callbacks, runs `run_conversation`, emits events + result as JSON-lines. Model on `hermes_cli/oneshot.py:_run_agent` but wire callbacks.
- `kaizen/worker_pool.py` — spawn-per-tenant + reuse + idle-evict; sets `HERMES_HOME` at `subprocess.Popen(env=...)`.
- `kaizen/personas/brand_strategist.md`, `kaizen/personas/content_creator.md` — the two NOW-scope personas (or as `skills/marketing/<name>/SKILL.md`).
- `kaizen/tests/test_isolation.py` — Phase 0 gate: two workers, two HERMES_HOME, assert no cross-tenant rows in `state.db`.

Per-tenant runtime artifacts (written by the app, not committed): `SOUL.md`, `config.yaml`, `honcho.json`, `state.db`, `skills/`.

## Risks / unknowns
- Subagent per-child MCP scoping is ambiguous in code (`delegate_tool.py:2519` vs `:2382`) — don't depend on it; use FastAPI-constructed per-role agents. Spike only if pursuing org-L5.
- Honcho client singleton is process-global — fine under process-per-tenant, fatal in-process.
- No first-class `create_profile()` Python API — provisioning is scaffolding (see `hermes_cli/profiles.py`, `hermes_bootstrap.py` to reuse seeding).
- `run_conversation` is synchronous — must offload from the FastAPI event loop.
