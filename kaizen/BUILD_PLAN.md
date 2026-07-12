# Build Plan — Kaizen x Hermes AI Marketing Agency

> Rubric-driven, 8-hour team build. Pairs with `kaizen/SPEC.md`. Where this doc and the spec disagree on tenancy, **this doc wins** (see the isolation correction below).

## Verdict: is the approach good?

Yes. Auth-scoped, per-tenant-isolated multi-agent marketing agency on Hermes, with a closed eval loop, targets **L4 across the board and L5 on our strengths (observability, eval)**. Those two are 42 of the 164 base points and are what most teams leave empty. The one honest dependency: the 20x "real output" score needs a **real live post on a real surface** during judging, so the thinnest real-output slice (Phase 1) is the make-or-break.

## Rubric targets (what we aim for and how)

| Parameter | Weight | Target | How we hit it | Owner |
|---|---|---|---|---|
| Working output shipping | 20x | **L4, reach L5** | L4 = real post to a real X/blog surface, human approves publish, on the happy path. L5 = auto-publish + escalate-by-exception across 3+ runs. Marketing posts are low-stakes writes, so autonomous L5 is realistic. | Maaz + Mohit |
| Observability | 7x | **L4, reach L5** | L4 = trace tree (who called whom) + token/cost per step, filterable (Langfuse or self-hosted). L5 = diff two runs + cost-spike alert + search across runs. | Mohit |
| Agent org structure | 5x | **L4, reach L5** | L4 = manager plans subtasks per request and bounces bad drafts back (the eval agent is the reviewer). L5 = manager spawns a specialist on the fly (e.g. a video specialist when a campaign needs it). | Mohit |
| Evaluation + iteration | 5x | **L4, reach L5** | L4 = automated eval suite that blocks a "release" on quality drop. L5 = failed/low-engagement posts auto-captured as new eval cases, prompts version-controlled, pass rate climbing across versions. Our differentiator. | Mohit |
| Handoffs + memory | 2x | **L5** | Three layers per tenant: current task + this brand's past posts/performance + brand rules/guardrails. Comes free from the per-tenant brand profile. | Mohit |
| Cost/latency per task | 1x | **L4** (1-5 min / $0.10-0.50) | Cheap-model routing for classification, parallel content generation, expensive model only for final copy. | Maaz |
| Management UI | 1x | **L3, reach L4** | L3 = a PM can pause/edit-prompt/re-run from the dashboard with docs. Don't over-invest, it's 1x. | Diya |

Plus multi-tenancy shown live (two brands, isolated) for the cross-track Revenue moat bonus.

## Isolation correction (LOCKED, supersedes SPEC §6 tiers)

Code fact: `hermes_state.py:123` computes `DEFAULT_DB_PATH = get_hermes_home()/"state.db"` **at import time**. The in-process ContextVar override cannot change a value already frozen at import, so it is **not** a reliable isolation wall for the state DB on its own.

**Therefore the isolation mechanism is process-per-tenant:**
- FastAPI keeps a **worker pool**: one Hermes worker process per active tenant, launched with `HERMES_HOME=/data/hermes/profiles/<tenant_id>` in its env.
- Because the env is set before that process imports anything, *every* path (including `DEFAULT_DB_PATH`) resolves to the tenant's dir. Zero bleed by construction, no reliance on runtime overrides.
- FastAPI routes a tenant's job to its worker (spawn on first use, reuse after, evict idle). Concurrency = multiple tenant workers in parallel.
- ContextVar override stays only as a secondary optimization for genuinely runtime-resolved paths; never trusted alone.

This is also Hermes's intended pattern (its own comment: "subprocess spawner should pass HERMES_HOME explicitly").

## Phases (vertical slices, each independently demoable)

### Phase 0 — Isolation spike (GATE, ~30 min). Owner: Mohit
Prove process-per-tenant isolation before anyone builds on it.
- Launch two Hermes workers with `HERMES_HOME=/tmp/kaizen/A` and `/tmp/kaizen/B`.
- Write a session/memory in each; assert each dir's `state.db` contains only its own data and the other's is absent.
- Add the negative test: a request authenticated as A cannot read B's home.
- **Acceptance:** test green, no cross-tenant rows. If it passes (it should, by construction), Phase 1 starts.

### Phase 1 — Thinnest real-output slice. Owner: Maaz + Mohit
One tenant, one real post, fully observable. This is the 20x parameter's floor→L4.
- FastAPI `POST /v1/brands/{id}/campaigns` → enqueue job → tenant worker.
- Hermes orchestrator → one **publisher** subagent → **X (or blog) MCP** → **one real post** on a real surface.
- Capture the run in the observability tool (trace of each step).
- **Acceptance:** a real post URL exists on a real account, and the run is viewable step-by-step. Hits 20x L3→L4 + 7x L3 + org L2.

### Phase 2 — The crew + dynamic manager. Owner: Mohit
- Add specialists: **Brand-DNA** (reads product URL → brand profile in tenant memory), **competitor/hit analysis** (Linkup), **content** (text + image + ElevenLabs voice).
- Manager **plans per request** and **bounces a weak draft back** before approving.
- **Acceptance:** two structurally different campaign requests produce different plans in the trace, and at least one draft is sent back for revision. Hits org L4, memory L4→L5.

### Phase 3 — The eval loop (our edge). Owner: Mohit
- Eval agent **predicts** performance against the brand's/competitors' real baseline before posting; **measures** real engagement after; **captures** low performers as new eval cases.
- Wire the suite so a quality drop blocks a "release"; version prompts in git.
- **Acceptance:** show v1→v2 pass-rate climbing on a named eval set, and one real failure that became a new eval case. Hits eval L4→L5, obs L4→L5.

### Phase 4 — Management UI + cost tuning. Owner: Diya + Maaz
- Dashboard: brand signup, assign campaign, watch run tree (SSE), approve publish, edit a prompt, re-run. Cheap-model routing + parallel gen to keep task under 5 min / $0.50.
- **Acceptance:** a non-engineer runs a campaign end to end from the UI with docs. Hits mgmt UI L3, cost/latency L4.

### Phase 5 — Deploy + proof + demo. Owner: Adil
- One VPS: Postgres (with RLS on tenant tables), Redis (queue), FastAPI + worker pool, per-tenant home dirs. Cloudflare in front. Power-ups wired: Linkup, ElevenLabs, Dodo (paywall), Convex/Cloudflare, Wispr (500+ words dictated).
- Seed 2-3 brands. Capture proof: real post URLs, trace screenshots, eval trend chart, live-mode payment.
- **Acceptance:** the demo script below runs clean twice in a row.

## Work split (parallel from Phase 1)
- **Diya** — landing page (LocalAds-style) + brand voice + dashboard (SSE run tree, approve/edit/re-run).
- **Mohit** — tenancy (Phase 0), Hermes agent config, the eval + observability loop.
- **Maaz** — FastAPI control plane, worker pool + queue, tool endpoints (X/blog MCP, Linkup), Postgres + RLS.
- **Adil** — deploy, power-up wiring, proof capture, demo ops.

Agree the API + job contract (SPEC §5) first so frontend/backend build against mocks in parallel.

## Demo script (2 min demo, 1 min proof, 1 min Q&A)
1. Non-eng assigns a campaign for Brand A in the dashboard (mgmt UI, org).
2. Manager plans, specialists run, one draft bounced back, then a **real post lands on a real X/blog** (20x, org L4).
3. Open the run: trace tree, token/cost per step; diff a passing vs failing run (obs L4→L5).
4. Show the eval trend v1→v4 and a real failure turned into an eval case (eval L5).
5. Run Brand B **concurrently**, open both stores to prove isolation (moat + Revenue bonus).
6. Timer + trace show the task under 5 min / $0.50 (cost L4).

## Global constraints
- Track: AI as Agency. Hermes must visibly do real work (per-tenant memory + orchestration + cron) or coding-partner receipts. No Hermes, no score.
- Real live surface for the 20x post: **X or a blog** (writable APIs); other channels are disclosed drafts.
- Tenant id from auth token only, never client-supplied (SPEC R7).
- Postgres RLS on all tenant tables; per-tenant tool credentials (SPEC R3).
- Fresh-build honesty: Hermes is disclosed base; the pack + integration + eval layer are today's work.

## Top risks
1. Phase 1 real-output path (channel API + worker routing) — build first, it's the 20x floor.
2. Programmatic Hermes subagent invocation from FastAPI — confirm the exact call in Phase 1; it's the other unknown besides isolation.
3. On-brand content quality vs LocalAds — narrow formats, don't ship slop.
