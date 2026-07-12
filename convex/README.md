# convex/ — Kaizen data + auth layer

Convex is the **system of record** for structured product data (brands, brand
profile/DNA, campaigns, posts, jobs, eval runs, engagement) and is the **JWT
issuer** the external FastAPI control plane verifies against. See
`kaizen/FOUNDATION_SLICE.md` §1 and `kaizen/DEPLOYMENT.md` for how this fits
with Honcho (agent memory) and `HERMES_HOME` (per-tenant operational cache).

**Status: LIVE locally.** A local anonymous Convex deployment is wired end to
end — schema + functions deployed, Convex Auth JWT signing configured, JWKS
serving real keys. No cloud login is required to develop against it. See
"Promoting to a cloud deployment" below for the one-time step to get a
dashboard + persistent/shareable deployment later.

## Directory layout (read this before moving files again)

This project root (`convex/` relative to the repo root, i.e.
`hermes-agent/convex/`) is **not itself the Convex functions directory** — it
is the Convex *project* root: `package.json`, `node_modules/`, `tsconfig.json`,
`.env.local`, `.gitignore` live here. The actual Convex functions directory
that `npx convex dev` bundles and deploys is the **nested**
`convex/convex/` subdirectory (Convex's default functions-dir convention —
"project root + a `convex/` folder inside it"). All the files in the table
below live in that nested directory:

| File (under `convex/convex/`) | Purpose |
|---|---|
| `schema.ts` | Tables: `brands`, `brandProfile`, `campaigns`, `posts`, `jobs`, `eval_runs`, `engagement`, plus `...authTables` (from `@convex-dev/auth/server`). Every tenant table carries `tenantId` and is indexed `by_tenant` (or a compound index starting with `tenantId`). |
| `auth.config.ts` | Convex Auth provider config — this deployment issues the JWT. Documents the exact issuer/JWKS URL shape FastAPI must verify against (see below). |
| `auth.ts` | `convexAuth({ providers: [Password] })` — makes `ctx.auth.getUserIdentity()` real. Exports `auth`, `signIn`, `signOut`, `store`, `isAuthenticated`. |
| `http.ts` | `auth.addHttpRoutes(http)` — mounts `/.well-known/openid-configuration` + `/.well-known/jwks.json` on this deployment's HTTP Actions origin. |
| `brands.ts` | `createBrand`, `getBrand`, `listBrands`, `updateBrandStatus`. |
| `profile.ts` | `upsertBrandProfile`, `getBrandProfile` — the brand-DNA read/write path used by the FastAPI reconciliation step (`AGENTS.md`/`SOUL.md` file → Convex sync-back, and Convex → file on `render_home()`). |
| `jobs.ts` | `createJob`, `updateJobStatus`, `getJob`, `listJobsForBrand` — backs the `{job_id, tenant_id, type, status}` job model (`SPEC.md` §5). |

`convex/convex/_generated/**` is real, machine-generated codegen (produced by
`npx convex dev` against the live local deployment) — gitignored, not
committed, regenerate it with `npx convex dev` or `npx convex codegen`.

**Do not put function modules directly in this project root again** — that
was the original bug: `npx convex dev`, run from this directory, looked for
its default `convex/` functions subdirectory, found none, and silently
created an empty one instead of deploying the `.ts` files that were sitting
at this level. If `mcp__convex__tables` / `functionSpec` ever comes back
empty again, this is the first thing to check.

## Running locally

```bash
cd convex
npm install
CONVEX_AGENT_MODE=anonymous npx convex dev
```

`npm install` (registry-only, no Convex login needed) has already been run in
this commit — `@convex-dev/auth`/`@auth/core` are present in `node_modules/`
and pinned in `package.json`.

`CONVEX_AGENT_MODE=anonymous npx convex dev` creates/reuses a **local**
anonymous deployment (no browser login, no Convex account) — backed by
`.convex/local/default/convex_local_backend.sqlite3` — and writes
`CONVEX_DEPLOYMENT=anonymous:anonymous-convex`, `CONVEX_URL=http://127.0.0.1:3210`,
`CONVEX_SITE_URL=http://127.0.0.1:3211` to `.env.local`. It watches
`convex/convex/**/*.ts`, bundles them, and pushes on every save — leave it
running in the background while developing so the Convex MCP tools
(`tables`, `functionSpec`, `run`, `logs`, `envSet`, ...) can reach it.

`npx tsc --noEmit -p .` typechecks every file against the real
`convex`, `@convex-dev/auth`, and `@auth/core` npm packages **and** the real
generated `convex/convex/_generated/**` — confirmed clean, 0 errors, once
`npx convex dev` has run at least once to produce that codegen.

## Promoting to a cloud deployment (later, deferred per CLAUDE.md rule 6)

The local anonymous deployment above is meant for development. To get a real
Convex Cloud deployment (dashboard, persistent URL, shareable with
teammates), from `convex/`:

```bash
npx convex login   # one-time browser login
npx convex dev      # links/creates a real cloud dev deployment, rewrites .env.local
```

What changes when you do this:
- `.env.local` gets **new** `CONVEX_DEPLOYMENT` (e.g. `dev:happy-animal-123`),
  `CONVEX_URL` (`https://happy-animal-123.convex.cloud`), and
  `CONVEX_SITE_URL` (`https://happy-animal-123.convex.site`) — the
  `127.0.0.1:3210`/`:3211` local values are gone.
- You must re-run the JWT key-generation step (or `npx @convex-dev/auth`)
  against the **new** deployment — `JWT_PRIVATE_KEY`/`JWKS`/`SITE_URL` are
  per-deployment and do **not** carry over from the local anonymous
  deployment.
- The repo-root `.env` (`CONVEX_URL`, `CONVEX_SITE_URL`, `CONVEX_DEPLOYMENT`,
  `CONVEX_JWT_ISSUER`, `CONVEX_JWKS_URL`) must be updated to the new
  `.convex.site`/`.convex.cloud` URLs so `kaizen/auth.py` verifies against the
  right issuer.
- The dashboard becomes available at the URL `npx convex dev` prints (or
  `mcp__convex__status`'s `dashboardUrl`), instead of only the MCP tools.

## Auth: what FastAPI needs (read this before writing `kaizen/auth.py`)

**Status: wired AND activated on the local deployment.** `JWT_PRIVATE_KEY`,
`JWKS`, and `SITE_URL` are set (via `mcp__convex__envSet` /
`npx convex env set`), and `http://127.0.0.1:3211/.well-known/jwks.json`
serves real RS256 keys (curl it to confirm — see below). The three pieces
`auth.config.ts` previously said were missing are now all present:

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

**How the keys were generated and set** (the one-time key generation step,
`@convex-dev/auth`'s own setup, verified via Context7
`/get-convex/convex-auth`, docs/pages/setup/manual.mdx, 2026-07-12) — run once
from the `convex/` directory, with Node:

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

(`npx @convex-dev/auth` runs this — and the env var upload — for you
interactively against a cloud deployment; the above is the manual-setup
equivalent, used here because we're on a local anonymous deployment with no
dashboard.) The two output lines, plus `SITE_URL`, were set via
`mcp__convex__envSet` (equivalent to `npx convex env set <NAME> <VALUE>`):

| Env var | Set by | Consumed by |
|---|---|---|
| `JWT_PRIVATE_KEY` | key-gen step above | Convex Auth, to *sign* JWTs (server-side only, never leaves Convex) |
| `JWKS` | key-gen step above | Convex Auth, to *serve* `{CONVEX_SITE_URL}/.well-known/jwks.json` |
| `SITE_URL` | set to `http://127.0.0.1:3211` (= local `CONVEX_SITE_URL`) | Convex Auth's own redirect/callback config |

On a cloud deployment, the dashboard's **Environment Variables** page
(`https://dashboard.convex.dev/deployment/settings/environment-variables`) is
the equivalent place to inspect/edit these once you've run `npx convex login`
(see "Promoting to a cloud deployment" above) — and you'd re-run the
key-generation step for that deployment, since these three vars are
per-deployment and do not carry over from local to cloud.

Once `JWT_PRIVATE_KEY`/`JWKS` are set and `http.ts` is deployed,
`CONVEX_SITE_URL` (this deployment's HTTP Actions origin, shaped like
`https://<deployment-name>.convex.site`, distinct from the client
`CONVEX_URL` which ends in `.convex.cloud`) serves:

```
Issuer                : {CONVEX_SITE_URL}
OIDC discovery doc    : {CONVEX_SITE_URL}/.well-known/openid-configuration
JWKS (public keys)    : {CONVEX_SITE_URL}/.well-known/jwks.json
```

**This is exactly what `kaizen/auth.py` verifies against** — confirmed live,
not just by reading both sides side by side:

- Repo-root `.env` section 4 sets literal (not `${...}`-interpolated —
  `os.environ.get(...)` does not do shell interpolation) values:
  `CONVEX_JWT_ISSUER=http://127.0.0.1:3211`,
  `CONVEX_JWKS_URL=http://127.0.0.1:3211/.well-known/jwks.json`,
  `CONVEX_JWT_AUDIENCE=convex` — the exact URL shape and audience Convex Auth
  now actually serves (verified with `curl`, see below).
- `kaizen/auth.py`'s `verify_convex_jwt` fetches+caches that exact URL
  (`JWKSCache`), verifies RS256 signature via the JWK matching the token's
  `kid`, checks `iss == CONVEX_JWT_ISSUER` and `aud == CONVEX_JWT_AUDIENCE`
  (`"convex"`, matching `auth.config.ts`'s `applicationID`), and returns
  `claims["sub"]` as `tenant_id`. `kaizen/tests/test_auth.py` proves this
  contract with a synthetic keypair; `curl http://127.0.0.1:3211/.well-known/jwks.json`
  (200, real RS256 public key) and the R7 smoke test below (unauthenticated
  Convex function calls reject with "Unauthenticated") confirm the Convex
  side of the contract is live end-to-end. A full login → FastAPI round trip
  (real Convex Auth sign-in producing a JWT that FastAPI then verifies) is
  the natural next integration test once `kaizen/auth.py` is wired into a
  running FastAPI app.

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

**Verified live** via `mcp__convex__run` against the local deployment with no
identity attached: both `brands.js:listBrands` (query) and
`brands.js:createBrand` (mutation) reject with
`Uncaught Error: Unauthenticated: no valid identity on request`, thrown from
`requireTenantId` — confirming the fail-closed behavior end to end, not just
in source.

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
