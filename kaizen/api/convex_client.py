"""Small HTTP client for the Convex data/auth layer.

FastAPI receives the same Convex Auth JWT that the frontend uses. When
``CONVEX_URL`` is configured, the control plane forwards that bearer token
to Convex's HTTP API so every mutation still derives tenantId from
``ctx.auth.getUserIdentity()`` inside Convex.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from kaizen.profile import BrandProfile

_CONVEX_TIMEOUT_SECONDS = 8.0


class ConvexAPIError(RuntimeError):
    """Raised when the configured Convex deployment rejects a mutation."""


def is_convex_configured() -> bool:
    return bool(os.environ.get("CONVEX_URL", "").strip())


def _convex_url() -> str:
    return os.environ.get("CONVEX_URL", "").strip().rstrip("/")


def _brand_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or parsed.path or url


def _mutation(path: str, args: dict, *, bearer_token: str) -> object:
    convex_url = _convex_url()
    if not convex_url:
        raise ConvexAPIError("CONVEX_URL is not configured")
    if not bearer_token:
        raise ConvexAPIError("Convex mutation requires the caller's bearer token")

    payload = {"path": path, "args": args, "format": "json"}
    headers = {"Authorization": f"Bearer {bearer_token}"}

    try:
        with httpx.Client(timeout=_CONVEX_TIMEOUT_SECONDS) as client:
            response = client.post(f"{convex_url}/api/mutation", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ConvexAPIError(f"Convex mutation {path} failed before response: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise ConvexAPIError(
            f"Convex mutation {path} returned HTTP {response.status_code}: {detail}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise ConvexAPIError(f"Convex mutation {path} returned non-JSON response") from exc

    if isinstance(body, dict) and body.get("status") == "error":
        error = body.get("errorMessage") or body.get("error") or body
        raise ConvexAPIError(f"Convex mutation {path} failed: {error}")

    if isinstance(body, dict) and "value" in body:
        return body["value"]
    return body


def create_brand(url: str, *, bearer_token: str) -> str:
    value = _mutation(
        "brands:createBrand",
        {"name": _brand_name_from_url(url), "url": url},
        bearer_token=bearer_token,
    )
    if not isinstance(value, str):
        raise ConvexAPIError("Convex brands:createBrand did not return a brand id")
    return value


def update_brand_status(brand_id: str, status: str, *, bearer_token: str) -> None:
    _mutation(
        "brands:updateBrandStatus",
        {"brandId": brand_id, "status": status},
        bearer_token=bearer_token,
    )


def create_job(job_id: str, brand_id: str | None, *, bearer_token: str) -> None:
    args: dict[str, object] = {"jobId": job_id, "type": "onboarding"}
    if brand_id is not None:
        args["brandId"] = brand_id
    _mutation("jobs:createJob", args, bearer_token=bearer_token)


def update_job_status(
    job_id: str,
    status: str,
    *,
    bearer_token: str,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    args: dict[str, object] = {"jobId": job_id, "status": status}
    if error is not None:
        args["error"] = error
    if result is not None:
        args["result"] = result
    _mutation("jobs:updateJobStatus", args, bearer_token=bearer_token)


def upsert_brand_profile(brand_id: str, profile: BrandProfile, *, bearer_token: str) -> None:
    _mutation(
        "profile:upsertBrandProfile",
        {
            "brandId": brand_id,
            "positioning": profile.positioning,
            "voiceTone": profile.voice_tone,
            "audience": profile.audience,
            "dos": profile.dos,
            "donts": profile.donts,
            "guardrails": profile.guardrails,
            "channels": profile.channels,
        },
        bearer_token=bearer_token,
    )
