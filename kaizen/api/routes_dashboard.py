"""Tenant-scoped dashboard API routes consumed by the Kaizen web app.

Convex is the durable source of truth when ``CONVEX_URL`` is configured.
When it is not configured, these routes expose only data created through
this FastAPI process' in-memory stores and otherwise return empty states.
No bundled demo/mock brand data is served from this module.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kaizen.api import convex_client, deps
from kaizen.api.brand_store import BrandRecord, BrandStore
from kaizen.api.campaign_store import CampaignRecord, CampaignStore
from kaizen.api.job_store import Job, JobStore
from kaizen.profile import BrandProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["dashboard"])

_CampaignStatus = Literal["draft", "active", "completed", "archived"]


class CreateCampaignRequest(BaseModel):
    name: str | None = None
    title: str | None = None
    goal: str | None = None
    objective: str | None = None
    channels: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    status: _CampaignStatus = "draft"
    brand_id: str | None = None


_CHANNEL_LABELS = {
    "x": "X",
    "telegram": "Telegram",
    "blog": "Blog",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
}

# Channels the publish pipeline (Composio, see routes_publish.py) actually
# supports today. GET /v1/channels always offers at least these, regardless
# of what a brand's onboarding profile happened to record in `channels` --
# a brand with an empty/missing `channels` list must still be able to pick a
# channel and create a campaign (the "no channels returned" demo blocker).
# LinkedIn is primary/first: it's the one with a live Composio connection.
_SUPPORTED_CHANNELS: tuple[str, ...] = ("linkedin", "x")
_CONNECTED_CHANNELS: frozenset[str] = frozenset({"linkedin"})


def _web_status(status: str | None) -> str:
    if status == "active":
        return "running"
    if status == "completed":
        return "published"
    if status in {"draft", "running", "review", "published", "failed", "queued", "done"}:
        return status
    return "draft"


def _iso_from_ms(value: Any) -> str:
    if isinstance(value, (int, float)):
        import datetime as _dt

        # Convex stores ms. In-process stores pass ms too.
        return _dt.datetime.fromtimestamp(value / 1000, tz=_dt.UTC).isoformat()
    return ""


def _voice_list(voice_tone: str) -> list[str]:
    return [part.strip() for part in voice_tone.replace(";", ",").split(",") if part.strip()]


def _channel_response(channel: str) -> dict[str, Any]:
    label = _CHANNEL_LABELS.get(channel, channel.replace("_", " ").title())
    if channel in _CONNECTED_CHANNELS:
        status = "connected"
        description = f"{label} is connected via Composio -- posts publish live."
    else:
        status = "draft_only"
        description = f"Draft generation is available for {label}."
    return {
        "id": channel,
        "label": label,
        "status": status,
        "health": "healthy",
        "description": description,
    }


def _warn_convex_fallback(operation: str, exc: convex_client.ConvexAPIError) -> None:
    logger.warning("Convex %s unavailable; using process-local fallback: %s", operation, exc)


def _profile_response(profile: BrandProfile | dict | None) -> dict[str, Any]:
    if profile is None:
        return {
            "positioning": "",
            "voice_tone": "",
            "voiceTone": "",
            "audience": "",
            "dos": [],
            "donts": [],
            "guardrails": [],
            "channels": [],
        }

    if isinstance(profile, BrandProfile):
        voice_tone = profile.voice_tone
        return {
            "positioning": profile.positioning,
            "voice_tone": voice_tone,
            "voiceTone": voice_tone,
            "audience": profile.audience,
            "dos": list(profile.dos),
            "donts": list(profile.donts),
            "guardrails": list(profile.guardrails),
            "channels": list(profile.channels),
        }

    voice_tone = str(profile.get("voiceTone") or profile.get("voice_tone") or "")
    return {
        "positioning": str(profile.get("positioning") or ""),
        "voice_tone": voice_tone,
        "voiceTone": voice_tone,
        "audience": str(profile.get("audience") or ""),
        "dos": list(profile.get("dos") or []),
        "donts": list(profile.get("donts") or []),
        "guardrails": list(profile.get("guardrails") or []),
        "channels": list(profile.get("channels") or []),
        "updated_at": profile.get("updatedAt"),
        "updatedAt": profile.get("updatedAt"),
    }


def _brand_doc_response(doc: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    brand_id = str(doc.get("_id") or doc.get("brand_id") or doc.get("id") or "")
    created_at = doc.get("createdAt") or doc.get("_creationTime")
    brand_profile = _profile_response(profile)
    name = doc.get("name") or doc.get("url") or ""
    voice = _voice_list(str(brand_profile["voiceTone"]))
    channels = _channels_from_brand({"channels": brand_profile["channels"], "profile": brand_profile})
    return {
        "id": brand_id,
        "brand_id": brand_id,
        "brandId": brand_id,
        "tenant_id": doc.get("tenantId"),
        "tenantId": doc.get("tenantId"),
        "name": name,
        "url": doc.get("url") or "",
        "category": "",
        "audience": brand_profile["audience"],
        "positioning": brand_profile["positioning"],
        "voice": voice,
        "guardrails": brand_profile["guardrails"],
        "colors": [],
        "status": doc.get("status") or "provisioned",
        "created_at": created_at,
        "createdAt": _iso_from_ms(created_at),
        "profile": brand_profile,
        "channels": channels,
    }


def _brand_record_response(record: BrandRecord) -> dict[str, Any]:
    created_at_ms = int(record.created_at * 1000)
    brand_profile = _profile_response(record.profile)
    voice = _voice_list(str(brand_profile["voiceTone"]))
    channels = _channels_from_brand({"channels": brand_profile["channels"], "profile": brand_profile})
    return {
        "id": record.brand_id,
        "brand_id": record.brand_id,
        "brandId": record.brand_id,
        "tenant_id": record.tenant_id,
        "tenantId": record.tenant_id,
        "name": record.profile.name,
        "url": record.url,
        "category": "",
        "audience": brand_profile["audience"],
        "positioning": brand_profile["positioning"],
        "voice": voice,
        "guardrails": brand_profile["guardrails"],
        "colors": [],
        "status": record.status,
        "home": str(record.home),
        "created_at": created_at_ms,
        "createdAt": _iso_from_ms(created_at_ms),
        "profile": brand_profile,
        "channels": channels,
    }


def _current_local_brand(brand_store: BrandStore, tenant_id: str) -> dict[str, Any] | None:
    record = brand_store.current_for_tenant(tenant_id)
    if record is None:
        return None
    return _brand_record_response(record)


def _current_convex_brand(bearer_token: str) -> dict[str, Any] | None:
    brands = convex_client.list_brands(bearer_token=bearer_token)
    if not brands:
        return None
    brand_docs = [brand for brand in brands if isinstance(brand, dict)]
    if not brand_docs:
        return None
    current = max(
        brand_docs,
        key=lambda brand: brand.get("createdAt") or brand.get("_creationTime") or 0,
    )
    try:
        profile = convex_client.get_brand_profile(str(current["_id"]), bearer_token=bearer_token)
    except convex_client.ConvexAPIError as exc:
        _warn_convex_fallback("brand profile read", exc)
        profile = None
    return _brand_doc_response(current, profile)


def _get_current_brand(
    *,
    bearer_token: str,
    tenant_id: str,
    brand_store: BrandStore,
) -> dict[str, Any] | None:
    if convex_client.is_convex_configured():
        try:
            return _current_convex_brand(bearer_token)
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("current brand read", exc)
    return _current_local_brand(brand_store, tenant_id)


def _current_brand_id_or_404(
    *,
    body_brand_id: str | None,
    bearer_token: str,
    tenant_id: str,
    brand_store: BrandStore,
) -> str:
    if body_brand_id is not None:
        local_record = brand_store.get(body_brand_id)
        if local_record is not None:
            deps.guard_tenant_hint(local_record.tenant_id, tenant_id)
        return body_brand_id

    current_brand = _get_current_brand(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        brand_store=brand_store,
    )
    if current_brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    return str(current_brand["brand_id"])


def _channels_from_brand(brand: dict[str, Any] | None) -> list[str]:
    if brand is None:
        return []
    raw_channels = brand.get("channels") or (brand.get("profile") or {}).get("channels") or []
    return [str(channel) for channel in raw_channels if str(channel).strip()]


def _campaign_doc_response(doc: dict[str, Any]) -> dict[str, Any]:
    campaign_id = str(doc.get("_id") or doc.get("campaign_id") or doc.get("id") or "")
    created_at = doc.get("createdAt") or doc.get("_creationTime")
    updated_at = doc.get("updatedAt") or created_at
    name = doc.get("name") or doc.get("title") or ""
    goal = doc.get("goal") or doc.get("objective") or ""
    channels = [str(channel) for channel in doc.get("channels") or []]
    formats = [str(fmt) for fmt in doc.get("formats") or []]
    status = _web_status(str(doc.get("status") or "draft"))
    return {
        "id": campaign_id,
        "campaign_id": campaign_id,
        "campaignId": campaign_id,
        "brand_id": doc.get("brandId") or doc.get("brand_id"),
        "brandId": doc.get("brandId") or doc.get("brand_id"),
        "name": name,
        "title": name,
        "goal": goal,
        "objective": goal,
        "status": status,
        "channels": channels,
        "formats": formats,
        "created_at": created_at,
        "createdAt": _iso_from_ms(created_at),
        "updated_at": updated_at,
        "updatedAt": _iso_from_ms(updated_at),
        "summary": doc.get("summary") or goal,
    }


def _campaign_record_response(record: CampaignRecord) -> dict[str, Any]:
    created_at_ms = int(record.created_at * 1000)
    updated_at_ms = int(record.updated_at * 1000)
    status = _web_status(record.status)
    return {
        "id": record.campaign_id,
        "campaign_id": record.campaign_id,
        "campaignId": record.campaign_id,
        "brand_id": record.brand_id,
        "brandId": record.brand_id,
        "name": record.name,
        "title": record.name,
        "goal": record.goal,
        "objective": record.goal or "",
        "status": status,
        "channels": record.channels,
        "formats": record.formats,
        "created_at": created_at_ms,
        "createdAt": _iso_from_ms(created_at_ms),
        "updated_at": updated_at_ms,
        "updatedAt": _iso_from_ms(updated_at_ms),
        "summary": record.goal or "",
    }


def _local_campaigns(campaign_store: CampaignStore, tenant_id: str) -> list[dict[str, Any]]:
    return [_campaign_record_response(campaign) for campaign in campaign_store.list_for_tenant(tenant_id)]


def _post_doc_response(doc: dict[str, Any]) -> dict[str, Any]:
    post_id = str(doc.get("_id") or doc.get("post_id") or doc.get("id") or "")
    created_at = doc.get("createdAt") or doc.get("_creationTime")
    published_at = doc.get("publishedAt")
    body = doc.get("body") or ""
    status = str(doc.get("status") or "draft")
    web_status = "approved" if status == "scheduled" else status
    if web_status not in {"draft", "approved", "published", "failed"}:
        web_status = "draft"
    title = str(doc.get("title") or body[:72] or "Untitled post")
    return {
        "id": post_id,
        "post_id": post_id,
        "postId": post_id,
        "brand_id": doc.get("brandId") or doc.get("brand_id"),
        "brandId": doc.get("brandId") or doc.get("brand_id"),
        "campaign_id": doc.get("campaignId") or doc.get("campaign_id"),
        "campaignId": doc.get("campaignId") or doc.get("campaign_id") or "",
        "title": title,
        "channel": doc.get("channel") or "",
        "format": doc.get("format") or "short_copy",
        "body": body,
        "content": body,
        "copy": body,
        "media_url": doc.get("mediaUrl"),
        "mediaUrl": doc.get("mediaUrl"),
        "status": web_status,
        "score": doc.get("score") or 0,
        "engagement": {"impressions": 0, "clicks": 0, "reactions": 0},
        "publishedUrl": doc.get("publishedUrl"),
        "published_at": published_at,
        "publishedAt": published_at,
        "created_at": created_at,
        "createdAt": _iso_from_ms(created_at),
    }


def _job_doc_run_response(doc: dict[str, Any]) -> dict[str, Any]:
    job_id = str(doc.get("jobId") or doc.get("job_id") or doc.get("_id") or "")
    created_at = doc.get("createdAt") or doc.get("_creationTime")
    updated_at = doc.get("updatedAt")
    campaign_id = str(doc.get("campaignId") or doc.get("campaign_id") or doc.get("brandId") or "")
    return {
        "id": job_id,
        "run_id": job_id,
        "runId": job_id,
        "job_id": job_id,
        "jobId": job_id,
        "brand_id": doc.get("brandId") or doc.get("brand_id"),
        "brandId": doc.get("brandId") or doc.get("brand_id"),
        "campaign_id": campaign_id,
        "campaignId": campaign_id,
        "events": [],
        "type": doc.get("type") or "job",
        "status": doc.get("status") or "queued",
        "error": doc.get("error"),
        "result": doc.get("result"),
        "created_at": created_at,
        "createdAt": _iso_from_ms(created_at),
        "updated_at": updated_at,
        "updatedAt": _iso_from_ms(updated_at),
        "source": "job",
    }


def _event_type(raw_type: str) -> str:
    return {
        "tool_start": "tool.started",
        "tool_complete": "tool.completed",
        "final": "job.completed",
        "error": "job.failed",
        "step": "agent.started",
        "text_delta": "agent.completed",
    }.get(raw_type, "agent.completed")


def _event_detail(event: dict[str, Any]) -> str:
    data = event.get("data")
    if not isinstance(data, dict):
        return ""
    if "delta" in data:
        return str(data["delta"])
    if "final_response" in data:
        return str(data["final_response"])
    if "message" in data:
        return str(data["message"])
    if "name" in data:
        return str(data["name"])
    if "iteration" in data:
        return f"Iteration {data['iteration']}"
    return str(data)


def _run_events(job: Job) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, event in enumerate(job.events):
        raw_type = str(event.get("type") or "step")
        ts = event.get("ts")
        ts_ms = ts * 1000 if isinstance(ts, (int, float)) and ts < 10_000_000_000 else ts
        events.append(
            {
                "id": f"{job.job_id}-{index}",
                "jobId": job.job_id,
                "job_id": job.job_id,
                "runId": job.job_id,
                "run_id": job.job_id,
                "ts": _iso_from_ms(ts_ms) if ts_ms is not None else _iso_from_ms(int(job.updated_at * 1000)),
                "type": _event_type(raw_type),
                "agent": "orchestrator",
                "title": raw_type.replace("_", " ").title(),
                "detail": _event_detail(event),
                "costUsd": 0,
            }
        )
    return events


def _job_record_run_response(job: Job) -> dict[str, Any]:
    created_at_ms = int(job.created_at * 1000)
    updated_at_ms = int(job.updated_at * 1000)
    campaign_id = job.brand_id or ""
    return {
        "id": job.job_id,
        "run_id": job.job_id,
        "runId": job.job_id,
        "job_id": job.job_id,
        "jobId": job.job_id,
        "brand_id": job.brand_id,
        "brandId": job.brand_id,
        "campaign_id": campaign_id,
        "campaignId": campaign_id,
        "events": _run_events(job),
        "type": job.type,
        "status": job.status,
        "error": job.error,
        "result": job.result,
        "event_count": len(job.events),
        "created_at": created_at_ms,
        "createdAt": _iso_from_ms(created_at_ms),
        "updated_at": updated_at_ms,
        "updatedAt": _iso_from_ms(updated_at_ms),
        "source": "job",
    }


def _eval_doc_run_response(doc: dict[str, Any]) -> dict[str, Any]:
    run_id = str(doc.get("_id") or doc.get("run_id") or doc.get("id") or "")
    created_at = doc.get("createdAt") or doc.get("_creationTime")
    predicted = doc.get("predictedScore")
    actual = doc.get("actualScore")
    return {
        "id": run_id,
        "run_id": run_id,
        "runId": run_id,
        "job_id": run_id,
        "jobId": run_id,
        "brand_id": doc.get("brandId"),
        "brandId": doc.get("brandId"),
        "campaign_id": "",
        "campaignId": "",
        "events": [],
        "post_id": doc.get("postId"),
        "type": "eval",
        "status": "done",
        "predicted_score": predicted,
        "predictedScore": predicted,
        "actual_score": actual,
        "actualScore": actual,
        "rationale": doc.get("rationale"),
        "created_at": created_at,
        "createdAt": _iso_from_ms(created_at),
        "source": "eval_run",
    }


def _local_runs(job_store: JobStore, tenant_id: str) -> list[dict[str, Any]]:
    return [_job_record_run_response(job) for job in job_store.list_for_tenant(tenant_id)]


def _sum_metric(rows: list[dict[str, Any]], key: str) -> int:
    total = 0
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _analytics_summary(
    *,
    campaigns: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    eval_runs: list[dict[str, Any]],
    engagement: list[dict[str, Any]],
) -> dict[str, Any]:
    predicted_scores = [
        float(row["predictedScore"])
        for row in eval_runs
        if isinstance(row.get("predictedScore"), (int, float))
    ]
    actual_scores = [
        float(row["actualScore"])
        for row in eval_runs
        if isinstance(row.get("actualScore"), (int, float))
    ]
    by_channel: dict[str, dict[str, Any]] = {}
    for row in engagement:
        channel = str(row.get("channel") or "unknown")
        bucket = by_channel.setdefault(
            channel,
            {"channel": channel, "likes": 0, "shares": 0, "comments": 0, "impressions": 0},
        )
        for metric in ("likes", "shares", "comments", "impressions"):
            value = row.get(metric)
            if isinstance(value, (int, float)):
                bucket[metric] += int(value)
        clicks = row.get("clicks")
        if isinstance(clicks, (int, float)):
            bucket["clicks"] = bucket.get("clicks", 0) + int(clicks)

    avg_predicted = _average(predicted_scores)
    avg_actual = _average(actual_scores)
    score_delta = None
    if avg_predicted is not None and avg_actual is not None:
        score_delta = avg_actual - avg_predicted

    channel_performance = [
        {
            "channel": channel,
            "impressions": int(metrics.get("impressions") or 0),
            "clicks": int(metrics.get("clicks") or 0),
            "posts": len([post for post in posts if post.get("channel") == channel]),
        }
        for channel, metrics in by_channel.items()
    ]
    published_posts = len([post for post in posts if post.get("status") == "published"])
    impressions = _sum_metric(engagement, "impressions")
    clicks = _sum_metric(engagement, "clicks")

    return {
        "window": "Last 14 days",
        "totals": {
            "campaigns": len(campaigns),
            "publishedPosts": published_posts,
            "impressions": impressions,
            "clicks": clicks,
            "costUsd": 0,
            "posts": len(posts),
            "runs": len(runs),
            "eval_runs": len(eval_runs),
            "engagement_rows": len(engagement),
            "likes": _sum_metric(engagement, "likes"),
            "shares": _sum_metric(engagement, "shares"),
            "comments": _sum_metric(engagement, "comments"),
        },
        "evals": {
            "count": len(eval_runs),
            "average_predicted_score": avg_predicted,
            "average_actual_score": avg_actual,
            "average_score_delta": score_delta,
        },
        "by_channel": list(by_channel.values()),
        "channelPerformance": channel_performance,
        "recentWins": [],
        "recent_runs": runs[:10],
    }


def _convex_campaigns_or_local(
    *, bearer_token: str, tenant_id: str, campaign_store: CampaignStore
) -> list[dict[str, Any]]:
    if convex_client.is_convex_configured():
        try:
            return [
                _campaign_doc_response(campaign)
                for campaign in convex_client.list_campaigns(bearer_token=bearer_token)
                if isinstance(campaign, dict)
            ]
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("campaign list", exc)
    return _local_campaigns(campaign_store, tenant_id)


def _convex_posts_or_empty(
    *, bearer_token: str, campaign_id: str | None = None
) -> list[dict[str, Any]]:
    if not convex_client.is_convex_configured():
        return []
    try:
        return [
            _post_doc_response(post)
            for post in convex_client.list_posts(campaign_id, bearer_token=bearer_token)
            if isinstance(post, dict)
        ]
    except convex_client.ConvexAPIError as exc:
        _warn_convex_fallback("post list", exc)
        return []


def _convex_runs_or_local(
    *, bearer_token: str, tenant_id: str, job_store: JobStore
) -> list[dict[str, Any]]:
    if convex_client.is_convex_configured():
        try:
            job_runs = [
                _job_doc_run_response(job)
                for job in convex_client.list_jobs(bearer_token=bearer_token)
                if isinstance(job, dict)
            ]
            eval_runs = [
                _eval_doc_run_response(run)
                for run in convex_client.list_eval_runs(bearer_token=bearer_token)
                if isinstance(run, dict)
            ]
            return job_runs + eval_runs
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("run list", exc)
    return _local_runs(job_store, tenant_id)


@router.get("/current-brand")
def get_current_brand(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any] | None:
    from kaizen.api.main import brand_store

    return _get_current_brand(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        brand_store=brand_store,
    )


def _available_channels(brand: dict[str, Any] | None) -> list[str]:
    """The channel ids to offer for campaign creation / the Library.

    No brand yet -> no channels (campaign creation isn't reachable without a
    brand regardless; matches the existing "no brand" empty state). Once a
    brand exists, always includes the publish-supported floor
    (`_SUPPORTED_CHANNELS`, LinkedIn first) so campaign creation works even
    when the brand's onboarding profile recorded no `channels` -- an empty
    profile must not disable channel selection (the "no channels returned"
    demo blocker). Any additional channels the brand's profile did record
    (e.g. "blog", "telegram") are appended after, deduped.
    """
    if brand is None:
        return []
    ordered = list(_SUPPORTED_CHANNELS)
    for channel in _channels_from_brand(brand):
        if channel not in ordered:
            ordered.append(channel)
    return ordered


@router.get("/channels")
def list_channels(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> list[dict[str, Any]]:
    from kaizen.api.main import brand_store

    brand = _get_current_brand(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        brand_store=brand_store,
    )
    return [_channel_response(channel) for channel in _available_channels(brand)]


@router.get("/campaigns")
def list_campaigns(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> list[dict[str, Any]]:
    from kaizen.api.main import campaign_store

    return _convex_campaigns_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        campaign_store=campaign_store,
    )


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: str,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any]:
    from kaizen.api.main import campaign_store

    if convex_client.is_convex_configured():
        try:
            campaign = convex_client.get_campaign(campaign_id, bearer_token=bearer_token)
            if campaign is not None:
                return _campaign_doc_response(campaign)
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("campaign read", exc)

    local_campaign = campaign_store.get(campaign_id)
    if local_campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    deps.guard_tenant_hint(local_campaign.tenant_id, tenant_id)
    return _campaign_record_response(local_campaign)


@router.post("/campaigns", status_code=201)
def create_campaign(
    body: CreateCampaignRequest,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any]:
    from kaizen.api.main import brand_store, campaign_store

    campaign_name = (body.title or body.name or "").strip()
    if not campaign_name:
        raise HTTPException(status_code=422, detail="campaign title is required")
    campaign_goal = body.objective if body.objective is not None else body.goal

    brand_id = _current_brand_id_or_404(
        body_brand_id=body.brand_id,
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        brand_store=brand_store,
    )

    if convex_client.is_convex_configured():
        try:
            return _campaign_doc_response(
                convex_client.create_campaign(
                    brand_id=brand_id,
                    name=campaign_name,
                    goal=campaign_goal,
                    channels=body.channels,
                    formats=body.formats,
                    status=body.status,
                    bearer_token=bearer_token,
                )
            )
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("campaign create", exc)

    local_record = brand_store.get(brand_id)
    if local_record is None:
        raise HTTPException(status_code=404, detail="brand not found")
    deps.guard_tenant_hint(local_record.tenant_id, tenant_id)
    campaign = campaign_store.create(
        tenant_id=tenant_id,
        brand_id=brand_id,
        name=campaign_name,
        goal=campaign_goal,
        channels=body.channels,
        formats=body.formats,
        status=body.status,
    )
    return _campaign_record_response(campaign)


@router.get("/posts")
def list_posts(
    campaign_id: str | None = Query(default=None),
    bearer_token: str = Depends(deps.require_bearer_token),
    _tenant_id: str = Depends(deps.require_tenant),
) -> list[dict[str, Any]]:
    return _convex_posts_or_empty(bearer_token=bearer_token, campaign_id=campaign_id)


@router.get("/runs")
def list_runs(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> list[dict[str, Any]]:
    from kaizen.api.main import job_store

    return _convex_runs_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        job_store=job_store,
    )


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any]:
    from kaizen.api.main import job_store

    if convex_client.is_convex_configured():
        try:
            job = convex_client.get_job(run_id, bearer_token=bearer_token)
            if job is not None:
                return _job_doc_run_response(job)
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("job run read", exc)

        try:
            eval_run = convex_client.get_eval_run(run_id, bearer_token=bearer_token)
            if eval_run is not None:
                return _eval_doc_run_response(eval_run)
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("eval run read", exc)

    local_job = job_store.get(run_id)
    if local_job is None:
        raise HTTPException(status_code=404, detail="run not found")
    deps.guard_tenant_hint(local_job.tenant_id, tenant_id)
    return _job_record_run_response(local_job)


@router.get("/analytics")
def get_analytics(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any]:
    from kaizen.api.main import campaign_store, job_store

    campaigns = _convex_campaigns_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        campaign_store=campaign_store,
    )
    posts = _convex_posts_or_empty(bearer_token=bearer_token)
    runs = _convex_runs_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        job_store=job_store,
    )

    eval_runs: list[dict[str, Any]] = []
    engagement: list[dict[str, Any]] = []
    if convex_client.is_convex_configured():
        try:
            eval_runs = [
                run
                for run in convex_client.list_eval_runs(bearer_token=bearer_token)
                if isinstance(run, dict)
            ]
            engagement = [
                row
                for row in convex_client.list_engagement(bearer_token=bearer_token)
                if isinstance(row, dict)
            ]
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("analytics read", exc)

    return _analytics_summary(
        campaigns=campaigns,
        posts=posts,
        runs=runs,
        eval_runs=eval_runs,
        engagement=engagement,
    )


@router.get("/orchestrator-workspace")
def get_orchestrator_workspace(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> dict[str, Any]:
    from kaizen.api.main import brand_store, campaign_store, job_store

    brand = _get_current_brand(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        brand_store=brand_store,
    )
    campaigns = _convex_campaigns_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        campaign_store=campaign_store,
    )
    posts = _convex_posts_or_empty(bearer_token=bearer_token)
    runs = _convex_runs_or_local(
        bearer_token=bearer_token,
        tenant_id=tenant_id,
        job_store=job_store,
    )

    eval_runs: list[dict[str, Any]] = []
    engagement: list[dict[str, Any]] = []
    if convex_client.is_convex_configured():
        try:
            eval_runs = [
                run
                for run in convex_client.list_eval_runs(bearer_token=bearer_token)
                if isinstance(run, dict)
            ]
            engagement = [
                row
                for row in convex_client.list_engagement(bearer_token=bearer_token)
                if isinstance(row, dict)
            ]
        except convex_client.ConvexAPIError as exc:
            _warn_convex_fallback("workspace analytics read", exc)

    next_steps = [
        {
            "id": "new-campaign",
            "label": "Create campaign",
            "detail": "Persist a campaign brief through the backend API.",
            "href": "/app/campaigns/new",
        }
    ]
    if brand is None:
        next_steps = [
            {
                "id": "onboard-brand",
                "label": "Onboard brand",
                "detail": "Create a brand profile before launching campaigns.",
                "href": "/app/onboarding",
            }
        ]

    return {
        "model": "Kaizen backend",
        "modes": ["Text", "Image", "Video", "Audio"],
        "prompts": [],
        "messages": [],
        "nextSteps": next_steps,
        "brand": brand,
        "channels": [_channel_response(channel) for channel in _available_channels(brand)],
        "campaigns": campaigns,
        "posts": posts,
        "runs": runs,
        "analytics": _analytics_summary(
            campaigns=campaigns,
            posts=posts,
            runs=runs,
            eval_runs=eval_runs,
            engagement=engagement,
        ),
    }
