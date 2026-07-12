"""FastAPI dependencies: the auth boundary for the Kaizen control plane.

``require_tenant`` is the *only* way a route learns ``tenant_id`` (SPEC.md
R7 / FOUNDATION_SLICE.md section 4): it reads the ``Authorization: Bearer
<jwt>`` header, verifies it via ``kaizen.auth.verify_convex_jwt`` against
Convex's JWKS, and returns the token's ``sub`` claim. Any client-supplied
brand_id/tenant hint elsewhere in a request is just a hint --
``guard_tenant_hint`` is what turns a mismatch into an HTTP 403, never a
silent bypass.

Config (env vars, matching ``kaizen/.env.example`` section 4/5 exactly):
    CONVEX_JWT_ISSUER    issuer FastAPI verifies the JWT `iss` claim against
    CONVEX_JWKS_URL      the JWKS document FastAPI fetches + caches
    CONVEX_JWT_AUDIENCE  audience FastAPI verifies the JWT `aud` claim against
    KAIZEN_PROFILES_DIR  base_dir for provision_tenant (per-tenant HERMES_HOME)

Module-level env reads happen at import time (mirroring the rest of
kaizen/ -- e.g. worker.py reads HERMES_HOME at process start). Tests that
need different env values reload this module after setting env vars via
monkeypatch (see kaizen/tests/test_api.py's ``client`` fixture).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Header, HTTPException

from kaizen.auth import AuthError, JWKSCache, verify_convex_jwt

CONVEX_JWT_ISSUER = os.environ.get("CONVEX_JWT_ISSUER", "")
CONVEX_JWT_AUDIENCE = os.environ.get("CONVEX_JWT_AUDIENCE", "convex")
CONVEX_JWKS_URL = os.environ.get("CONVEX_JWKS_URL", "")
KAIZEN_PROFILES_DIR = Path(os.environ.get("KAIZEN_PROFILES_DIR", "./.kaizen/profiles"))

# One process-wide JWKS cache, shared across requests (kaizen/auth.py's
# JWKSCache is the thing that actually caches + handles rotation-refresh).
jwks_cache = JWKSCache(jwks_url=CONVEX_JWKS_URL)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'")
    return token


def require_tenant(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: verify the bearer JWT and return ``tenant_id``.

    Raises HTTP 401 if the header is missing/malformed or the token fails
    verification (bad signature, wrong iss/aud, expired -- anything
    ``verify_convex_jwt`` raises ``AuthError`` for).
    """
    token = _extract_bearer_token(authorization)
    try:
        return verify_convex_jwt(
            token,
            issuer=CONVEX_JWT_ISSUER,
            audience=CONVEX_JWT_AUDIENCE,
            jwks_cache=jwks_cache,
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def guard_tenant_hint(hinted_tenant_id: str, actual_tenant_id: str) -> None:
    """Raise HTTP 403 if a client-supplied tenant hint doesn't match the
    validated token's tenant. A client-supplied brand_id/tenant_id is only
    ever a hint (SPEC.md R7) -- this is the enforcement point.
    """
    if hinted_tenant_id != actual_tenant_id:
        raise HTTPException(status_code=403, detail="tenant hint does not match authenticated tenant")
