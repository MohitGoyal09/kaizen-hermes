"""Convex sync-back: reconcile file-authoritative brand DNA into Convex.

FOUNDATION_SLICE.md section 3: "After a run: the backend reconciles file ->
Convex (read the file, upsert brandProfile)". This module is that
reconciliation call -- ``sync_brand_profile`` reads the AGENTS.md that the
Brand Strategist wrote (via ``parse_agents``) and calls Convex's
``upsertBrandProfile`` mutation (``convex/profile.ts``) over Convex's HTTP
API.

STUBBED for the foundation slice: there is no live Convex deployment in
this environment (no ``npx convex dev`` login available -- see
``convex/README.md``), and per SPEC.md R7 the FastAPI service call to Convex
must itself carry a Convex-verifiable identity on behalf of the tenant
(a service-auth concern the hackathon scope defers). ``sync_brand_profile``
therefore performs a best-effort HTTP call when ``CONVEX_URL`` is
configured, and swallows (logs, does not raise) any failure -- reconciling
to Convex must never fail an onboarding job that already succeeded
locally (the file write already happened; Convex is a downstream durability
step, not the source of truth mid-run).

When wiring this for real: Convex's client HTTP API expects a POST to
``{CONVEX_URL}/api/mutation`` with ``{"path": "profile:upsertBrandProfile",
"args": {...}, "format": "json"}`` and an ``Authorization: Bearer <token>``
identifying the tenant to ``ctx.auth.getUserIdentity()`` server-side.
"""

from __future__ import annotations

import logging
from kaizen.api import convex_client
from kaizen.profile import BrandProfile

logger = logging.getLogger("kaizen.api.convex_sync")

def sync_brand_profile(brand_id: str, profile: BrandProfile, *, bearer_token: str | None = None) -> bool:
    """Best-effort reconciliation of ``profile`` into Convex's
    ``brandProfile`` table via ``upsertBrandProfile``.

    Returns True if the sync call was attempted and succeeded, False
    otherwise (including the no-op case where ``CONVEX_URL`` isn't
    configured, e.g. in tests). Never raises -- a Convex outage or missing
    config must not fail the onboarding job whose real deliverable (the
    written AGENTS.md) already succeeded.
    """
    if not convex_client.is_convex_configured():
        logger.info("CONVEX_URL not configured; skipping brand profile sync-back for %s", brand_id)
        return False

    try:
        convex_client.upsert_brand_profile(brand_id, profile, bearer_token=bearer_token or "")
        return True
    except convex_client.ConvexAPIError as exc:
        logger.warning("Convex brand profile sync-back failed for %s: %s", brand_id, exc)
        return False
