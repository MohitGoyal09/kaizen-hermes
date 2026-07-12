"""Kaizen FastAPI control plane entrypoint.

Wires together the auth boundary (``deps.py``), the in-memory registries,
and the route modules. Run with:

    uvicorn kaizen.api.main:app --host $KAIZEN_API_HOST --port $KAIZEN_API_PORT

Route modules import the stores lazily from this module inside handlers, so
tests can reload this module with fresh environment variables and fresh
stores without stale route references.
"""

from __future__ import annotations

from fastapi import FastAPI

from kaizen.api.brand_store import BrandStore
from kaizen.api.campaign_store import CampaignStore
from kaizen.api.content_store import ContentStore
from kaizen.api.job_store import JobStore

brand_store = BrandStore()
campaign_store = CampaignStore()
content_store = ContentStore()
job_store = JobStore()

app = FastAPI(title="Kaizen Control Plane", version="0.1.0")


def _register_routes(fastapi_app: FastAPI) -> None:
    from kaizen.api import routes_brands, routes_content, routes_dashboard, routes_jobs

    fastapi_app.include_router(routes_brands.router)
    fastapi_app.include_router(routes_content.router)
    fastapi_app.include_router(routes_dashboard.router)
    fastapi_app.include_router(routes_jobs.router)


_register_routes(app)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
