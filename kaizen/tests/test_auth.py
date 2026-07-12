"""Tests for kaizen.auth: verifying Convex Auth JWTs against a JWKS.

FOUNDATION_SLICE.md section 4 / SPEC.md R7: the *only* source of tenant_id
server-side is the validated JWT's ``sub`` claim. ``verify_convex_jwt``
fetches (and caches) the issuer's JWKS, verifies RS256 signature + `iss` +
`aud` + expiry, and returns ``claims["sub"]`` as the tenant id. Any failure
(bad signature, wrong issuer/audience, expired, unreachable JWKS) raises the
typed ``AuthError`` so FastAPI's dependency layer can turn it into a 401.

This test generates its own synthetic RSA keypair and signs tokens locally
-- no live network, no real Convex deployment. The JWKS document is served
from an in-memory dict (monkeypatched fetch), covering the exact shape
Convex serves at ``{CONVEX_SITE_URL}/.well-known/jwks.json``.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from kaizen.auth import AuthError, JWKSCache, verify_convex_jwt

ISSUER = "https://happy-animal-123.convex.site"
AUDIENCE = "convex"
KID = "test-key-1"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture()
def jwks_document(rsa_keypair):
    _private_key, public_key = rsa_keypair
    jwk = json_loads_jwk(public_key)
    jwk["kid"] = KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return {"keys": [jwk]}


def json_loads_jwk(public_key) -> dict:
    """Turn a cryptography public key into a JWK dict via PyJWT's algorithm."""
    import json

    algo = RSAAlgorithm(RSAAlgorithm.SHA256)
    jwk_json = algo.to_jwk(public_key)
    return json.loads(jwk_json)


def _make_token(
    rsa_keypair,
    *,
    sub: str = "tenant-abc",
    iss: str = ISSUER,
    aud: str = AUDIENCE,
    exp_delta: int = 3600,
    kid: str | None = KID,
) -> str:
    private_key, _public_key = rsa_keypair
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_delta,
    }
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, private_key, algorithm="RS256", headers=headers)


@pytest.fixture()
def cache_with_jwks(jwks_document, monkeypatch: pytest.MonkeyPatch) -> JWKSCache:
    """A JWKSCache whose HTTP fetch is monkeypatched to return the in-memory
    JWKS document instead of making a real network call."""
    cache = JWKSCache(jwks_url="https://example.invalid/.well-known/jwks.json")
    monkeypatch.setattr(cache, "_fetch_jwks", lambda: jwks_document)
    return cache


class TestVerifyConvexJwtValidToken:
    def test_returns_tenant_id_from_sub_claim(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, sub="tenant-abc")

        tenant_id = verify_convex_jwt(
            token,
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_cache=cache_with_jwks,
        )

        assert tenant_id == "tenant-abc"

    def test_different_sub_claim_returns_different_tenant(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, sub="tenant-xyz")

        tenant_id = verify_convex_jwt(
            token,
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_cache=cache_with_jwks,
        )

        assert tenant_id == "tenant-xyz"


class TestVerifyConvexJwtTamperedSignature:
    def test_tampered_signature_raises_auth_error(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, sub="tenant-abc")
        # Flip a character in the signature segment to corrupt it.
        header, payload, signature = token.split(".")
        tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        tampered_token = f"{header}.{payload}.{tampered_signature}"

        with pytest.raises(AuthError):
            verify_convex_jwt(
                tampered_token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )

    def test_signed_with_wrong_key_raises_auth_error(self, cache_with_jwks) -> None:
        other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        token = jwt.encode(
            {"sub": "tenant-abc", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 3600},
            other_private_key,
            algorithm="RS256",
            headers={"kid": KID},
        )

        with pytest.raises(AuthError):
            verify_convex_jwt(
                token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )


class TestVerifyConvexJwtWrongIssuerOrAudience:
    def test_wrong_issuer_raises_auth_error(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, iss="https://evil.example.com")

        with pytest.raises(AuthError):
            verify_convex_jwt(
                token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )

    def test_wrong_audience_raises_auth_error(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, aud="some-other-app")

        with pytest.raises(AuthError):
            verify_convex_jwt(
                token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )


class TestVerifyConvexJwtExpired:
    def test_expired_token_raises_auth_error(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, exp_delta=-3600)

        with pytest.raises(AuthError):
            verify_convex_jwt(
                token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )


class TestVerifyConvexJwtMalformedToken:
    def test_garbage_token_raises_auth_error(self, cache_with_jwks) -> None:
        with pytest.raises(AuthError):
            verify_convex_jwt(
                "not-a-jwt-at-all",
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )

    def test_unknown_kid_raises_auth_error(self, rsa_keypair, cache_with_jwks) -> None:
        token = _make_token(rsa_keypair, kid="some-other-kid")

        with pytest.raises(AuthError):
            verify_convex_jwt(
                token,
                issuer=ISSUER,
                audience=AUDIENCE,
                jwks_cache=cache_with_jwks,
            )


class TestJWKSCacheRefresh:
    def test_caches_jwks_and_does_not_refetch_on_every_call(
        self, rsa_keypair, jwks_document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetch_calls = {"count": 0}

        def _fake_fetch():
            fetch_calls["count"] += 1
            return jwks_document

        cache = JWKSCache(jwks_url="https://example.invalid/.well-known/jwks.json")
        monkeypatch.setattr(cache, "_fetch_jwks", _fake_fetch)

        token = _make_token(rsa_keypair, sub="tenant-abc")
        verify_convex_jwt(token, issuer=ISSUER, audience=AUDIENCE, jwks_cache=cache)
        verify_convex_jwt(token, issuer=ISSUER, audience=AUDIENCE, jwks_cache=cache)

        assert fetch_calls["count"] == 1

    def test_refreshes_jwks_once_when_kid_is_unknown_then_succeeds(
        self, rsa_keypair, jwks_document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates key rotation: the cache holds a stale JWKS missing the
        signing key's kid, so the cache must refetch once before giving up."""
        stale_jwks = {"keys": []}
        fetch_sequence = [stale_jwks, jwks_document]

        cache = JWKSCache(jwks_url="https://example.invalid/.well-known/jwks.json")
        monkeypatch.setattr(cache, "_fetch_jwks", lambda: fetch_sequence.pop(0))
        # Prime the cache with the stale document (simulating a cache that
        # was populated before key rotation happened).
        cache.get()

        token = _make_token(rsa_keypair, sub="tenant-abc")
        tenant_id = verify_convex_jwt(token, issuer=ISSUER, audience=AUDIENCE, jwks_cache=cache)

        assert tenant_id == "tenant-abc"
