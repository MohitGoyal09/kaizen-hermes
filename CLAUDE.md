# CLAUDE.md — Kaizen x Hermes (project context for Claude Code)

Read this first. It orients you to what we are building and points to the locked design docs. Detailed decisions live in `kaizen/*.md`; this file is the index + the rules.

## What this repo is
A private fork of **Nous Research Hermes Agent** (upstream: `nousresearch/hermes-agent`). We (Team Kaizen) are building a **multi-tenant AI marketing agency** on top of it for the GrowthX Hermes Buildathon, track **AI as Agency**.

Product in one line: a brand signs up, an **onboarding interview + research** builds a brand profile, and a **crew of agents generates on-brand content** (and, next step, publishes it to a real surface and measures it).

## Ground rules (do not violate)
1. **Do not edit core Hermes source.** All our code goes under `kaizen/`. Hermes is the vendored base; we call it, we don't fork its internals.
2. **Multi-tenancy = process-per-tenant.** One Hermes worker process per brand with `HERMES_HOME=/data/hermes/profiles/<brand_id>` set in its env **before** any Hermes import. In-process ContextVar scoping is UNSAFE (three subsystems cache their path at import — see `CODE_GROUNDED_PLAN.md`). Never rely on the in-process override as the isolation wall.
3. **The per-tenant brand profile is written to `$HERMES_HOME/SOUL.md`** (not `profile.md` — Hermes has no such convention). Every agent auto-reads SOUL.md.
4. **Agent personas + skills live in the repo** (`kaizen/personas/*.md` or `skills/marketing/<name>/SKILL.md`), version-controlled, synced into each tenant's `HERMES_HOME`. Only per-tenant *data* goes in a DB (Convex) / memory (Honcho).
5. **Tenant id comes from the auth token, never a client-supplied field** (SPEC R7).
6. **Deployment is deferred.** Focus is getting the app working locally first. `kaizen/DEPLOYMENT.md` is for later; ignore it until the app runs.

## Doc index (kaizen/)
- **`kaizen/SPEC.md`** — auth model + multi-tenancy rules R1-R8. The isolation contract.
- **`kaizen/FEATURES_AND_AGENTS.md`** — the agent roster (orchestrator + 5 specialists) + the onboarding intake interview. What each agent does.
- **`kaizen/CODE_GROUNDED_PLAN.md`** — **the build bible.** Traced from Hermes source: how to invoke an agent, spawn subagents, define skills, wire memory, and the exact files to create. Cites `file:line`. Read this before writing code.
- **`kaizen/BUILD_PLAN.md`** — rubric-driven phases + owners + demo mapping.
- **`kaizen/GETTING_STARTED.md`** — Hermes config keys, model tiers (OpenAI), power-up→agent map.
- **`kaizen/DEPLOYMENT.md`** — cloud storage/deploy (Convex + Honcho + profiles). DEFERRED.

## Key code facts (from CODE_GROUNDED_PLAN.md)
- **Run one agent turn:** `AIAgent.run_conversation(user_message, system_message=..., ...)` in `run_agent.py:5787`. Synchronous + in-process → call it from a threadpool. Template: `hermes_cli/oneshot.py:_run_agent` (`:297-420`).
- **Result dict:** `final_response`, `messages` (full transcript), `api_calls`, `completed`. Observability via constructor callbacks (`step_callback`, `tool_start_callback`, `tool_complete_callback`, `event_callback`) + `agent._convert_to_trajectory_format(...)`.
- **Skills:** `$HERMES_HOME/skills/<category>/<name>/SKILL.md` (YAML frontmatter, only `name`+`description` required).
- **Persona:** `$HERMES_HOME/SOUL.md` (`prompt_builder.py:load_soul_md` `:1819`).
- **MCP servers:** per profile in `$HERMES_HOME/config.yaml` under `mcp_servers:`; scope a specialist via its `enabled_toolsets` (toolset `mcp-<name>`).
- **Home resolution:** `hermes_constants.get_hermes_home()` (`:55`). Import-time hazards: `hermes_state.py:123` (state.db), `agent/auxiliary_client.py:662` (auth.json), `plugins/memory/honcho/client.py:742` (Honcho singleton).
- **Build agents as FastAPI-constructed per-role `AIAgent`s** with explicit `enabled_toolsets`; use `delegate_task` (`tools/delegate_tool.py`) only for the live "spawn a specialist" demo moment.

## NOW scope (what to build, in order)
1. **Isolation test** — `kaizen/tests/test_isolation.py`: two workers, two `HERMES_HOME`, assert no cross-tenant rows in `state.db`. Gate; nothing builds until green.
2. **`kaizen/tenancy.py`** — `provision_tenant(brand_id, brand_config) -> Path`: scaffold profile dir + `config.yaml` + `honcho.json` + `SOUL.md`.
3. **`kaizen/worker.py`** — per-tenant worker: reads `HERMES_HOME` env, builds `AIAgent` with callbacks, runs `run_conversation`, emits events + result as JSON-lines.
4. **Brand Strategist agent** — onboarding: research + bounded interview → write brand profile to `SOUL.md`.
5. **Content Creator agent** — reads `SOUL.md` → generates on-brand content from a text brief.
6. (Next) publish to one real surface + eval loop.

Files to create for NOW scope: `kaizen/tenancy.py`, `kaizen/worker.py`, `kaizen/worker_pool.py`, `kaizen/personas/brand_strategist.md`, `kaizen/personas/content_creator.md`, `kaizen/tests/test_isolation.py`. No core Hermes edits.

## Models (OpenAI via API key)
Orchestrator + Eval = strongest reasoning model; Content + Brand Strategist = faster/cheaper; classification = cheapest. Set in `config.yaml` `model` block.
