"""Tests for the Content Creator route: ``POST /v1/brands/{id}/content``.

Mirrors ``test_api.py``'s approach exactly (real synthetic RSA-signed JWT
through the real ``verify_convex_jwt`` path, ``KAIZEN_WORKER_DRYRUN=1`` so no
live LLM call happens) -- this route reuses the same auth boundary
(``deps.require_tenant`` + ``_get_owned_brand_or_404_403``-style guard) and
the same job/stream machinery (``job_store`` + ``GET /v1/jobs/{id}/stream``)
as the onboarding route, just with a different persona/job type.

In dryrun mode the worker subprocess never actually writes
``content_latest.md`` (it just emits a synthetic step/final -- see
``kaizen/worker.py:_run_dryrun``), so the content-recording step must
degrade gracefully (skip recording, do not fail the job) when the file
isn't there. That's exercised implicitly by the happy-path test still
reaching "done" rather than "failed".
"""

from __future__ import annotations

import json
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

    # Same reload order as test_api.py's client fixture: deps -> route
    # modules (their Depends(...) wiring is captured at each module's own
    # import/decoration time) -> main last so it re-registers routers
    # pointing at the freshly-reloaded route modules.
    import importlib

    import kaizen.api.deps as deps_module
    import kaizen.api.routes_brands as routes_brands_module
    import kaizen.api.routes_content as routes_content_module
    import kaizen.api.routes_jobs as routes_jobs_module
    import kaizen.api.main as main_module

    importlib.reload(deps_module)
    importlib.reload(routes_brands_module)
    importlib.reload(routes_content_module)
    importlib.reload(routes_jobs_module)
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


class TestContentAuthBoundary:
    def test_missing_authorization_header_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/v1/brands/does-not-matter/content", json={"brief": "announce our launch"}
        )
        assert response.status_code == 401

    def test_unknown_brand_id_returns_404(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        response = client.post(
            "/v1/brands/does-not-exist/content",
            json={"brief": "announce our launch"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_other_tenant_brand_returns_403(self, client: TestClient, rsa_keypair) -> None:
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers_a)

        headers_b = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.post(
            f"/v1/brands/{brand_id}/content",
            json={"brief": "announce our launch"},
            headers=headers_b,
        )
        assert response.status_code == 403


class TestContentJobAndStream:
    def test_content_request_enqueues_job_and_returns_202(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        response = client.post(
            f"/v1/brands/{brand_id}/content",
            json={"brief": "announce our new pricing tier", "format": "social_post"},
            headers=headers,
        )

        assert response.status_code == 202
        body = response.json()
        assert "job_id" in body
        assert body["status"] in ("queued", "running", "done")

    def test_content_format_is_optional(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        response = client.post(
            f"/v1/brands/{brand_id}/content",
            json={"brief": "announce our new pricing tier"},
            headers=headers,
        )

        assert response.status_code == 202

    def test_job_runs_and_stream_yields_step_then_terminal_event(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        content_resp = client.post(
            f"/v1/brands/{brand_id}/content",
            json={"brief": "announce our new pricing tier"},
            headers=headers,
        )
        job_id = content_resp.json()["job_id"]

        with client.stream(
            "GET", f"/v1/jobs/{job_id}/stream", headers=headers
        ) as stream_resp:
            assert stream_resp.status_code == 200
            assert "text/event-stream" in stream_resp.headers["content-type"]

            event_types: list[str] = []
            for raw_line in stream_resp.iter_lines():
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                payload = json.loads(raw_line[len("data:"):].strip())
                event_types.append(payload["type"])
                if payload["type"] in ("final", "error"):
                    break

        assert "step" in event_types
        assert event_types[-1] in ("final", "error")
        assert event_types.index("step") < len(event_types) - 1 or event_types[-1] == "step"

    def test_job_reaches_done_status(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        brand_id = _create_brand(client, headers)

        content_resp = client.post(
            f"/v1/brands/{brand_id}/content",
            json={"brief": "announce our new pricing tier"},
            headers=headers,
        )
        job_id = content_resp.json()["job_id"]

        with client.stream("GET", f"/v1/jobs/{job_id}/stream", headers=headers) as stream_resp:
            for raw_line in stream_resp.iter_lines():
                if raw_line.startswith("data:"):
                    payload = json.loads(raw_line[len("data:"):].strip())
                    if payload["type"] in ("final", "error"):
                        break

        status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "done"
        assert status_resp.json()["type"] == "content"
