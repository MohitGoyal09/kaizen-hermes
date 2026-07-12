"""Tests for the Publisher route: ``POST /v1/brands/{id}/publish`` and
``GET /v1/brands/{id}/posts/published``.

Mirrors ``test_content.py``'s fixture setup exactly (real synthetic
RSA-signed JWT through the real ``verify_convex_jwt`` path) -- this route
reuses the same auth boundary (``deps.require_tenant`` +
``_get_owned_brand_or_404_403``-style guard) as every other brand-scoped
route.

No live Composio call is made anywhere in this file: every case here is
either rejected before the Composio call (401/403/404) or hits the
``COMPOSIO_API_KEY`` unset guard (400), which is the only Composio-adjacent
path exercised without network access.
"""

from __future__ import annotations

import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://test-deployment.convex.site"
AUDIENCE = "convex"
KID = "test-key-1"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def jwks_document(rsa_keypair):
    import json as _json

    _private_key, public_key = rsa_keypair
    algo = RSAAlgorithm(RSAAlgorithm.SHA256)
    jwk = _json.loads(algo.to_jwk(public_key))
    jwk["kid"] = KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return {"keys": [jwk]}


def _make_token(rsa_keypair, *, sub: str, exp_delta: int = 3600) -> str:
    private_key, _public_key = rsa_keypair
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + exp_delta,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


@pytest.fixture()
def profiles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "profiles"
    d.mkdir()
    return d


@pytest.fixture()
def client(profiles_dir: Path, jwks_document, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KAIZEN_PROFILES_DIR", str(profiles_dir))
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    monkeypatch.setenv("CONVEX_JWT_ISSUER", ISSUER)
    monkeypatch.setenv("CONVEX_JWT_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("CONVEX_JWKS_URL", "https://example.invalid/.well-known/jwks.json")
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)

    # Same reload order as test_content.py's client fixture: deps -> route
    # modules (their Depends(...) wiring is captured at each module's own
    # import/decoration time) -> main last so it re-registers routers
    # pointing at the freshly-reloaded route modules.
    import importlib

    import kaizen.api.deps as deps_module
    import kaizen.api.routes_brands as routes_brands_module
    import kaizen.api.routes_content as routes_content_module
    import kaizen.api.routes_jobs as routes_jobs_module
    import kaizen.api.routes_publish as routes_publish_module
    import kaizen.api.main as main_module

    importlib.reload(deps_module)
    importlib.reload(routes_brands_module)
    importlib.reload(routes_content_module)
    importlib.reload(routes_jobs_module)
    importlib.reload(routes_publish_module)
    importlib.reload(main_module)

    monkeypatch.setattr(deps_module.jwks_cache, "_fetch_jwks", lambda: jwks_document)

    return TestClient(main_module.app)


def _auth_headers(rsa_keypair, *, sub: str) -> dict[str, str]:
    token = _make_token(rsa_keypair, sub=sub)
    return {"Authorization": f"Bearer {token}"}


def _create_brand(client: TestClient, headers: dict[str, str]) -> str:
    create_resp = client.post(
        "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
    )
    assert create_resp.status_code == 201
    return create_resp.json()["brand_id"]


class TestPublishAuthBoundary:
    def test_missing_authorization_header_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/v1/brands/does-not-matter/publish", json={"text": "hello world"}
        )
        assert response.status_code == 401

    def test_unknown_brand_id_returns_404(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        response = client.post(
            "/v1/brands/does-not-exist/publish",
            json={"text": "hello world"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_other_tenant_brand_returns_403(self, client: TestClient, rsa_keypair) -> None:
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers_a)

        headers_b = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.post(
            f"/v1/brands/{brand_id}/publish",
            json={"text": "hello world"},
            headers=headers_b,
        )
        assert response.status_code == 403


class TestPublishComposioConfig:
    def test_missing_composio_api_key_returns_400(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        response = client.post(
            f"/v1/brands/{brand_id}/publish",
            json={"text": "announcing our launch", "channel": "x"},
            headers=headers,
        )

        assert response.status_code == 400
        assert "COMPOSIO_API_KEY" in response.json()["detail"]

    def test_unsupported_channel_returns_400(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        response = client.post(
            f"/v1/brands/{brand_id}/publish",
            json={"text": "announcing our launch", "channel": "telegram"},
            headers=headers,
        )

        assert response.status_code == 400


class TestPublishedPostsAuthBoundary:
    def test_missing_authorization_header_returns_401(self, client: TestClient) -> None:
        response = client.get("/v1/brands/does-not-matter/posts/published")
        assert response.status_code == 401

    def test_unknown_brand_id_returns_404(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        response = client.get(
            "/v1/brands/does-not-exist/posts/published", headers=headers
        )
        assert response.status_code == 404

    def test_other_tenant_brand_returns_403(self, client: TestClient, rsa_keypair) -> None:
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers_a)

        headers_b = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.get(
            f"/v1/brands/{brand_id}/posts/published", headers=headers_b
        )
        assert response.status_code == 403

    def test_empty_list_when_nothing_published(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        response = client.get(f"/v1/brands/{brand_id}/posts/published", headers=headers)

        assert response.status_code == 200
        assert response.json() == []
