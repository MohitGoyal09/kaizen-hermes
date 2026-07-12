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


def _convex_function(kind: str, path: str, args: dict, *, bearer_token: str) -> object:
    convex_url = _convex_url()
    if not convex_url:
        raise ConvexAPIError("CONVEX_URL is not configured")
    if not bearer_token:
        raise ConvexAPIError("Convex function requires the caller's bearer token")

    payload = {"path": path, "args": args, "format": "json"}
    headers = {"Authorization": f"Bearer {bearer_token}"}
    endpoint = "api/mutation" if kind == "mutation" else "api/query"

    try:
        with httpx.Client(timeout=_CONVEX_TIMEOUT_SECONDS) as client:
            response = client.post(f"{convex_url}/{endpoint}", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ConvexAPIError(f"Convex {kind} {path} failed before response: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise ConvexAPIError(
            f"Convex {kind} {path} returned HTTP {response.status_code}: {detail}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise ConvexAPIError(f"Convex {kind} {path} returned non-JSON response") from exc

    if isinstance(body, dict) and body.get("status") == "error":
        error = body.get("errorMessage") or body.get("error") or body
        raise ConvexAPIError(f"Convex {kind} {path} failed: {error}")

    if isinstance(body, dict) and "value" in body:
        return body["value"]
    return body


def _mutation(path: str, args: dict, *, bearer_token: str) -> object:
    return _convex_function("mutation", path, args, bearer_token=bearer_token)


def _query(path: str, args: dict, *, bearer_token: str) -> object:
    return _convex_function("query", path, args, bearer_token=bearer_token)


def _require_object(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise ConvexAPIError(f"Convex {path} did not return an object")
    return value


def _require_array(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise ConvexAPIError(f"Convex {path} did not return an array")
    return value


def _without_none(args: dict) -> dict:
    return {key: value for key, value in args.items() if value is not None}


def create_brand(url: str, *, bearer_token: str) -> str:
    value = _mutation(
        "brands:createBrand",
        {"name": _brand_name_from_url(url), "url": url},
        bearer_token=bearer_token,
    )
    if not isinstance(value, str):
        raise ConvexAPIError("Convex brands:createBrand did not return a brand id")
    return value


def list_brands(*, bearer_token: str) -> list:
    return _require_array(_query("brands:listBrands", {}, bearer_token=bearer_token), "brands:listBrands")


def get_brand_profile(brand_id: str, *, bearer_token: str) -> dict | None:
    value = _query("profile:getBrandProfile", {"brandId": brand_id}, bearer_token=bearer_token)
    if value is None:
        return None
    return _require_object(value, "profile:getBrandProfile")


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


def get_job(job_id: str, *, bearer_token: str) -> dict | None:
    value = _query("jobs:getJob", {"jobId": job_id}, bearer_token=bearer_token)
    if value is None:
        return None
    return _require_object(value, "jobs:getJob")


def list_jobs(*, bearer_token: str) -> list:
    return _require_array(_query("jobs:listJobs", {}, bearer_token=bearer_token), "jobs:listJobs")


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


def create_campaign(
    *,
    brand_id: str,
    name: str,
    goal: str | None = None,
    channels: list[str] | None = None,
    formats: list[str] | None = None,
    status: str = "draft",
    bearer_token: str,
) -> dict:
    value = _mutation(
        "campaigns:createCampaign",
        _without_none(
            {
                "brandId": brand_id,
                "name": name,
                "goal": goal,
                "channels": channels,
                "formats": formats,
                "status": status,
            }
        ),
        bearer_token=bearer_token,
    )
    return _require_object(value, "campaigns:createCampaign")


def list_campaigns(*, bearer_token: str) -> list:
    return _require_array(
        _query("campaigns:listCampaigns", {}, bearer_token=bearer_token),
        "campaigns:listCampaigns",
    )


def get_campaign(campaign_id: str, *, bearer_token: str) -> dict | None:
    value = _query(
        "campaigns:getCampaign",
        {"campaignId": campaign_id},
        bearer_token=bearer_token,
    )
    if value is None:
        return None
    return _require_object(value, "campaigns:getCampaign")


def list_posts(campaign_id: str | None = None, *, bearer_token: str) -> list:
    return _require_array(
        _query(
            "posts:listPosts",
            _without_none({"campaignId": campaign_id}),
            bearer_token=bearer_token,
        ),
        "posts:listPosts",
    )


def list_eval_runs(*, bearer_token: str) -> list:
    return _require_array(
        _query("evals:listEvalRuns", {}, bearer_token=bearer_token),
        "evals:listEvalRuns",
    )


def get_eval_run(run_id: str, *, bearer_token: str) -> dict | None:
    value = _query("evals:getEvalRun", {"runId": run_id}, bearer_token=bearer_token)
    if value is None:
        return None
    return _require_object(value, "evals:getEvalRun")


def list_engagement(*, bearer_token: str) -> list:
    return _require_array(
        _query("engagement:listEngagement", {}, bearer_token=bearer_token),
        "engagement:listEngagement",
    )


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
