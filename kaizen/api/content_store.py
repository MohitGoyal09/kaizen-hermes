"""In-memory content registry for the Kaizen control plane.

Records what the Content Creator persona produced for a brand -- the
control plane's own fast local record of "what did we last generate for
this brand and which job produced it", analogous to ``brand_store.py``'s
role for brand records. Convex's ``posts`` table (``convex/posts.ts``) is
the durable downstream record once ``convex_sync.sync_post`` reconciles it
(best-effort, matching the existing ``sync_brand_profile`` posture); this
in-memory store is what the control plane itself can read back without a
network round trip, and what tests assert against without a live Convex
deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentRecord:
    brand_id: str
    job_id: str
    brief: str
    format: str | None
    body: str
    channel: str = "linkedin"
    synced_to_convex: bool = False


class ContentStore:
    """Process-wide in-memory registry of generated content, keyed by
    brand_id (most-recent-wins, one record per brand -- matches
    ``content_latest.md``'s "latest" semantics)."""

    def __init__(self) -> None:
        self._content: dict[str, ContentRecord] = {}

    def record(
        self,
        *,
        brand_id: str,
        job_id: str,
        brief: str,
        format: str | None,
        body: str,
        channel: str = "linkedin",
        synced_to_convex: bool = False,
    ) -> ContentRecord:
        record = ContentRecord(
            brand_id=brand_id,
            job_id=job_id,
            brief=brief,
            format=format,
            body=body,
            channel=channel,
            synced_to_convex=synced_to_convex,
        )
        self._content[brand_id] = record
        return record

    def get(self, brand_id: str) -> ContentRecord | None:
        return self._content.get(brand_id)
