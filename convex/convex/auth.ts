// convex/auth.ts
//
// Wires @convex-dev/auth into this deployment so `ctx.auth.getUserIdentity()`
// actually returns a non-null identity, and so this deployment becomes a real
// JWT issuer + JWKS host (FOUNDATION_SLICE.md section 4 / kaizen/auth.py's
// verification target).
//
// Provider choice: Password. Verified against current docs (Context7
// `/get-convex/convex-auth`, docs/pages/config/passwords.mdx, 2026-07-12) --
// this is the simplest sign-in method that produces a real Convex Auth
// session/JWT without an external OAuth app registration, which fits the
// hackathon/foundation-slice scope (SPEC.md: "Auth — Lightweight brand
// token, not full auth/RBAC"). Swapping to OAuth/magic-link later is a
// provider-list change only; nothing downstream (kaizen/auth.py, brands.ts,
// profile.ts, jobs.ts) depends on which provider issued the token, since
// they all key off `ctx.auth.getUserIdentity().subject` / the JWT `sub`
// claim, not the provider.
//
// `convexAuth(...)` is what actually makes this deployment sign and serve
// JWTs once `JWT_PRIVATE_KEY` / `JWKS` are set (see convex/README.md's
// "one-time init" section) and `http.ts` mounts the routes below.

import { Password } from "@convex-dev/auth/providers/Password";
import { convexAuth } from "@convex-dev/auth/server";

export const { auth, signIn, signOut, store, isAuthenticated } = convexAuth({
  providers: [Password],
});
