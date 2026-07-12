// convex/auth.config.ts
//
// Convex Auth configuration — declares that THIS deployment trusts its own
// Convex-Auth-issued JWTs (frontend logs in here; the external FastAPI
// control plane is meant to verify the resulting JWT against this
// deployment's JWKS).
//
// ============================================================================
// STATUS: INCOMPLETE — this file alone does NOT make this deployment a JWT
// issuer or JWKS host. Verified against current docs (Context7
// `/get-convex/convex-auth`, docs/pages/setup/manual.mdx and
// docs/pages/setup.mdx) on 2026-07-12:
//
//   `auth.config.ts` only tells Convex which OIDC issuer to TRUST for
//   validating incoming tokens (`domain` must equal the JWT's `iss`,
//   `applicationID` must equal `aud`) — "Convex uses the `domain` to
//   discover the JWKS endpoint" of that issuer. It does not, by itself,
//   generate keys, sign tokens, or serve `/.well-known/*`.
//
//   For Convex itself to actually issue tokens and serve JWKS at
//   `{CONVEX_SITE_URL}/.well-known/jwks.json` /
//   `{CONVEX_SITE_URL}/.well-known/openid-configuration`, THREE more things
//   are required and are NOT present in this commit:
//     1. `@convex-dev/auth` + `@auth/core` as dependencies (convex/package.json
//        currently only lists bare `convex`).
//     2. `convex/auth.ts` calling `convexAuth({ providers: [...] })` with an
//        actual chosen sign-in method (password / magic link / OAuth — a
//        product decision, not made here) to produce `JWT_PRIVATE_KEY`/`JWKS`.
//     3. `convex/http.ts` calling `auth.addHttpRoutes(http)` — THIS is what
//        mounts the `/.well-known/...` HTTP routes. Without it, those paths
//        404 and `ctx.auth.getUserIdentity()` will always return `null`.
//
//   Until all three exist, every function in brands.ts/profile.ts/jobs.ts
//   will reject every call as unauthenticated (fails closed, not a security
//   leak — but the auth layer is not yet functional end-to-end).
//
// Once wired, the intended contract (unchanged) is:
//
//   Issuer               : {CONVEX_SITE_URL}                                (JWT `iss` claim)
//   OIDC discovery doc   : {CONVEX_SITE_URL}/.well-known/openid-configuration
//   JWKS (public keys)   : {CONVEX_SITE_URL}/.well-known/jwks.json
//
// ============================================================================
// WHAT THE PYTHON / FASTAPI SIDE MUST DO (kaizen/auth.py, per FOUNDATION_SLICE.md §4)
// ONCE THE ABOVE IS WIRED:
//   1. Read CONVEX_SITE_URL from env (same value as this Convex deployment's
//      site URL, e.g. "https://happy-animal-123.convex.site").
//   2. Fetch/cache {CONVEX_SITE_URL}/.well-known/jwks.json (a standard JWKS
//      document: {"keys": [...RS256 public keys with `kid`...]}).
//   3. Verify the incoming `Authorization: Bearer <jwt>` against that JWKS:
//        - signature: RS256, key selected by the token's `kid` header
//        - `iss` claim MUST equal CONVEX_SITE_URL exactly
//        - `aud` claim MUST equal "convex" (the applicationID below)
//   4. `tenant_id = claims["sub"]` (the Convex user/identity subject) — this
//      is the ONLY source of tenant_id server-side. SPEC.md R7: a
//      client-supplied brand_id/tenant_id is at most a hint that must equal
//      this value, else 403.
// ============================================================================

export default {
  providers: [
    {
      domain: process.env.CONVEX_SITE_URL,
      applicationID: "convex",
    },
  ],
};
