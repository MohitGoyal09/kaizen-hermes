// convex/auth.config.ts
//
// Convex Auth configuration — this deployment IS the JWT issuer for the whole
// Kaizen system (frontend logs in here; the external FastAPI control plane
// verifies the resulting JWT against this deployment's JWKS).
//
// Convex API grounding: fetched 2026-07-12 via Context7 (`/get-convex/convex-auth`,
// docs/pages/setup/manual.mdx). The built-in Convex Auth provider config shape is:
//   { providers: [{ domain: process.env.CONVEX_SITE_URL, applicationID: "convex" }] }
// `CONVEX_SITE_URL` is the deployment's HTTP Actions URL (looks like
// `https://<deployment-name>.convex.site`), auto-populated by `npx convex dev` /
// `npx convex deploy`. Every Convex deployment serves OIDC discovery + JWKS at
// well-known paths under that same origin (this is how Convex Auth's own
// dashboard / server-side `ctx.auth.getUserIdentity()` verification works, and
// it is the same mechanism any external verifier must use):
//
//   Issuer               : {CONVEX_SITE_URL}                                (JWT `iss` claim)
//   OIDC discovery doc   : {CONVEX_SITE_URL}/.well-known/openid-configuration
//   JWKS (public keys)   : {CONVEX_SITE_URL}/.well-known/jwks.json
//
// ============================================================================
// WHAT THE PYTHON / FASTAPI SIDE MUST DO (kaizen/auth.py, per FOUNDATION_SLICE.md §4):
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
