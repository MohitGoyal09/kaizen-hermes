"""Tests for the kaizen.api FastAPI control plane.

Covers the auth boundary (401 unauthenticated, 403 tenant-hint mismatch --
SPEC.md R7 / FOUNDATION_SLICE.md section 4), brand provisioning
(``POST /v1/brands`` -> ``provision_tenant`` under a tmp
``KAIZEN_PROFILES_DIR``), and the onboarding job + SSE stream running in
``KAIZEN_WORKER_DRYRUN=1`` mode (no real LLM, no live Convex -- the worker
subprocess emits a synthetic ``step`` then ``final`` event, exactly as
proven in ``test_worker_dryrun.py``).

Auth is exercised with a *real* synthetic RSA-signed JWT verified through
the real ``verify_convex_jwt`` path (JWKS fetch monkeypatched onto the
app's cached ``JWKSCache`` instance) -- this proves the whole
dependency-injection wire-up, not just that some auth function was called.
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

    # Import after env vars are set so module-level config reads them fresh.
    # Reload deps first (module-level env-derived config + jwks_cache), then
    # the route modules (their `Depends(deps.require_tenant)` wiring and any
    # `deps.<CONST>` references are captured at each module's *own* import/
    # decoration time), then main last so it re-registers routers pointing
    # at the freshly-reloaded route modules.
    import importlib

    import kaizen.api.deps as deps_module
    import kaizen.api.routes_brands as routes_brands_module
    import kaizen.api.routes_jobs as routes_jobs_module
    import kaizen.api.main as main_module

    importlib.reload(deps_module)
    importlib.reload(routes_brands_module)
    importlib.reload(routes_jobs_module)
    importlib.reload(main_module)

    monkeypatch.setattr(deps_module.jwks_cache, "_fetch_jwks", lambda: jwks_document)

    return TestClient(main_module.app)


def _auth_headers(rsa_keypair, *, sub: str) -> dict[str, str]:
    token = _make_token(rsa_keypair, sub=sub)
    return {"Authorization": f"Bearer {token}"}


class TestAuthBoundary:
    def test_missing_authorization_header_returns_401(self, client: TestClient) -> None:
        response = client.post("/v1/brands", json={"url": "https://acme.example.com"})
        assert response.status_code == 401

    def test_garbage_bearer_token_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/v1/brands",
            json={"url": "https://acme.example.com"},
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert response.status_code == 401

    def test_brand_id_hint_mismatch_returns_403(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
        )
        brand_id = create_resp.json()["brand_id"]

        other_headers = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.get(f"/v1/brands/{brand_id}", headers=other_headers)

        assert response.status_code == 403


class TestCreateBrand:
    def test_provisions_tenant_dir_under_profiles_dir(
        self, client: TestClient, rsa_keypair, profiles_dir: Path
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")

        response = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
        )

        assert response.status_code == 201
        body = response.json()
        assert "brand_id" in body
        assert "home" in body

        tenant_dirs = list(profiles_dir.iterdir())
        assert len(tenant_dirs) == 1
        assert (tenant_dirs[0] / "SOUL.md").exists()
        assert (tenant_dirs[0] / "AGENTS.md").exists()

    def test_returned_brand_id_is_scoped_to_the_tenant(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")

        response = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
        )
        brand_id = response.json()["brand_id"]

        get_resp = client.get(f"/v1/brands/{brand_id}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["brand_id"] == brand_id


class TestGetBrandNotFound:
    def test_unknown_brand_id_returns_404(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        response = client.get("/v1/brands/does-not-exist", headers=headers)
        assert response.status_code == 404


class TestOnboardingJobAndStream:
    def test_onboard_enqueues_job_and_stream_yields_step_then_final(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")

        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
        )
        brand_id = create_resp.json()["brand_id"]

        onboard_resp = client.post(f"/v1/brands/{brand_id}/onboard", headers=headers)
        assert onboard_resp.status_code == 202
        job_id = onboard_resp.json()["job_id"]

        with client.stream(
            "GET", f"/v1/jobs/{job_id}/stream", headers=headers
        ) as stream_resp:
            assert stream_resp.status_code == 200
            assert "text/event-stream" in stream_resp.headers["content-type"]

            event_types: list[str] = []
            for raw_line in stream_resp.iter_lines():
                if not raw_line:
                    continue
                if not raw_line.startswith("data:"):
                    continue
                payload = json.loads(raw_line[len("data:"):].strip())
                event_types.append(payload["type"])
                if payload["type"] in ("final", "error"):
                    break

        assert "step" in event_types
        assert "final" in event_types
        assert event_types.index("step") < event_types.index("final")

    def test_job_status_endpoint_reaches_done(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")

        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers
        )
        brand_id = create_resp.json()["brand_id"]
        onboard_resp = client.post(f"/v1/brands/{brand_id}/onboard", headers=headers)
        job_id = onboard_resp.json()["job_id"]

        # Drain the stream to completion first (deterministic wait for the
        # background job instead of a timing-based sleep loop).
        with client.stream("GET", f"/v1/jobs/{job_id}/stream", headers=headers) as stream_resp:
            for raw_line in stream_resp.iter_lines():
                if raw_line.startswith("data:"):
                    payload = json.loads(raw_line[len("data:"):].strip())
                    if payload["type"] in ("final", "error"):
                        break

        status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "done"

    def test_unknown_job_id_returns_404(self, client: TestClient, rsa_keypair) -> None:
        headers = _auth_headers(rsa_keypair, sub="tenant-a")
        response = client.get("/v1/jobs/does-not-exist", headers=headers)
        assert response.status_code == 404

    def test_job_belonging_to_other_tenant_returns_403(
        self, client: TestClient, rsa_keypair
    ) -> None:
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers_a
        )
        brand_id = create_resp.json()["brand_id"]
        onboard_resp = client.post(f"/v1/brands/{brand_id}/onboard", headers=headers_a)
        job_id = onboard_resp.json()["job_id"]

        headers_b = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.get(f"/v1/jobs/{job_id}", headers=headers_b)
        assert response.status_code == 403

    def test_stream_of_job_belonging_to_other_tenant_returns_403(
        self, client: TestClient, rsa_keypair
    ) -> None:
        """Regression: GET /v1/jobs/{id}/stream (the SSE endpoint) must
        enforce the same tenant-ownership check as the job-status endpoint.
        An unauthenticated or cross-tenant SSE subscription must never
        leak another tenant's run events."""
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers_a
        )
        brand_id = create_resp.json()["brand_id"]
        onboard_resp = client.post(f"/v1/brands/{brand_id}/onboard", headers=headers_a)
        job_id = onboard_resp.json()["job_id"]

        # Drain tenant-a's own stream to completion first so the background
        # job doesn't leak into other tests.
        with client.stream(
            "GET", f"/v1/jobs/{job_id}/stream", headers=headers_a
        ) as stream_resp:
            assert stream_resp.status_code == 200
            for raw_line in stream_resp.iter_lines():
                if raw_line.startswith("data:"):
                    payload = json.loads(raw_line[len("data:"):].strip())
                    if payload["type"] in ("final", "error"):
                        break

        headers_b = _auth_headers(rsa_keypair, sub="tenant-b")
        response = client.get(f"/v1/jobs/{job_id}/stream", headers=headers_b)
        assert response.status_code == 403

    def test_stream_without_authentication_returns_401(
        self, client: TestClient, rsa_keypair
    ) -> None:
        """Regression: the SSE endpoint must require a valid bearer token,
        not just job-ownership -- an unauthenticated request must never
        reach the point of streaming any job's events."""
        headers_a = _auth_headers(rsa_keypair, sub="tenant-a")
        create_resp = client.post(
            "/v1/brands", json={"url": "https://acme.example.com"}, headers=headers_a
        )
        brand_id = create_resp.json()["brand_id"]
        onboard_resp = client.post(f"/v1/brands/{brand_id}/onboard", headers=headers_a)
        job_id = onboard_resp.json()["job_id"]

        with client.stream(
            "GET", f"/v1/jobs/{job_id}/stream", headers=headers_a
        ) as stream_resp:
            for raw_line in stream_resp.iter_lines():
                if raw_line.startswith("data:"):
                    payload = json.loads(raw_line[len("data:"):].strip())
                    if payload["type"] in ("final", "error"):
                        break

        response = client.get(f"/v1/jobs/{job_id}/stream")
        assert response.status_code == 401
