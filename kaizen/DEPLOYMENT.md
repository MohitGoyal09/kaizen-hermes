# Cloud Storage & Deployment (doc-grounded)

> Answers "how does memory/state work in the cloud when Hermes is local-first, so we don't rebuild later." Grounded in the Hermes docs (memory-providers, honcho, docker). Pairs with `SPEC.md` and `BUILD_PLAN.md`.

## The fix: three storage layers, separated by ownership

The mistake that forces a rebuild is mixing these. Keep them separate:

| Layer | Stores | Where it lives | System of record |
|---|---|---|---|
| **Convex** (app DB + realtime, power-up) | users/auth, **brand config** (URL, colors, tone, connected accounts, guardrails), campaigns, generated content, posts, `eval_runs`, engagement metrics, jobs | Convex managed cloud | Product data. Frontend subscribes for the live dashboard + run tree. |
| **Honcho Cloud** (Hermes memory) | the agent's **evolving, learned memory** of a brand + user model (cross-session recall) | Honcho Cloud, one peer/workspace per tenant | Agent memory. Set `memory.provider: honcho` per profile. |
| **Hermes `HERMES_HOME` per profile** | session SQLite, learned skills, secrets, config.yaml | persistent volume at `/opt/data/profiles/<tenant_id>` | Operational state (treated as per-tenant cache; durable memory is in Honcho). |

**Two different "brand profiles", do not conflate:**
- **Structured brand config** (fields you control) → **Convex**.
- **Learned agent memory** (what the crew has figured out about the brand over time) → **Honcho**.

## Why this means no rebuild
- **Local-vs-cloud solved:** durable memory → Honcho Cloud; product data → Convex; the Hermes local dir is just per-tenant operational cache on a volume.
- **Scale with zero app change:** profiles add as supervised services (Hermes Docker s6 runs one profile per tenant natively). Later, move a hot tenant to a Modal/Daytona serverless backend by setting its `HERMES_HOME`/env, no code change.
- **Crash safety:** if the container dies, Honcho (memory) + Convex (data) survive; only in-flight sessions are lost. Nothing irreplaceable is on the box.

## Deployment topology

```
Frontend (Cloudflare Pages / Vercel)         ← deployed link the judges open
      │  HTTPS (Convex realtime for dashboard)
      ▼
Convex (managed)  ◄──────── FastAPI control plane ────────► Hermes container
  app data + auth            • auth, derive tenant_id         nousresearch/hermes-agent
  + realtime UI              • job queue + worker routing      s6: one profile per tenant
                             • tool endpoints (X/blog MCP,      /opt/data on persistent volume
                               Linkup)                          memory.provider = honcho (cloud)
                                                                       │
                                                                       ▼
                                                               Honcho Cloud (memory, per-tenant peer)
```

- **Deployed link** = the Cloudflare/Vercel frontend URL → FastAPI → Hermes.
- Hermes as one container hosting all tenant profiles (docs-recommended). FastAPI + Convex + Honcho are separate managed/cloud services.

## Isolation: Convex changes the mechanism (correction)
Convex is a document/reactive DB, not Postgres, so the earlier "Postgres RLS" becomes: **every Convex query/mutation derives `tenant_id` from the authenticated Convex identity and filters on it; a client-passed tenant is never trusted.** Same rule (SPEC R7), Convex mechanism (auth + per-function tenant checks) instead of SQL RLS.

## Config to set (doc-grounded)
- **Per tenant profile:** `memory.provider: honcho` in `config.yaml`; `honcho.json` in that profile's `HERMES_HOME` with Honcho **Cloud** base URL + API key. Each tenant = a distinct Honcho peer/workspace (`hermes honcho peer` / `honcho map`).
- **Docker:** `docker run -v <persistent-disk>:/opt/data nousresearch/hermes-agent gateway run`; profiles under `/opt/data/profiles/<tenant_id>`.
- **Convex:** schema for the tables above; auth issues the session token; FastAPI reads `tenant_id` from it.

## Cloud spikes to run first (verify, do not assume)
1. **Honcho multi-tenant + durability:** two profiles → two Honcho peers → write memory in each → assert isolation in Honcho, and that memory survives a container restart (proves cloud durability, not local disk).
2. **Convex tenant scoping:** an authed query for tenant A cannot read tenant B's rows.
3. **Deployed smoke:** one real post triggered from the deployed URL, with the run visible in observability.

## Sources
- Hermes memory providers: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers/
- Hermes + Honcho: https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho
- Hermes Docker: https://hermes-agent.nousresearch.com/docs/user-guide/docker
- Honcho integration guide: https://honcho.dev/docs/v3/guides/integrations/hermes
