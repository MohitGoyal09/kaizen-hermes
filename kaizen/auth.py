"""Convex Auth JWT verification: the only place ``tenant_id`` is derived.

FOUNDATION_SLICE.md section 4 / SPEC.md R7: the frontend logs in via Convex
Auth and gets a signed session JWT; every FastAPI request carries it as
``Authorization: Bearer <jwt>``. This module verifies that JWT against
Convex's JWKS (RS256, keyed by ``kid``), checks ``iss``/``aud``/expiry, and
returns ``claims["sub"]`` as ``tenant_id`` -- the *only* server-side source
of tenant identity. A client-supplied brand_id is never trusted as tenant
identity (see ``kaizen/api/deps.py``'s hint-guard, which compares against
this value).

JWKS is fetched over HTTP and cached in-process (``JWKSCache``): Convex's
JWKS endpoint is a slow-changing, cacheable document (RSA public keys), so
re-fetching per-request would be wasteful and would block the event loop
harder than necessary. The cache refreshes once, synchronously, whenever a
token's ``kid`` isn't found in the current cached document -- this is the
key-rotation path: Convex rotates keys rarely, and a stale cache should
self-heal on the very next verification rather than requiring a restart.

The JWKS fetch uses a short-timeout ``httpx.Client`` (sync) rather than
async httpx, because ``verify_convex_jwt`` itself is a plain sync function
(PyJWT's verification is sync/CPU-bound). FastAPI callers run it via
``starlette.concurrency.run_in_threadpool`` (see ``kaizen/api/deps.py``) so
it never blocks the event loop; the alternative -- making this function
async -- would only move the blocking part (PyJWT's RSA verify) rather than
remove it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

_JWKS_FETCH_TIMEOUT_SECONDS = 5.0


class AuthError(Exception):
    """Raised for any JWT verification failure. FastAPI maps this to 401."""


@dataclass
class JWKSCache:
    """In-process cache for one issuer's JWKS document, with a refresh path
    for key rotation.

    Not thread-safe-by-construction beyond a coarse lock around refresh --
    good enough for a control plane that fetches an infrequently-rotated
    document; a stampede of concurrent refreshes is harmless (idempotent
    GET), so the lock exists to avoid redundant network calls, not for
    correctness.
    """

    jwks_url: str
    _cached: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch the JWKS document over HTTP. Overridden in tests to avoid
        live network calls."""
        with httpx.Client(timeout=_JWKS_FETCH_TIMEOUT_SECONDS) as client:
            response = client.get(self.jwks_url)
            response.raise_for_status()
            return response.json()

    def get(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return the cached JWKS document, fetching it if absent or if
        ``force_refresh`` is set (the key-rotation path)."""
        if self._cached is None or force_refresh:
            with self._lock:
                if self._cached is None or force_refresh:
                    self._cached = self._fetch_jwks()
        return self._cached

    def find_key(self, kid: str | None) -> dict[str, Any] | None:
        """Return the JWK matching ``kid`` from the cache, refreshing once
        if it's missing (handles key rotation without a restart)."""
        jwks = self.get()
        key = _find_key_in_document(jwks, kid)
        if key is not None:
            return key
        jwks = self.get(force_refresh=True)
        return _find_key_in_document(jwks, kid)


def _find_key_in_document(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    keys = jwks.get("keys", [])
    if kid is None:
        return keys[0] if len(keys) == 1 else None
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def verify_convex_jwt(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks_cache: JWKSCache,
) -> str:
    """Verify ``token`` against Convex's JWKS and return ``tenant_id``.

    Checks (in order): the token is well-formed and RS256-signed by a key
    present in the issuer's JWKS, ``iss`` equals ``issuer`` exactly, ``aud``
    equals ``audience`` exactly, and the token is not expired. Returns
    ``claims["sub"]`` as the tenant id on success.

    Raises ``AuthError`` -- never a raw ``jwt`` or ``httpx`` exception -- on
    any failure, so callers (``kaizen/api/deps.py``) can map this to a
    uniform 401 without needing to know PyJWT's exception hierarchy.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as exc:
        raise AuthError(f"malformed JWT: {exc}") from exc

    kid = unverified_header.get("kid")

    try:
        jwk = jwks_cache.find_key(kid)
    except httpx.HTTPError as exc:
        raise AuthError(f"failed to fetch JWKS: {exc}") from exc

    if jwk is None:
        raise AuthError(f"no matching JWKS key found for kid={kid!r}")

    try:
        public_key = RSAAlgorithm.from_jwk(jwk)
    except (ValueError, TypeError) as exc:
        raise AuthError(f"invalid JWK: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.exceptions.PyJWTError as exc:
        raise AuthError(f"JWT verification failed: {exc}") from exc

    tenant_id = claims.get("sub")
    if not tenant_id or not isinstance(tenant_id, str):
        raise AuthError("JWT is missing a valid 'sub' claim")

    return tenant_id
