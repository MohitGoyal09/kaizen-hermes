// convex/http.ts
//
// Mounts @convex-dev/auth's HTTP routes, which is what actually serves
// `/.well-known/openid-configuration` and `/.well-known/jwks.json` on this
// deployment's HTTP Actions origin (CONVEX_SITE_URL). Without this call,
// those paths 404 and `ctx.auth.getUserIdentity()` always returns null
// (every function in brands.ts/profile.ts/jobs.ts fails closed as
// "Unauthenticated" -- safe, but not usable end-to-end). See
// convex/README.md and convex/auth.config.ts for the full contract
// kaizen/auth.py verifies against.

import { httpRouter } from "convex/server";
import { auth } from "./auth";

const http = httpRouter();

auth.addHttpRoutes(http);

export default http;
