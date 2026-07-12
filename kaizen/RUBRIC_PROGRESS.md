# Rubric Progress — Kaizen x Hermes (shared team source of truth)

> **Track 03 · AI as Agency · 164 base + uncapped real-output overflow.**
> Living doc — update it whenever a level changes. This is the single place the whole team (Maaz, Mohit, Diya, Adil) reads to stay at the same pace.
> Last updated: **2026-07-12**. Pairs with `FOUNDATION_SLICE.md`, `SPEC.md`, `FEATURES_AND_AGENTS.md`.

## North star
**Get ONE real working demo ASAP** — a completed declared job that lands a real artifact on a real surface, fully observable — then keep pushing the other rubrics. The 20x working-output parameter is 80/164 (49%) **plus uncapped overflow**, so it dominates. Nothing scores until a task completes live.

---

## Scoring model
Per parameter: **L1 = 0 · L2 = 1×w · L3 = 2×w · L4 = 3×w · L5 = 4×w**. (Validates: 80+20+28+20+8+4+4 = 164.)
The rubric is verified by a mentor **re-running the task and reading the trace** — points come from *working, observable behavior*, not from code existing.

---

## Scorecard

| Parameter | Weight / max | **Hermes gives us (baseline)** | Now (honest) | Target | What unlocks the target | Owner |
|---|---|---|---|---|---|---|
| **Working output shipping** | 20x / **80** +overflow | Agent runtime, tool calls, MCP client, file tools = the execution engine | **L1 = 0** | **L4→L5** (60–80+) | Complete the declared job end-to-end and **land a real artifact on a real surface** (blog/X). Staged = L3 ceiling; real + human-approved = L4; autonomous ×3 runs = L5. Overflow: +1×20 per extra real task done live. | Maaz + Mohit |
| **Observability** | 7x / **28** | Constructor callbacks (`step`/`tool_start`/`tool_complete`/`event`), `stream_callback`, trajectory format, `save_trajectories` JSONL | **L1 = 0** (plumbing only) | **L4→L5** (21–28) | **Event-by-event streaming** (callbacks → JSON-lines → SSE) → a **trace tree with tokens+cost per step**, filter, diff two runs, cost-spike alert. Closest to easy points. | Mohit |
| **Agent org structure** | 5x / **20** | `delegate_task` subagent spawning, per-role `AIAgent` with scoped toolsets | **L1 = 0** (roles defined, not run) | **L4→L5** (15–20) | Trace shows the **manager dynamically planning per request** + bouncing a bad draft back (L4); manager **spawns a specialist on the fly** (L5). Needs proper orchestration. | Mohit |
| **Evaluation + iteration** | 5x / **20** | Trajectory capture = raw material for eval cases | **L1 = 0** | **L4→L5** (15–20) | Named eval set → CI-style gate blocks a release on quality drop → **failed/low-engagement runs auto-become eval cases**, pass rate climbing v1→v4, prompts version-controlled. | Mohit |
| **Handoffs + memory** | 2x / **8** | Honcho provider (per-tenant workspace), SOUL.md + AGENTS.md auto-read, `user_profile` | **L1 = 0** (Honcho configured, not live) | **L5** (8) | Our 3-layer design (now / brand's past / brand rules) already *is* L5 — the **self-learning flywheel** (below) demonstrates it live. Cheapest max. | Mohit |
| **Cost / latency** | 1x / **4** | Model routing, fallback chains, cheap-model config | unmeasured | **L4** (3) | Timed live run 1–5 min / $0.10–0.50; cheap model for classification, strong model only for final copy. | Maaz |
| **Management UI** | 1x / **4** | Hermes dashboard / web_server (dev-grade) | **L1 = 0** | **L3→L4** (2–3) | Brand dashboard: non-eng assigns a campaign, watches SSE run tree, approves publish, edits a prompt, re-runs. | Diya |

**Current demonstrated total: ~0 / 164.** Realistic target with the plan: **~130–150 + real-output overflow.**

---

## What Hermes already provides (so we don't rebuild it)
Hermes is the harness — a large share of the rubric infrastructure is inherited, which is why we can move fast:
- **Execution engine** — `AIAgent.run_conversation`, tool calling, MCP client, file read/write, skills. (working-output engine)
- **Sub-agents / org** — `delegate_task` spawns isolated child agents in-process; we build per-role `AIAgent`s with scoped toolsets on top. (org structure)
- **Observability primitives** — live callbacks + `_convert_to_trajectory_format` + JSONL trajectories. We add the *viewing surface* (trace tree + cost + diff). (observability)
- **Memory** — native Honcho provider (per-tenant workspace/peer), SOUL.md + AGENTS.md auto-read into every turn, user profile. We add the *self-learning loop*. (memory)
- **Cost controls** — model routing + fallback chains. We tune tiers. (cost)
- **Multi-tenancy is NOT provided** — process-per-tenant isolation, provisioning, worker pool, auth, Convex sync, control-plane API, and the real-surface publishing are **our** net-new work (and our differentiator).

Rule for judging: Hermes must **visibly do real work** in the trace (per-tenant memory + orchestration), not be a thin wrapper.

---

## The self-learning memory flywheel (our "self-reliant" story)
This is what makes **memory L5** and **eval L5** at once, and it's the moat vs generic generators.

```
 Content Creator ──generates──► Publisher ──posts──► REAL surface (X / blog)
      ▲ reads learned patterns                              │
      │ (Honcho)                                            │ later
      │                                                     ▼
 Honcho (learned memory) ◄──writes pattern── Performance Observer / Eval
      "for this brand: short hooks + question CTAs           │ fetches real
       outperform; posts at 9am do best"                     │ engagement + attributes
                                                             │ it to content attributes
                                                             ▼
                                              Convex (raw metrics + post history)
```

**How we store the self-reliant part (the key decision):**
- **Learned patterns / insights = Honcho** (per-tenant peer/workspace). This is the durable, evolving "what works for this brand" memory. Hermes reads/writes it natively every turn (`memory.provider: honcho`) — **Hermes works as-is; Honcho carries the self-learning layer.**
- **Raw engagement metrics + post history = Convex** (queryable data, feeds the dashboard + the eval set).
- **Editable brand config (voice/guardrails) = Convex → projected to SOUL.md/AGENTS.md** (what the agent reads as constraints).

**The loop, concretely:**
1. Content Creator generates, reading brand DNA (SOUL/AGENTS) **+ learned patterns (Honcho)**.
2. Publisher posts to a real surface.
3. A **Performance Observer** (folded into Eval/Scorer) later pulls real engagement, attributes performance to content attributes (format, tone, hook, topic, timing).
4. It writes the learned pattern to **Honcho** ("this brand's short punchy hooks outperform") and low performers become **new eval cases** in Convex.
5. Next generation biases toward what works → **content improves across versions**. Self-learning, demonstrable v1→v4.

This directly satisfies: **memory L5** (now + brand's past + rules), **eval L5** (closed loop, failures become cases, gains across versions), and feeds **observability**.

---

## Current build status (branch `kaizen/foundation-slice`)
- ✅ Isolation gate (process-per-tenant) — green.
- ✅ Tenancy / profile / `render_home` — built + reviewed.
- ✅ Worker + worker_pool (callbacks → JSON-lines) — dryrun-tested; **no live LLM run yet**.
- ✅ Personas (orchestrator, brand_strategist) — drafted.
- ✅ Convex — **LIVE on a local deployment** (`127.0.0.1:3210`, site `:3211`). Functions deployed + verified via MCP (`tables`/`functionSpec`); `@convex-dev/auth` JWKS serving (RS256, `curl` 200); **R7 fail-closed verified live**; `CONVEX_*` written to root `.env`. Backend runs via `cd convex && CONVEX_AGENT_MODE=anonymous npx convex dev` (must stay up). Cloud/dashboard = one `npx convex login` later.
- ✅ auth.py (JWKS verify) + FastAPI control plane + SSE — built, **59 tests green**; **security-reviewed: auth sound, no bypass** (alg pinned, iss/aud/exp enforced, fail-closed, R7 verified).
  - Routes: `POST /v1/brands`, `GET /v1/brands/{id}`, `POST /v1/brands/{id}/onboard`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/stream` (SSE). Documented in `API.md` + `BACKEND_HANDOFF.md`.
- ✅ **FIRST LIVE LLM RUN WORKS** (2026-07-12) — Brand Strategist researched a real URL via web tools and wrote brand DNA to `AGENTS.md` on **OpenAI `gpt-5-mini`** (`openai-api` provider), streamed step/text/final events. First real completed task → off 0.
- ❌ Still pending: **published** real output (the 20x post), observability UI, eval loop, mgmt UI, live Honcho verification, Convex→Cloud, the remaining specialist agents.

---

## Immediate path to the first real demo (in order)
1. **Finish + review** the FastAPI/auth agent (in flight). *(Mohit)*
2. **`npx convex dev`** → link deployment; push schema; `envSet` JWT keys via Convex MCP. *(Mohit + user login)*
3. **Drop creds into `.env`** — `OPENAI_API_KEY`, `HONCHO_*`, `CONVEX_*`. *(user)*
4. **First live onboarding run** — brand URL → Brand Strategist → writes SOUL.md/AGENTS.md → sync to Convex, over SSE. Banks **memory** + starts **org/obs**. *(Mohit)*
5. **Thinnest real-output slice** — orchestrator → content → **publish to a real surface** (staged→real). This is the **20x floor → L4**, the make-or-break for the demo. *(Maaz + Mohit)*
6. Then climb: observability trace-tree+cost (L4) → eval closed loop + dynamic manager (L4→L5) → demonstrate the self-learning flywheel (memory/eval L5) → mgmt UI + cost tuning.

**Do not build all six agents before the first real post exists. Step 5 is make-or-break.**
