# Kaizen Backend — Handoff & Integration Context

> **Read this first.** Full context for anyone (human or agent) picking up the Kaizen backend to run it, understand it, or wire a frontend to it. The frontend lives in a **separate repo**; this doc + `kaizen/API.md` are the contract. Last updated 2026-07-12.

## What this is
A **multi-tenant AI marketing agency** built on the Hermes agent. A brand signs up → an onboarding agent researches the brand and builds its profile → (next) a crew of agents generates and publishes on-brand content and measures it. Multi-tenancy (one isolated `HERMES_HOME` per brand, process-per-tenant) is the differentiator and is proven green.

## Architecture (three storage layers, separated by ownership)
```
Frontend (separate repo)                    ← Convex Auth login + dashboard
   │  Bearer JWT (from Convex Auth)
   ▼
FastAPI control plane  (kaizen/api/)         ← THE backend the frontend calls
   │  verifies JWT via Convex JWKS → tenant_id
   ▼
Hermes worker per tenant (kaizen/worker.py)  ← runs agents, streams events
   ├─ Convex  : structured system-of-record (brands, profiles, jobs) + AUTH ISSUER
   ├─ Honcho  : durable per-tenant learned memory
   └─ HERMES_HOME/<brand>/ : SOUL.md + AGENTS.md (brand DNA) + state.db (disposable cache)
```

## Repo layout
- `kaizen/api/` — FastAPI app (`main.py`, `deps.py` = auth boundary, `routes_brands.py`, `routes_jobs.py`, `job_store.py`, `brand_store.py`, `convex_sync.py`).
- `kaizen/auth.py` — Convex JWT verification (JWKS).
- `kaizen/tenancy.py`, `profile.py`, `worker.py`, `worker_pool.py` — tenancy + Hermes runtime.
- `kaizen/personas/` — agent system prompts.
- `convex/` — Convex project: `convex/convex/*.ts` (schema, auth, http, brands, profile, jobs).
- Docs: `API.md` (routes), `RUBRIC_PROGRESS.md` (status), `FOUNDATION_SLICE.md`, `SPEC.md`.

---

## 🔑 AUTH — how frontend login connects to the backend

**One identity, issued by Convex Auth, used by both Convex and the FastAPI backend.** There is no separate backend login — the frontend's Convex Auth token IS the backend's token.

### The flow
```
1. User logs in on the FRONTEND via Convex Auth (@convex-dev/auth, Password provider today).
   Convex issues a signed JWT (RS256), served from CONVEX_SITE_URL/.well-known/jwks.json.

2. The frontend now holds that JWT. It uses the SAME token two ways:
   (a) Convex queries/mutations  → automatic (ConvexAuthProvider attaches it;
       Convex functions read identity via ctx.auth.getUserIdentity()).
   (b) FastAPI backend calls      → the frontend MANUALLY attaches it:
       Authorization: Bearer <jwt>

3. FastAPI (kaizen/auth.py + deps.require_tenant) verifies the JWT against Convex's
   JWKS (iss + aud + exp + signature), and derives tenant_id = claims["sub"].
   → tenant_id is ALWAYS server-derived from the token, never trusted from the client (SPEC R7).
```

So: **log in once (Convex Auth) → the resulting JWT authenticates the frontend to BOTH Convex directly AND our FastAPI backend.** Same `sub` = same `tenant_id` everywhere.

### What the FRONTEND must implement
1. Wrap the app in `ConvexAuthProvider` (from `@convex-dev/auth/react`) with the Convex client (`CONVEX_URL`).
2. Render a sign-in form; call `signIn("password", { email, password, flow })` (from `useAuthActions`). This is the "login material" — Convex Auth handles credential storage in the `authTables` we already deployed.
3. To call our FastAPI backend, get the JWT and attach it:
   ```js
   import { useAuthToken } from "@convex-dev/auth/react";
   const token = useAuthToken();              // the JWT to send to FastAPI
   fetch(`${API_URL}/v1/brands`, {
     method: "POST",
     headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
     body: JSON.stringify({ url }),
   });
   ```
4. For the SSE stream, use `fetch()` (not `EventSource`) so you can send the Bearer header — see `API.md`.

### What the BACKEND already provides
- Convex Auth is wired (`convex/convex/auth.ts` Password provider, `http.ts` routes, `auth.config.ts`), JWKS is live, and FastAPI verification (`kaizen/auth.py`) is security-reviewed (alg pinned RS256, iss/aud/exp enforced, fail-closed, no cross-tenant leak). Nothing else is needed backend-side for login to work.

---

## How to run locally
```bash
# 1. Convex (functions + auth issuer + JWKS). Keep this running.
cd convex && CONVEX_AGENT_MODE=anonymous npx convex dev     # local; or `npx convex dev` for cloud (logged in)

# 2. Env: fill /Users/…/hermes-agent/.env  (git-ignored) — see the table below.

# 3. FastAPI backend
cd /path/to/hermes-agent
uvicorn kaizen.api.main:app --host 127.0.0.1 --port 8000 --reload

# 4. Tests
python3 -m pytest kaizen/tests/ -v        # 59 green
```

## Environment variables (root `.env`, git-ignored)
| Var | Who fills | How to get it |
|---|---|---|
| `OPENAI_API_KEY` | you | platform.openai.com (buildathon OpenAI perk) |
| `HERMES_INFERENCE_PROVIDER` | fixed | `openai-api` (NOT `openai` — that id is invalid in Hermes) |
| `HERMES_INFERENCE_MODEL` | fixed | `gpt-5-mini` (works with OpenAI Responses/codex mode; `gpt-4o-mini` needs `chat_completions` forced) |
| `HONCHO_API_KEY`, `HONCHO_BASE_URL` | you | honcho.dev Cloud dashboard |
| `CONVEX_URL`, `CONVEX_SITE_URL`, `CONVEX_DEPLOYMENT` | Convex CLI | written to `convex/.env.local` by `npx convex dev`; mirror into root `.env` |
| `CONVEX_JWT_ISSUER` | = `CONVEX_SITE_URL` | JWT `iss` FastAPI verifies |
| `CONVEX_JWKS_URL` | = `CONVEX_SITE_URL/.well-known/jwks.json` | JWKS FastAPI fetches |
| `CONVEX_JWT_AUDIENCE` | fixed | `convex` |
| `KAIZEN_PROFILES_DIR` | default ok | per-tenant `HERMES_HOME` base dir |
| `KAIZEN_API_HOST`, `KAIZEN_API_PORT` | default ok | `127.0.0.1` / `8000` |

**Frontend env (separate repo):** `VITE_CONVEX_URL` / `NEXT_PUBLIC_CONVEX_URL` = `CONVEX_URL` (to init the Convex client), and an `API_URL` pointing at the FastAPI base.

## The API
See **`kaizen/API.md`** — 5 routes: `POST /v1/brands`, `GET /v1/brands/{id}`, `POST /v1/brands/{id}/onboard`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/stream` (SSE). All Bearer-authenticated.

## Current status (2026-07-12)
✅ Isolation gate · tenancy · worker · FastAPI + auth (59 tests green) · Convex live locally (functions + JWKS + R7 verified) · **first live onboarding run works** (Brand Strategist → `AGENTS.md` on `gpt-5-mini`).
🟡 Pending: Convex → Cloud migration · CORS (deferred) · full HTTP end-to-end API test · Honcho live verification · the remaining specialist agents (competitor, content, publisher, eval).

## Frontend integration checklist
1. Init Convex client with `CONVEX_URL`; wrap in `ConvexAuthProvider`.
2. Build sign-in (Password provider) — login works against the deployed `authTables`.
3. Get the JWT via `useAuthToken()`; send it as `Bearer` to the FastAPI `API_URL`.
4. Use `fetch()`-based SSE for `/v1/jobs/{id}/stream` (not `EventSource`).
5. (Backend TODO before deployed frontend) enable CORS for your origin + move Convex to Cloud.
