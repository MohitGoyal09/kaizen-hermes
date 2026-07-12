# convex/ — Kaizen data + auth layer

Convex is the **system of record** for structured product data (brands, brand
profile/DNA, campaigns, posts, jobs, eval runs, engagement) and is the **JWT
issuer** the external FastAPI control plane verifies against. See
`kaizen/FOUNDATION_SLICE.md` §1 and `kaizen/DEPLOYMENT.md` for how this fits
with Honcho (agent memory) and `HERMES_HOME` (per-tenant operational cache).

## Files

| File | Purpose |
|---|---|
| `schema.ts` | Tables: `brands`, `brandProfile`, `campaigns`, `posts`, `jobs`, `eval_runs`, `engagement`, plus `...authTables` (from `@convex-dev/auth/server`). Every tenant table carries `tenantId` and is indexed `by_tenant` (or a compound index starting with `tenantId`). |
| `auth.config.ts` | Convex Auth provider config — this deployment issues the JWT. Documents the exact issuer/JWKS URL shape FastAPI must verify against (see below). |
| `auth.ts` | `convexAuth({ providers: [Password] })` — makes `ctx.auth.getUserIdentity()` real. Exports `auth`, `signIn`, `signOut`, `store`, `isAuthenticated`. |
| `http.ts` | `auth.addHttpRoutes(http)` — mounts `/.well-known/openid-configuration` + `/.well-known/jwks.json` on this deployment's HTTP Actions origin. |
| `brands.ts` | `createBrand`, `getBrand`, `listBrands`, `updateBrandStatus`. |
| `profile.ts` | `upsertBrandProfile`, `getBrandProfile` — the brand-DNA read/write path used by the FastAPI reconciliation step (`AGENTS.md`/`SOUL.md` file → Convex sync-back, and Convex → file on `render_home()`). |
| `jobs.ts` | `createJob`, `updateJobStatus`, `getJob`, `listJobsForBrand` — backs the `{job_id, tenant_id, type, status}` job model (`SPEC.md` §5). |

## Running locally

```bash
cd convex
npm install
npx convex dev
```

`npm install` (registry-only, no Convex login needed) has already been run in
this commit — `@convex-dev/auth`/`@auth/core` are present in `node_modules/`
and pinned in `package.json`.

`npx convex dev` will prompt a browser login on first run, create/link a
Convex deployment, write `.env.local` with `CONVEX_DEPLOYMENT` +
`CONVEX_URL`, and generate `convex/_generated/**` (commit that directory once
it exists — it is required for the code to typecheck and run, but this
environment had no Convex login available, so it is not present yet in this
commit). It will also prompt (or you run `npx @convex-dev/auth` separately)
to generate and upload `JWT_PRIVATE_KEY`/`JWKS` — see the Auth section below.

`npx tsc --noEmit -p .` typechecks every file in this directory (including
`auth.ts` / `http.ts` / the `authTables`-extended `schema.ts`) against the
real `convex`, `@convex-dev/auth`, and `@auth/core` npm packages —
**confirmed clean, 0 errors** (hand-authored stand-ins for
`_generated/server.ts` + `_generated/dataModel.ts` were used locally to prove
this, since no Convex login was available to run real codegen; they are not
part of the normal committed deliverable since they are machine-generated —
see git history / PR description).

## Auth: what FastAPI needs (read this before writing `kaizen/auth.py`)

**Status: wired in code, not yet activated (no Convex login in this
environment).** The three pieces `auth.config.ts` previously said were
missing are now all present:

1. `@convex-dev/auth` (`0.0.94`) + `@auth/core` (`0.41.1`) are declared in
   `convex/package.json` **and installed** (`npm install` against the public
   npm registry — this does not require a Convex login, only `npx convex
   dev`/`npx convex deploy` do). `npx tsc --noEmit -p .` passes against the
   real packages.
2. `convex/auth.ts` calls `convexAuth({ providers: [Password] })`. Provider
   choice: **Password** — the simplest sign-in method that issues a real
   session/JWT without registering an external OAuth app, matching
   `SPEC.md`'s "Auth — Lightweight brand token, not full auth/RBAC" scope
   for the hackathon. Swapping providers later is a one-line change; nothing
   downstream keys off which provider issued the token.
3. `convex/http.ts` calls `auth.addHttpRoutes(http)` — this is what mounts
   `/.well-known/openid-configuration` and `/.well-known/jwks.json`.
4. `convex/schema.ts` spreads `...authTables` (from
   `@convex-dev/auth/server`) into `defineSchema` — the users/sessions/
   accounts tables `convexAuth`'s Password provider needs to persist
   identities.

**What's still required to make this live** (needs a real Convex
deployment + login, unavailable in this environment):

```bash
cd convex
npm install        # already done in this commit; re-run if you pull fresh
npx convex dev      # first run: browser login, links/creates a deployment,
                     # writes .env.local (CONVEX_DEPLOYMENT, CONVEX_URL),
                     # generates convex/_generated/** (commit it once real)
```

Then the **one-time key generation step** (`@convex-dev/auth`'s own setup,
verified via Context7 `/get-convex/convex-auth`, docs/pages/setup/manual.mdx,
2026-07-12) — run once, from the `convex/` directory, with Node:

```bash
node -e '
import("jose").then(async ({ exportJWK, exportPKCS8, generateKeyPair }) => {
  const keys = await generateKeyPair("RS256", { extractable: true });
  const privateKey = await exportPKCS8(keys.privateKey);
  const publicKey = await exportJWK(keys.publicKey);
  const jwks = JSON.stringify({ keys: [{ use: "sig", ...publicKey }] });
  console.log(`JWT_PRIVATE_KEY="${privateKey.trimEnd().replace(/\n/g, " ")}"`);
  console.log(`JWKS=${jwks}`);
});
'
```

(`npx @convex-dev/auth` runs this — and the dashboard env var upload — for
you interactively; the above is the manual-setup equivalent if you want to
inspect the values first.) Copy the two output lines into this deployment's
**Environment Variables** page
(`https://dashboard.convex.dev/deployment/settings/environment-variables`):

| Env var | Set by | Consumed by |
|---|---|---|
| `JWT_PRIVATE_KEY` | key-gen step above | Convex Auth, to *sign* JWTs (server-side only, never leaves Convex) |
| `JWKS` | key-gen step above | Convex Auth, to *serve* `{CONVEX_SITE_URL}/.well-known/jwks.json` |
| `SITE_URL` | `npx convex dev` / dashboard | Convex Auth's own redirect/callback config |

Once `JWT_PRIVATE_KEY`/`JWKS` are set and `http.ts` is deployed,
`CONVEX_SITE_URL` (this deployment's HTTP Actions origin, shaped like
`https://<deployment-name>.convex.site`, distinct from the client
`CONVEX_URL` which ends in `.convex.cloud`) serves:

```
Issuer                : {CONVEX_SITE_URL}
OIDC discovery doc    : {CONVEX_SITE_URL}/.well-known/openid-configuration
JWKS (public keys)    : {CONVEX_SITE_URL}/.well-known/jwks.json
```

**This is exactly what `kaizen/auth.py` verifies against** — confirmed by
reading both sides side by side:

- `kaizen/.env.example` section 4 sets `CONVEX_JWKS_URL=${CONVEX_SITE_URL}/.well-known/jwks.json`
  and `CONVEX_JWT_ISSUER=${CONVEX_SITE_URL}` — the identical URL shape Convex
  Auth serves once wired.
- `kaizen/auth.py`'s `verify_convex_jwt` fetches+caches that exact URL
  (`JWKSCache`), verifies RS256 signature via the JWK matching the token's
  `kid`, checks `iss == CONVEX_JWT_ISSUER` and `aud == CONVEX_JWT_AUDIENCE`
  (`"convex"`, matching `auth.config.ts`'s `applicationID`), and returns
  `claims["sub"]` as `tenant_id`. `kaizen/tests/test_auth.py` proves this
  contract with a synthetic keypair (no live Convex needed to verify the
  *shape* is right); a live end-to-end check (real Convex Auth login →
  FastAPI accepts the resulting JWT) still requires the deployment steps
  above, which this environment could not run (no Convex account login
  available).

`kaizen/auth.py` (FastAPI side) must, and does:

1. Read `CONVEX_SITE_URL`-derived `CONVEX_JWKS_URL`/`CONVEX_JWT_ISSUER` from env.
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
