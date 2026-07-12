"""In-process fallback store for campaigns created through the FastAPI API.

Convex is the durable store when configured. This registry exists only so
local/dev deployments without Convex can still round-trip campaigns created
through ``POST /v1/campaigns`` in the current process. It does not seed demo
data and it does not claim durability across restarts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

CampaignStatus = Literal["draft", "active", "completed", "archived"]


@dataclass
class CampaignRecord:
    campaign_id: str
    tenant_id: str
    brand_id: str
    name: str
    goal: str | None = None
    channels: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    status: CampaignStatus = "draft"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CampaignStore:
    """Process-wide tenant-scoped campaign fallback registry."""

    def __init__(self) -> None:
        self._campaigns: dict[str, CampaignRecord] = {}

    def create(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        name: str,
        goal: str | None = None,
        channels: list[str] | None = None,
        formats: list[str] | None = None,
        status: CampaignStatus = "draft",
    ) -> CampaignRecord:
        campaign_id = uuid.uuid4().hex
        record = CampaignRecord(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=name,
            goal=goal,
            channels=channels or [],
            formats=formats or [],
            status=status,
        )
        self._campaigns[campaign_id] = record
        return record

    def get(self, campaign_id: str) -> CampaignRecord | None:
        return self._campaigns.get(campaign_id)

    def list_for_tenant(self, tenant_id: str) -> list[CampaignRecord]:
        return [
            campaign
            for campaign in self._campaigns.values()
            if campaign.tenant_id == tenant_id
        ]
