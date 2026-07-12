"""``/v1/brands/{id}/publish`` route: post a generated marketing post to a
real external social channel via Composio.

Primary channel: **LinkedIn** (Composio ``linkedin`` toolkit, OAuth managed by
Composio). ``x`` (Twitter) is also supported. Same auth boundary + owned-brand
guard as the other routes: ``Depends(deps.require_tenant)`` derives ``tenant_id``
from the verified JWT (never a client field); ``_get_owned_brand_or_404_403``
→ 404 unknown / 403 wrong tenant.

Composio specifics (installed ``composio==1.0.0-rc2``):
- ``tools.execute`` requires an explicit toolkit version; we pass
  ``dangerously_skip_version_check=True`` (demo posture — always use the latest
  tool version) rather than pinning a version.
- The connected social account lives under a fixed Composio ``user_id``
  (``COMPOSIO_USER_ID`` env — the id the account was authorized under), NOT the
  per-brand id, so every tenant's publish uses the one connected account.
- LinkedIn's ``LINKEDIN_CREATE_LINKED_IN_POST`` requires an ``author`` URN
  (``urn:li:person:<id>``) + ``commentary``. The URN is fetched once via
  ``LINKEDIN_GET_MY_INFO`` and cached per user_id.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from kaizen.api import deps
from kaizen.api.brand_store import BrandRecord, BrandStore
from kaizen.api.publish_store import PublishedPost, PublishStore

router = APIRouter(prefix="/v1/brands", tags=["publish"])

_LINKEDIN_CREATE_POST_TOOL = "LINKEDIN_CREATE_LINKED_IN_POST"
_LINKEDIN_GET_ME_TOOL = "LINKEDIN_GET_MY_INFO"
_TWITTER_CREATE_POST_TOOL = "TWITTER_CREATION_OF_A_POST"
_SUPPORTED_CHANNELS = ("linkedin", "x")
_COMPOSIO_NOT_CONFIGURED_MESSAGE = (
    "Composio not configured -- set COMPOSIO_API_KEY and connect a social account"
)

# LinkedIn author URN is stable per connected account; cache it per user_id.
_author_cache: dict[str, str] = {}
_author_lock = threading.Lock()


class PublishRequest(BaseModel):
    text: str
    channel: str = "linkedin"
    image_url: str | None = None


class PublishResponse(BaseModel):
    ok: bool
    channel: str
    url: str | None
    id: str | None
    raw: dict[str, Any]


class PublishedPostResponse(BaseModel):
    id: str
    channel: str
    text: str
    url: str | None
    provider_id: str | None
    status: str
    ts: float


def _get_owned_brand_or_404_403(brand_store: BrandStore, brand_id: str, tenant_id: str) -> BrandRecord:
    record = brand_store.get(brand_id)
    if record is None:
        raise HTTPException(status_code=404, detail="brand not found")
    deps.guard_tenant_hint(record.tenant_id, tenant_id)
    return record


def _composio_user_id() -> str:
    """The Composio end-user id the social account is connected under."""
    return os.environ.get("COMPOSIO_USER_ID", "").strip() or "kaizen"


def _composio_client():
    from composio import Composio  # local import: only on the publish path

    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise RuntimeError(_COMPOSIO_NOT_CONFIGURED_MESSAGE)
    return Composio(api_key=api_key)


def _execute(client, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = client.tools.execute(
        slug,
        user_id=_composio_user_id(),
        arguments=arguments,
        dangerously_skip_version_check=True,
    )
    result = dict(result) if not isinstance(result, dict) else result
    if result.get("successful") is False:
        raise RuntimeError(str(result.get("error") or f"{slug} failed"))
    return result


def _linkedin_author_urn(client) -> str:
    uid = _composio_user_id()
    with _author_lock:
        cached = _author_cache.get(uid)
    if cached:
        return cached
    info = _execute(client, _LINKEDIN_GET_ME_TOOL, {})
    data = info.get("data") or {}
    person_id = data.get("id")
    if not person_id:
        raise RuntimeError("could not resolve LinkedIn author id from LINKEDIN_GET_MY_INFO")
    urn = f"urn:li:person:{person_id}"
    with _author_lock:
        _author_cache[uid] = urn
    return urn


def _linkedin_url_from_id(post_id: str | None) -> str | None:
    if not post_id:
        return None
    urn = post_id if str(post_id).startswith("urn:li:") else f"urn:li:share:{post_id}"
    return f"https://www.linkedin.com/feed/update/{urn}"


def _extract_id(raw: dict[str, Any]) -> str | None:
    """Best-effort pull of the provider post id from Composio's response."""
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, dict):
        for key in ("id", "share_id", "ugcPostId", "activity"):
            if data.get(key):
                return str(data[key])
        inner = data.get("data")
        if isinstance(inner, dict) and inner.get("id"):
            return str(inner["id"])
    return None


def _trim_raw(raw: Any, *, max_len: int = 2000) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"value": str(raw)[:max_len]}
    if len(str(raw)) <= max_len:
        return raw
    return {
        "data": raw.get("data"),
        "error": raw.get("error"),
        "successful": raw.get("successful"),
        "_truncated": True,
    }


def _publish_to_linkedin(text: str, image_url: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    client = _composio_client()
    author = _linkedin_author_urn(client)
    commentary = f"{text}\n\n{image_url}" if image_url else text
    raw = _execute(client, _LINKEDIN_CREATE_POST_TOOL, {"author": author, "commentary": commentary})
    post_id = _extract_id(raw)
    return raw, post_id, _linkedin_url_from_id(post_id)


def _publish_to_x(text: str, image_url: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    client = _composio_client()
    args = {"text": f"{text}\n\n{image_url}" if image_url else text}
    raw = _execute(client, _TWITTER_CREATE_POST_TOOL, args)
    tweet_id = _extract_id(raw)
    url = f"https://twitter.com/i/web/status/{tweet_id}" if tweet_id else None
    return raw, tweet_id, url


@router.post("/{brand_id}/publish", status_code=201, response_model=PublishResponse)
def publish(
    brand_id: str,
    body: PublishRequest,
    tenant_id: str = Depends(deps.require_tenant),
) -> PublishResponse:
    """Publish a generated post to a real social channel (LinkedIn / X) via
    Composio. Missing config → 400; any provider/network error → 502 (never 500)."""
    from kaizen.api.main import brand_store, publish_store

    record = _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    channel = body.channel.lower()
    if channel not in _SUPPORTED_CHANNELS:
        raise HTTPException(status_code=400, detail=f"unsupported channel: {body.channel!r}")
    if not os.environ.get("COMPOSIO_API_KEY"):
        raise HTTPException(status_code=400, detail=_COMPOSIO_NOT_CONFIGURED_MESSAGE)

    try:
        if channel == "linkedin":
            raw, provider_id, url = _publish_to_linkedin(body.text, body.image_url)
        else:
            raw, provider_id, url = _publish_to_x(body.text, body.image_url)
    except Exception as exc:  # noqa: BLE001 - provider/network errors must never 500
        raise HTTPException(status_code=502, detail=f"Composio publish failed: {exc}") from exc

    publish_store.record(
        brand_id=record.brand_id,
        channel=channel,
        text=body.text,
        url=url,
        provider_id=provider_id,
        status="posted",
    )

    return PublishResponse(ok=True, channel=channel, url=url, id=provider_id, raw=_trim_raw(raw))


@router.get("/{brand_id}/posts/published", response_model=list[PublishedPostResponse])
def list_published_posts(
    brand_id: str,
    tenant_id: str = Depends(deps.require_tenant),
) -> list[PublishedPostResponse]:
    """The tenant's published posts for this brand -- the "track the post" view,
    most-recent first."""
    from kaizen.api.main import brand_store, publish_store

    _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    posts: list[PublishedPost] = publish_store.list_for_brand(brand_id)
    return [
        PublishedPostResponse(
            id=post.id, channel=post.channel, text=post.text, url=post.url,
            provider_id=post.provider_id, status=post.status, ts=post.ts,
        )
        for post in posts
    ]
