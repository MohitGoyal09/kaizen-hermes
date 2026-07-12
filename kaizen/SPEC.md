# Kaizen x Hermes — Multi-Tenant AI Marketing Agency

**Team:** Kaizen (Maaz, Mohit, Diya, Adil)
**Event:** GrowthX Hermes Buildathon — track: **AI as Agency**
**Base:** Nous Research Hermes Agent (private fork: `MohitGoyal09/kaizen-hermes`, upstream `nousresearch/hermes-agent`)
**Status:** spec v1, ready for team split. Not final; the isolation spike (Section 8) gates everything.

---

## 1. What we are building

An **AI marketing agency** that a brand hires instead of a human team. A brand owner connects their product/site; a crew of agents produces a brand profile, generates on-brand content, **publishes to real channels**, then **measures real engagement and improves the next round**. The differentiator vs generators like Pomelli and LocalAds is the closed loop: we don't stop at assets, we ship and self-grade.

**Why it fits the track:** the Agency rubric scores real output shipping (20x), observability (7x), and evaluation (5x). A real posted artifact + a grounded eval loop is exactly those three, and the two heavy ones (obs + eval = 42 pts) are what most teams skip.

---

## 2. Hackathon scope (read this before building)

| Decision | Call |
|---|---|
| Multi-tenant architecture | **Yes, from line one.** `brand_id` scoping + per-brand Hermes home. It's our differentiator and judges test concurrent use. |
| Number of brands in demo | **2-3 seeded brands.** Enough to prove isolation live. |
| Autoscaling / k8s / horizontal scale | **No.** Single VPS, in-process tenancy. Scale is a slide (Section 6, Tier 3), not code. |
| Channels for live posting | **X + Telegram + a blog** (writable APIs). FB/Insta/LinkedIn = publish-ready drafts, disclosed as drafts. |
| Content formats | **Text + image + brand voice (ElevenLabs audio).** Video = stretch, not core. |
| Auth | **Lightweight** brand token, not full auth/RBAC. |

**Rule of thumb:** correct isolation for 2-3 brands beats fake scale for zero. One real posted artifact beats four fake channel integrations.

---

## 3. System architecture

```
Frontend (landing page + brand dashboard)
        │  HTTPS
        ▼
FastAPI control plane  ──────────────────────────────────┐
  • brand auth / tenant router (brand_id)                 │
  • job queue + worker pool (concurrency)                  │
  • per-brand Hermes home override (isolation)             │
  • tool endpoints (post, competitor search, eval capture) │
  • metering (pay-per-use)                                 │
        │                                                  │
        ▼                                                  │
Hermes runtime (per-brand context)                         │
  • orchestrator agent (plans, delegates)                  │
  • specialist subagents (Section 7)                       │
  • skills + MCP tools + cron                              │
        │                                                  │
        ▼                                                  ▼
Postgres (brand_id-scoped)          Per-brand HERMES_HOME dirs
  brands, campaigns, posts,           /data/hermes/profiles/<brand_id>/
  eval_runs, engagement, jobs         (SQLite + memory + skills, isolated)
```

The frontend never talks to Hermes directly. Everything goes through FastAPI, which is the multi-tenant layer Hermes does not have.

---

## 4. Multi-tenancy design (the core)

Hermes stores all state (SQLite sessions, memory markdown, skills) through one function, `get_hermes_home()` in `hermes_constants.py`. Its resolution order is: **ContextVar override → `HERMES_HOME` env → `~/.hermes`**. Nous ships the scoping API:

```python
from hermes_constants import set_hermes_home_override, reset_hermes_home_override

token = set_hermes_home_override(f"/data/hermes/profiles/{brand_id}")
try:
    # run the Hermes agent — its SQLite, memory, skills all resolve to THIS brand
    ...
finally:
    reset_hermes_home_override(token)
```

- It's a **ContextVar**, so concurrent async requests each carry their own brand's home with **zero cross-bleed, in one process**. Its docstring: "for in-process, per-task scoping... does not mutate os.environ because that is shared by every thread."
- Physical isolation: separate dirs = separate SQLite + memory + skills. **Brand A cannot read Brand B**, by construction, not by a WHERE clause.
- Postgres rows also carry `brand_id` as an FK, and every query filters on it. Two layers of isolation.

**Isolation guarantee we will demo:** two brands running at the same time, and we open both SQLite stores live to show no shared rows.

### Auth and tenant resolution (LOCKED)

1. User logs in on the frontend, backend issues a signed session token (JWT or httpOnly session cookie).
2. Every API request carries the token. FastAPI validates it and derives `tenant_id` (the user's brand) from the token claims **server-side**.
3. The client **never** sends a trusted `user_id`/`brand_id`. If the frontend includes one, it is treated only as a hint that must equal the token's tenant, else `403`. Auth identity comes only from the validated token.
4. FastAPI runs the agent inside `set_hermes_home_override(profiles/<tenant_id>)`. The agent therefore has access to exactly one tenant's memory, skills, tools, and credentials. **Brand-specificity is enforced by scope, not by prompting the agent to behave.**

Hackathon simplification: **one user = one brand = one tenant.** `user_id` and `brand_id` are the same key for the demo.

### Tenancy rules (consolidated, LOCKED)

- **R1** One profile (`HERMES_HOME`) per tenant = physical isolation wall.
- **R2** `tenant_id` on every Postgres row; all queries filter by it.
- **R3** Tool/MCP credentials (the brand's X account, etc.) scoped per tenant, never shared.
- **R4** Subagents share the tenant's memory; they are not separate profiles.
- **R5** No Hermes call outside `set_hermes_home_override(tenant)`; always `reset` after.
- **R6** Nothing reaches Hermes except through FastAPI.
- **R7** `tenant_id` is derived from the validated auth token only, never from a client-supplied field. ("Frontend sends a user_id we trust" = anyone reads anyone's data. Forbidden.)
- **R8** (optional) Cloud memory (Honcho / Hindsight) = one workspace per tenant, keyed server-side, layered *inside* the wall. An enhancement, not the wall.

---

## 5. API layout

All routes are tenant-scoped by a `brand_id` derived from the brand token. Long work is async: enqueue, return `job_id`, stream progress.

```
POST /v1/brands                      → create brand, kick off Business-DNA build
GET  /v1/brands/{id}                  → brand profile + status
POST /v1/brands/{id}/campaigns        → enqueue campaign job → {job_id}
GET  /v1/jobs/{job_id}                → job status
GET  /v1/jobs/{job_id}/stream         → SSE run events (for observability panel)
POST /v1/brands/{id}/posts/{pid}/publish → publish a specific piece to a channel
GET  /v1/brands/{id}/posts            → posts + eval scores + real engagement
GET  /v1/brands/{id}/runs/{run_id}    → agent run trace (org tree, tool calls, cost)
```

- **Job model:** `{job_id, brand_id, type, status: queued|running|done|failed, events[]}`. Workers pull jobs; each worker sets the brand home override for the job's `brand_id`.
- **Streaming:** SSE from the job's event log powers the live run-tree + eval panel (the 7x observability parameter).
- **Metering:** every job writes a usage row per `brand_id` (pay-per-use foundation).

---

## 6. Deployment (Hermes for multiple users)

**Hackathon deploy (do this):**
- One VPS (or Cloudflare-fronted box). Postgres + Redis (for the queue) + the FastAPI app + the Hermes runtime in one process group.
- Per-brand home dirs under `/data/hermes/profiles/<brand_id>/`.
- **Tier 1 tenancy — in-process ContextVar override** (Section 4). Lowest latency, no spawn cost. SQLite runs WAL mode (concurrent readers). This handles the demo's 2-3 concurrent brands comfortably; latency is dominated by LLM calls, not by tenancy.
- A small **worker pool (4-8)** so long jobs (generate → post → eval) run in parallel across brands.

**Scale path (slide, not code):**
- **Tier 2 — process/profile per brand:** spawn a Hermes worker per brand with `HERMES_HOME` env set. True parallelism, heavier. For when one process serializes too much CPU.
- **Tier 3 — Modal / Daytona backends** (Hermes ships these): serverless per-tenant environments that hibernate when idle and wake on demand. This is literally **pay-per-use multi-tenancy** and is our productionization story.

**Performance framing for judges:** "One box serves many brands in-process today; the same brand_id abstraction promotes each brand to its own serverless environment (Modal) for scale, with no app changes." That answers "how will it perform / scale" without us building it.

---

## 7. The agent nodes (from the whiteboard)

Hermes orchestrator plans and delegates to specialist subagents (Hermes "spawns isolated subagents for parallel workstreams"):

1. **Brand DNA agent** — reads the product URL, extracts tone/colors/fonts/positioning, writes it to brand memory (the persistent, improving profile = the moat).
2. **Competitor + hit analysis agent** — Linkup power-up: pulls competitors and their top-performing posts to set a real baseline.
3. **Content agents (per channel/format)** — text, image, brand-voice audio (ElevenLabs). On-brand quality is the bar; match LocalAds' "looks like yours," don't ship generic slop.
4. **Publisher agent** — posts to X / Telegram / blog via tool endpoints; drafts for the rest. Idempotency key per post so a retry never double-posts.
5. **Eval / scoring agent (differentiator)** — predicts performance against the real competitor baseline *before* posting, then pulls **real engagement after** and scores the prediction. Feeds results into brand memory so v2 beats v1. This is the closed loop Pomelli/LocalAds lack, and it's our 5x eval + 7x observability points.

---

## 8. First task — the isolation spike (gates everything)

The code warns that "30+ module-level callers import get_hermes_home at load time," so some paths may cache the home. **Before building anything on top, prove runtime isolation:**

- Set the override to Brand A, write a memory/session; set to Brand B, write another; concurrently.
- Assert each brand's SQLite/memory dir contains only its own data.
- If any path bleeds, that path falls back to Tier 2 (env-per-worker) for isolation.

Do not start Section 5-7 work until this passes.

---

## 9. Team split

- **Diya / frontend + brand voice:** landing page (LocalAds-style: "paste your URL, get a marketing team"), brand dashboard, run-tree + eval panel consuming the SSE stream. Own the landing page copy/brand voice.
- **Backend A (Mohit):** the tenancy layer (override + spike), eval/observability loop, Hermes agent config.
- **Backend B (Maaz):** FastAPI control plane, job queue + workers, tool endpoints (publish, Linkup), Postgres.
- **Adil:** deploy (VPS, Postgres, Redis, Cloudflare), power-up wiring (ElevenLabs, Linkup, Dodo, Cloudflare, Convex), demo prep + proof capture.

Contracts to agree first: the API in Section 5 and the job/event shape, so frontend and backend build in parallel against mocks.

---

## 10. Demo → rubric mapping

| Parameter | Weight | How we hit L4/L5 |
|---|---|---|
| Real output shipping | 20x | A real post live on X/Telegram/blog during the demo; judge opens it. |
| Observability | 7x | Live run-tree + tool calls + cost from the SSE stream. |
| Evaluation + iteration | 5x | Predict → post → measure → v2 improves, shown live. |
| Agent org structure | 5x | Orchestrator + 5 specialists with handoffs. |
| Handoffs + memory | 2x | Per-brand persistent brand profile the agents read/write. |
| Cost/latency per task | 1x | Timed live run; cheap-model routing. |
| Management UI | 1x | Brand dashboard: non-engineer assigns a campaign. |

Plus multi-tenancy shown live (two brands, isolated) = the "moat / switching cost" story for cross-track Revenue bonus.

## 11. Risks
- **Isolation spike (Section 8)** — top risk, verify first.
- **Channel write-APIs** — X/Telegram/blog only for live; rest are disclosed drafts.
- **On-brand content quality** — narrow formats, don't spread thin.
- **Hermes-in-the-loop for the rubric** — Hermes must visibly do real work (memory across a brand's runs + cron). Keep it the orchestrator, not a wrapper.
