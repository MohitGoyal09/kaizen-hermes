"""In-memory published-post registry for the Kaizen control plane.

Records what ``routes_publish.py`` actually pushed to an external channel
(X/Twitter today) -- the control plane's own fast local "what did we publish
and where" record, analogous to ``content_store.py``'s role for generated
(not-yet-published) content. No Convex sync-back yet (out of NOW scope);
this is enough for the "track the post" view the frontend needs right after
publishing.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PublishedPost:
    id: str
    brand_id: str
    channel: str
    text: str
    url: str | None
    provider_id: str | None
    status: str
    ts: float = field(default_factory=time.time)


class PublishStore:
    """Process-wide in-memory registry of published posts, keyed by
    brand_id -- most-recent-first per brand, matching the "track the post"
    use case (a feed of what's gone out for this brand)."""

    def __init__(self) -> None:
        self._posts: dict[str, list[PublishedPost]] = {}

    def record(
        self,
        *,
        brand_id: str,
        channel: str,
        text: str,
        url: str | None,
        provider_id: str | None,
        status: str = "posted",
    ) -> PublishedPost:
        post = PublishedPost(
            id=uuid.uuid4().hex,
            brand_id=brand_id,
            channel=channel,
            text=text,
            url=url,
            provider_id=provider_id,
            status=status,
        )
        self._posts.setdefault(brand_id, []).append(post)
        return post

    def list_for_brand(self, brand_id: str) -> list[PublishedPost]:
        return list(reversed(self._posts.get(brand_id, [])))
