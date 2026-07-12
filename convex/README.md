# convex/ — Kaizen data + auth layer

Convex is the **system of record** for structured product data (brands, brand
profile/DNA, campaigns, posts, jobs, eval runs, engagement) and is the **JWT
issuer** the external FastAPI control plane verifies against. See
`kaizen/FOUNDATION_SLICE.md` §1 and `kaizen/DEPLOYMENT.md` for how this fits
with Honcho (agent memory) and `HERMES_HOME` (per-tenant operational cache).

## Files

| File | Purpose |
|---|---|
| `schema.ts` | Tables: `brands`, `brandProfile`, `campaigns`, `posts`, `jobs`, `eval_runs`, `engagement`. Every table carries `tenantId` and is indexed `by_tenant` (or a compound index starting with `tenantId`). |
| `auth.config.ts` | Convex Auth provider config — this deployment issues the JWT. Documents the exact issuer/JWKS URL shape FastAPI must verify against (see below). |
| `brands.ts` | `createBrand`, `getBrand`, `listBrands`, `updateBrandStatus`. |
| `profile.ts` | `upsertBrandProfile`, `getBrandProfile` — the brand-DNA read/write path used by the FastAPI reconciliation step (`AGENTS.md`/`SOUL.md` file → Convex sync-back, and Convex → file on `render_home()`). |
| `jobs.ts` | `createJob`, `updateJobStatus`, `getJob`, `listJobsForBrand` — backs the `{job_id, tenant_id, type, status}` job model (`SPEC.md` §5). |

## Running locally

```bash
cd convex
npm install
npx convex dev
```

`npx convex dev` will prompt a browser login on first run, create/link a
Convex deployment, write `.env.local` with `CONVEX_DEPLOYMENT` +
`CONVEX_URL`, and generate `convex/_generated/**` (commit that directory once
it exists — it is required for the code to typecheck and run, but this
environment had no Convex login available, so it is not present yet in this
commit).

`npx tsc --noEmit -p .` typechecks `schema.ts` / `auth.config.ts` /
`brands.ts` / `profile.ts` / `jobs.ts` against the real `convex` npm package
(hand-authored stand-ins for `_generated/server.ts` + `_generated/dataModel.ts`
were used locally to prove this — see git history / PR description; they are
not part of this commit since they are normally machine-generated).

## Auth: what FastAPI needs (read this before writing `kaizen/auth.py`)

**Status: not wired yet.** `auth.config.ts` currently only declares that this
deployment trusts its own origin as an OIDC issuer:

```ts
{
  providers: [{ domain: process.env.CONVEX_SITE_URL, applicationID: "convex" }],
}
```

Verified against current Convex Auth docs (Context7 `/get-convex/convex-auth`,
2026-07-12): `auth.config.ts` alone does not make a deployment issue tokens or
serve JWKS. That requires three more pieces, none of which are in this commit:

1. `@convex-dev/auth` + `@auth/core` added to `convex/package.json`.
2. `convex/auth.ts` calling `convexAuth({ providers: [...] })` with an actual
   sign-in method chosen (password / magic link / OAuth — a product decision
   for a later commit).
3. `convex/http.ts` calling `auth.addHttpRoutes(http)` — this is what mounts
   the `/.well-known/openid-configuration` and `/.well-known/jwks.json` HTTP
   routes. Without it those paths 404 and `ctx.auth.getUserIdentity()` always
   returns `null` (every function below fails closed as "Unauthenticated",
   which is safe but not yet usable end-to-end).

Once wired, `CONVEX_SITE_URL` (this deployment's HTTP Actions origin, shaped
like `https://<deployment-name>.convex.site`, distinct from the client
`CONVEX_URL` which ends in `.convex.cloud`) will serve:

```
Issuer                : {CONVEX_SITE_URL}
OIDC discovery doc    : {CONVEX_SITE_URL}/.well-known/openid-configuration
JWKS (public keys)    : {CONVEX_SITE_URL}/.well-known/jwks.json
```

`kaizen/auth.py` (FastAPI side) must:

1. Read `CONVEX_SITE_URL` from env (same value as this deployment's site URL).
2. Fetch + cache `{CONVEX_SITE_URL}/.well-known/jwks.json` (standard JWKS:
   `{"keys": [...RS256 public keys keyed by `kid`...]}`).
3. Verify the `Authorization: Bearer <jwt>` on every request:
   - RS256 signature, key selected by the token's `kid` header.
   - `iss` claim **must equal** `CONVEX_SITE_URL` exactly.
   - `aud` claim **must equal** `"convex"` (the `applicationID` above).
4. Derive `tenant_id = claims["sub"]` server-side. This is the **only**
   source of `tenant_id`.

## Tenant-derivation rule (SPEC.md R7 — do not violate)

`tenant_id` is **never** accepted as a client-supplied argument, in Convex
functions or in FastAPI routes. Every query/mutation in `brands.ts`,
`profile.ts`, and `jobs.ts` starts with:

```ts
const identity = await ctx.auth.getUserIdentity();
if (identity === null) throw new Error("Unauthenticated");
const tenantId = identity.subject; // JWT `sub` claim
```

and then filters every read (`.withIndex("by_tenant", q => q.eq("tenantId", tenantId))`)
and checks ownership on every write before mutating. A client-supplied
`brandId`/`tenantId` is at most a hint that must match this derived value —
if a fetched document's `tenantId` doesn't match, the function returns `null`
(queries) or throws (mutations), never leaking cross-tenant data. On the
FastAPI side, the equivalent rule holds: a client-supplied `brand_id` that
doesn't match the token's tenant is a `403`, per `kaizen/SPEC.md` R7 and
`kaizen/FOUNDATION_SLICE.md` §4.

## Brand profile fields (must match the Python projection)

`brandProfile` (see `schema.ts`) — the canonical brand DNA `render_home()`
projects to `SOUL.md`/`AGENTS.md`, and that the backend reconciles back after
a run:

```
tenantId    string            (derived, not stored by client)
brandId     Id<"brands">
positioning string
voiceTone   string
audience    string
dos         string[]
donts       string[]
guardrails  string[]
channels    string[]
updatedAt   number (Date.now())
```

`kaizen/profile.py`'s `BrandProfile` dataclass (`render_soul()` /
`render_agents()` / `parse_agents()`) should use exactly these field names so
the Convex ⇄ file projection round-trips without a mapping layer.
