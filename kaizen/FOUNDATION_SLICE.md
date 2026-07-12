# Foundation Slice — Build Spec (LOCKED, approved 2026-07-12)

> The buildable spec for the first slice: **auth → tenancy/provisioning → memory (Honcho Cloud) → FastAPI → onboarding (Brand Strategist writes the brand profile)**. Pairs with `SPEC.md` (tenancy rules), `CODE_GROUNDED_PLAN.md` (Hermes `file:line` facts), `DEPLOYMENT.md` (cloud storage), `FEATURES_AND_AGENTS.md` (roster). Where this and older docs disagree, **this doc wins** for the foundation slice.
>
> **Ground rule (unchanged):** no edits to core Hermes source. Everything under `kaizen/` and `convex/`.

## 0. Locked decisions (from approval)

| Decision | Call |
|---|---|
| Brand profile storage | **Convex = system of record**, projected to **`SOUL.md` + `AGENTS.md`** in `HERMES_HOME` (the split model). |
| Auth | **Convex Auth issues JWT → FastAPI verifies via JWKS → `tenant_id = claims.subject`**. Client-supplied brand_id is a hint that must equal the token tenant, else `403` (SPEC R7). |
| Memory provider | **Honcho Cloud now.** `memory.provider: honcho`, per-tenant workspace/peer. |
| First slice | **Foundation slice** (this doc). No publishing yet. |
| Deployment arc | **A (volume) now → B (render-on-start, stateless) prod → C (Modal/Daytona per-tenant) scale.** Unified by one abstraction: `render_home`. |

## 1. Separation of concerns

```
Convex (SoR, structured)        Honcho Cloud (learned memory)      HERMES_HOME (per-tenant cache, DISPOSABLE)
 ├─ users / auth (JWT issuer)    ├─ one workspace/peer per tenant    ├─ state.db   (isolated — Phase 0 ✅)
 ├─ brandProfile  ──render_home──┼─────────────────────────────────► ├─ SOUL.md    (identity + hard guardrails)
 ├─ campaigns / posts            │   what agents LEARN over time       ├─ AGENTS.md  (editable brand DNA)
 ├─ jobs / eval_runs             │                                     ├─ config.yaml + honcho.json
 └─ engagement                   └─ memory.provider: honcho            └─ skills/    (synced from repo)
        ▲                                                                     ▲
        └──── sync-back after run ──── FastAPI control plane ── run_conversation ┘
                    auth (verify JWT) · tenant router · jobs · SSE
```

**Ownership rule:** structured config you edit → **Convex**; what the agent learns → **Honcho**; what Hermes reads/writes at runtime → **files in `HERMES_HOME`** (a rebuildable projection, never a source of record).

## 2. The pinned abstraction — `render_home`

```python
def render_home(brand_profile: BrandProfile, dest: Path) -> None:
    """Read canonical brand config and materialize a HERMES_HOME.
    Writes SOUL.md (identity + guardrails), AGENTS.md (editable brand DNA),
    config.yaml (model + memory.provider: honcho), honcho.json (per-tenant
    workspace). Idempotent. This ONE function serves all deployment models:
      • Approach A: called at provision time onto a persistent volume.
      • Approach B: called at worker cold-start onto scratch (stateless).
      • Approach C: called inside a Modal/Daytona per-tenant env.
    A→B→C requires NO agent-code change — only WHERE/WHEN render_home runs.
    """
```

## 3. Brand profile read/write model (agent edits the file directly)

Hermes agents have `read_file`/`write_file` tools (`tools/file_tools.py`), and the worker runs with `cwd=$HERMES_HOME`, so the agent edits `SOUL.md`/`AGENTS.md` in place.

- **During a run:** the file is authoritative. The Brand Strategist writes brand DNA straight into `AGENTS.md`.
- **After a run:** the backend **reconciles file → Convex** (read the file, upsert `brandProfile`) so Convex stays durable + queryable.
- **On cold-start / new box / profile edit via UI:** `render_home` writes Convex → file. Idempotent; a restart always rebuilds the correct files.
- **`state.db` is disposable** — Honcho is the memory SoR, Convex is the data SoR. Nothing irreplaceable lives in `HERMES_HOME`.

> ⚠️ `AGENTS.md` is read from the worker's **cwd**. The repo root has a 71 KB Hermes `AGENTS.md`; the worker **must** run with `cwd=$HERMES_HOME` or it reads the wrong file. Hard requirement in `worker.py`.

## 4. Auth design

1. Frontend logs in via Convex Auth → receives a signed session **JWT**.
2. Every FastAPI request carries `Authorization: Bearer <jwt>`.
3. `auth.py` verifies the JWT against Convex **JWKS** (issuer + `kid`), derives `tenant_id = claims["sub"]` **server-side**.
4. A client-supplied brand_id is only a hint; if it ≠ token tenant → `403`.
5. One user = one brand = one tenant for the demo.

## 5. Files to create (no core Hermes edits)

```
kaizen/
  profile.py          BrandProfile dataclass (frozen) + render_soul() + render_agents() + parse_agents() (file→profile)
  tenancy.py          provision_tenant(brand_id, profile) -> Path; render_home(); write config.yaml + honcho.json; sync skills
  worker.py           per-tenant worker: HERMES_HOME env + cwd=HERMES_HOME; AIAgent + callbacks; run_conversation; JSON-lines events
  worker_pool.py      spawn-per-tenant + reuse + idle-evict; subprocess.Popen(env=..., cwd=...)
  auth.py             verify_convex_jwt(token) -> tenant_id  (JWKS fetch+cache, issuer/aud checks, 403 paths)
  api/
    main.py           FastAPI app; job model {job_id, tenant_id, type, status, events[]}; SSE
    deps.py           auth dependency -> tenant_id; tenant-hint guard
    routes_brands.py  POST /v1/brands ; GET /v1/brands/{id} ; POST /v1/brands/{id}/onboard
    routes_jobs.py    GET /v1/jobs/{id} ; GET /v1/jobs/{id}/stream (SSE)
  personas/
    orchestrator.md   manager persona
    brand_strategist.md  research URL + ≤5 bounded questions + write brand DNA to AGENTS.md
  tests/
    test_isolation.py           ✅ GREEN (Phase 0 gate)
    _tenant_probe.py            ✅ helper
    test_tenancy.py             provision creates correct dirs/files at correct paths
    test_profile_projection.py  BrandProfile → SOUL.md/AGENTS.md render; AGENTS.md → BrandProfile parse (round-trip)
    test_auth.py                JWKS verify with a synthetic keypair; tampered token → 403; tenant-hint mismatch → 403
    test_onboarding.py          Brand Strategist writes brand DNA to AGENTS.md (LLM mocked)
convex/
  schema.ts           brands, brandProfile, campaigns, posts, jobs, eval_runs, engagement — all tenant-scoped
  auth.config.ts      Convex Auth config (JWT issuer)
  brands.ts, profile.ts, jobs.ts   tenant-scoped queries/mutations; identity derived server-side; client tenant never trusted
```

## 6. Data flow — onboarding (slice payoff)

1. Frontend login (Convex Auth) → JWT.
2. `POST /v1/brands {url}` → verify JWT → `tenant_id` → `provision_tenant()` scaffolds `HERMES_HOME` + skeleton `brandProfile` in Convex → `render_home` → `{brand_id}`.
3. `POST /v1/brands/{id}/onboard` → enqueue job → tenant worker runs **Brand Strategist**: research URL → ≤5 bounded questions → write brand DNA into `AGENTS.md`.
4. Backend reconciles `AGENTS.md` → Convex `brandProfile`.
5. `GET /v1/jobs/{id}/stream` (SSE) shows the live run tree; final report returned.

## 6a. Streaming architecture (callbacks → IPC → SSE)

Hermes is the harness — agents/skills/tools are declarative — but observability is **not** a passthrough. `run_conversation` is synchronous and returns no `events` key; run visibility comes from **`AIAgent` constructor callbacks** (`step_callback`, `tool_start_callback`, `tool_complete_callback`, `event_callback`) + `stream_callback` for text deltas (`conversation_loop.py`, `tool_executor.py`). Because tenancy is **process-per-tenant**, the worker is a subprocess, so events cross a process boundary:

```
AIAgent callbacks (worker subprocess)
   → JSON-lines on stdout / Redis pub-sub      ← IPC (worker.py emits)
      → FastAPI SSE endpoint (routes_jobs.py)
         → frontend renders (tool tree + token stream)
```

- **worker.py** wires all constructor callbacks → serializes each event to one JSON line → stdout (Wave-1/2) or Redis pub-sub (prod).
- **routes_jobs.py** `/v1/jobs/{id}/stream` tails the job's event stream → SSE.
- Two channels: structured **tool/step events** (the run tree, 7× observability) and **text deltas** (the assistant reply).
- Final trajectory (post-hoc) via `agent._convert_to_trajectory_format(...)` (`run_agent.py:1952`).

**What Hermes does NOT provide (our net-new API layer):** auth (Convex JWT→tenant_id) · multi-tenancy (provision + worker pool + `render_home`) · job control · Convex sync · this streaming path. Defining the specialists/skills/tools is declarative and cheap; the tenancy + streaming plumbing is the real backend work.

## 7. Build order & sub-agent dispatch (Opus-class agents; TDD each)

- **Wave 1 (parallel, no live creds needed):**
  - **A** — `profile.py` + `tenancy.py` (incl. `render_home`) + `test_tenancy.py` + `test_profile_projection.py`.
  - **B** — `convex/` schema + auth config + tenant-scoped functions.
  - **C** — `auth.py` + `test_auth.py` (synthetic keypair; no live JWKS).
- **Wave 2 (parallel, after Wave 1):**
  - **A** — `worker.py` + `worker_pool.py` (cwd=HERMES_HOME; Honcho wired).
  - **D** — FastAPI `main.py` + `deps.py` + routes + job model + SSE.
- **Wave 3:** Brand Strategist persona + onboarding endpoint wired end-to-end + `test_onboarding.py`.

Each sub-agent is given: the grounded `file:line` facts, the "no core Hermes edits" rule, and a TDD requirement (write + run tests green). Waves reviewed before proceeding.

## 8. Prerequisites (live integration only — not blocking Wave 1)
- **Convex** deployment URL + deploy key (`npx convex dev`) and the **JWKS/issuer URL** for `auth.py`.
- **Honcho Cloud** API key + base URL (`HONCHO_API_KEY`, `HONCHO_BASE_URL`).
- **OpenAI** API key (model, per `GETTING_STARTED.md`).
- Frontend owner confirms the `SPEC §5` API contract.

## 9. Testing gates
- Phase 0 isolation: ✅ green (`kaizen/tests/test_isolation.py`, 3/3).
- Wave 1: `test_tenancy`, `test_profile_projection`, `test_auth` green (mocks/synthetic — no creds).
- Wave 3: `test_onboarding` green (LLM mocked); then one live onboarding run once creds are in.
