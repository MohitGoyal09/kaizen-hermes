"""``/v1/brands/{id}/publish`` route: post a generated marketing post to a
real external channel via Composio -- X/Twitter today, extensible by
``channel`` later.

Same auth boundary and owned-brand guard as ``routes_content.py`` /
``routes_brands.py``: ``Depends(deps.require_tenant)`` resolves
``tenant_id`` from the verified JWT (never a client-supplied field), and
``_get_owned_brand_or_404_403`` turns an unknown brand into 404 and a brand
owned by a different tenant into 403.

Composio call (Python SDK ``composio`` package, confirmed against the
installed 0.13.0 API + https://docs.composio.dev):

    from composio import Composio
    composio = Composio(api_key=COMPOSIO_API_KEY)
    result = composio.tools.execute(
        "TWITTER_CREATION_OF_A_POST",
        user_id=<brand_id>,          # Composio's per-end-user identity;
                                      # brand_id doubles as that id here, so
                                      # each brand's connected X account is
                                      # looked up by brand_id.
        arguments={"text": ..., "media_media_ids": [...]},  # media only if resolved
    )

``TWITTER_CREATION_OF_A_POST`` is the Twitter toolkit's "Create a post"
action (see https://docs.composio.dev/toolkits/twitter): creates a Tweet,
``text`` required unless a card/media/poll/quote-tweet is supplied. It
returns ``{"data": ..., "error": ..., "successful": ...}``; ``data`` carries
the raw X API v2 response (``{"data": {"id": ..., "text": ...}}``) on
success. We do not have the account's handle from Composio's response, so
the tweet URL is built from the id-only permalink
(``https://twitter.com/i/web/status/{id}``), which resolves correctly
without needing the username.

This route does not attach media via a real upload pipeline (out of NOW
scope's time budget) -- if ``image_url`` is given we best-effort try the
media field Composio's schema exposes for it; if that fails we just append
the link to the tweet text so the image is still reachable from the post.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from kaizen.api import deps
from kaizen.api.brand_store import BrandRecord, BrandStore
from kaizen.api.publish_store import PublishedPost, PublishStore

router = APIRouter(prefix="/v1/brands", tags=["publish"])

_TWITTER_CREATE_POST_TOOL = "TWITTER_CREATION_OF_A_POST"
_COMPOSIO_NOT_CONFIGURED_MESSAGE = (
    "Composio not configured -- set COMPOSIO_API_KEY and connect an X account"
)


class PublishRequest(BaseModel):
    text: str
    channel: str = "x"
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


def _tweet_url_from_id(tweet_id: str | None) -> str | None:
    if not tweet_id:
        return None
    return f"https://twitter.com/i/web/status/{tweet_id}"


def _extract_tweet_result(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort pull of ``(tweet_id, tweet_url)`` out of Composio's
    ``{"data": {"data": {"id": ..., "text": ...}}}`` (X API v2) shape.
    Never raises -- an unexpected shape just yields ``(None, None)``, and
    the route still returns 201 with ``raw`` for the caller to inspect.
    """
    data = raw.get("data") if isinstance(raw, dict) else None
    inner = data.get("data") if isinstance(data, dict) else None
    tweet_id = inner.get("id") if isinstance(inner, dict) else None
    return tweet_id, _tweet_url_from_id(tweet_id)


def _trim_raw(raw: Any, *, max_len: int = 2000) -> dict[str, Any]:
    """Trim the provider response so it stays small in API responses/logs."""
    if not isinstance(raw, dict):
        return {"value": str(raw)[:max_len]}
    text = str(raw)
    if len(text) <= max_len:
        return raw
    return {
        "data": raw.get("data"),
        "error": raw.get("error"),
        "successful": raw.get("successful"),
        "_truncated": True,
    }


def _build_tweet_arguments(text: str, image_url: str | None) -> dict[str, Any]:
    """``TWITTER_CREATION_OF_A_POST`` takes ``media_media_ids`` (Media IDs
    from a prior X media upload), not an arbitrary image URL -- we have no
    upload pipeline here, so best-effort just append the link to the tweet
    text instead of failing the whole publish over unattached media.
    """
    if not image_url:
        return {"text": text}
    return {"text": f"{text}\n\n{image_url}"}


def _publish_to_x(brand_id: str, text: str, image_url: str | None) -> dict[str, Any]:
    """Call Composio to create a tweet. Raises on any failure -- the route
    turns that into HTTP 502, never 500."""
    from composio import Composio  # local import: only needed on this path

    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise RuntimeError(_COMPOSIO_NOT_CONFIGURED_MESSAGE)

    client = Composio(api_key=api_key)
    result = client.tools.execute(
        _TWITTER_CREATE_POST_TOOL,
        user_id=brand_id,
        arguments=_build_tweet_arguments(text, image_url),
    )
    return dict(result) if not isinstance(result, dict) else result


@router.post("/{brand_id}/publish", status_code=201, response_model=PublishResponse)
def publish(
    brand_id: str,
    body: PublishRequest,
    tenant_id: str = Depends(deps.require_tenant),
) -> PublishResponse:
    """Publish a generated post to an external channel (X/Twitter today).

    ``channel != "x"`` is rejected with 400 (not yet supported) rather than
    silently no-op-ing. The Composio call itself is wrapped so any failure
    (missing config, provider/network error, bad response) becomes an HTTP
    error response -- this route never 500s on a downstream publish
    failure.
    """
    from kaizen.api.main import brand_store, publish_store

    record = _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    if body.channel != "x":
        raise HTTPException(status_code=400, detail=f"unsupported channel: {body.channel!r}")

    if not os.environ.get("COMPOSIO_API_KEY"):
        raise HTTPException(status_code=400, detail=_COMPOSIO_NOT_CONFIGURED_MESSAGE)

    try:
        raw = _publish_to_x(record.brand_id, body.text, body.image_url)
    except Exception as exc:  # noqa: BLE001 - provider/network errors must never 500
        raise HTTPException(status_code=502, detail=f"Composio publish failed: {exc}") from exc

    tweet_id, tweet_url = _extract_tweet_result(raw)

    publish_store.record(
        brand_id=record.brand_id,
        channel="x",
        text=body.text,
        url=tweet_url,
        provider_id=tweet_id,
        status="posted",
    )

    return PublishResponse(
        ok=True,
        channel="x",
        url=tweet_url,
        id=tweet_id,
        raw=_trim_raw(raw),
    )


@router.get("/{brand_id}/posts/published", response_model=list[PublishedPostResponse])
def list_published_posts(
    brand_id: str,
    tenant_id: str = Depends(deps.require_tenant),
) -> list[PublishedPostResponse]:
    """Return the tenant's published posts for this brand -- the "track the
    post" view: most-recent first."""
    from kaizen.api.main import brand_store, publish_store

    _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    posts: list[PublishedPost] = publish_store.list_for_brand(brand_id)
    return [
        PublishedPostResponse(
            id=post.id,
            channel=post.channel,
            text=post.text,
            url=post.url,
            provider_id=post.provider_id,
            status=post.status,
            ts=post.ts,
        )
        for post in posts
    ]
