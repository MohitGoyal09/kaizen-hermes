"""In-memory brand registry for the Kaizen control plane.

FastAPI's own record of "which brand_id belongs to which tenant" and "where
is its HERMES_HOME on disk" -- Convex is the system of record for the
*brand profile data* (FOUNDATION_SLICE.md section 1), but the control plane
still needs a fast local lookup to (a) enforce the tenant-hint guard on
``GET /v1/brands/{id}`` without a round trip, and (b) know which
``home`` path + ``BrandProfile`` to hand ``worker_pool.submit_turn`` for a
given brand_id. This is a cache/router, not a source of truth: Convex
sync-back (``upsertBrandProfile``) is what makes brand DNA durable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from kaizen.profile import BrandProfile


@dataclass
class BrandRecord:
    brand_id: str
    tenant_id: str
    url: str
    home: Path
    profile: BrandProfile
    status: str = "provisioned"


class BrandStore:
    """Process-wide in-memory brand registry, keyed by brand_id."""

    def __init__(self) -> None:
        self._brands: dict[str, BrandRecord] = {}

    def create(self, *, tenant_id: str, url: str, home: Path, profile: BrandProfile) -> BrandRecord:
        brand_id = profile.brand_id
        record = BrandRecord(
            brand_id=brand_id,
            tenant_id=tenant_id,
            url=url,
            home=home,
            profile=profile,
        )
        self._brands[brand_id] = record
        return record

    def get(self, brand_id: str) -> BrandRecord | None:
        return self._brands.get(brand_id)

    def update_profile(self, brand_id: str, profile: BrandProfile) -> None:
        record = self._brands.get(brand_id)
        if record is not None:
            record.profile = profile

    def update_status(self, brand_id: str, status: str) -> None:
        record = self._brands.get(brand_id)
        if record is not None:
            record.status = status


def new_brand_id() -> str:
    """Generate a fresh, filesystem-safe brand_id slug.

    Uses a uuid4 hex, which already satisfies tenancy.py's
    ``_SAFE_BRAND_ID_RE`` (alphanumeric only).
    """
    return uuid.uuid4().hex
