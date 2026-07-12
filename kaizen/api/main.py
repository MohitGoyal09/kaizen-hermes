"""Kaizen FastAPI control plane entrypoint.

Wires together the auth boundary (``deps.py``), the in-memory brand/job
registries, and the route modules (``routes_brands.py``,
``routes_jobs.py``). Run with:

    uvicorn kaizen.api.main:app --host $KAIZEN_API_HOST --port $KAIZEN_API_PORT

``brand_store``/``job_store`` are module-level singletons (one control
plane process for the foundation slice, per FOUNDATION_SLICE.md's
Wave-1/2 scope) -- route modules import them lazily (inside handler
functions) rather than at module import time, so tests can reload this
module with a fresh env (e.g. a different ``KAIZEN_PROFILES_DIR`` per test)
and get fresh stores without stale references lingering in already-imported
route modules.
"""

from __future__ import annotations

from fastapi import FastAPI

from kaizen.api.brand_store import BrandStore
from kaizen.api.campaign_store import CampaignStore
from kaizen.api.job_store import JobStore

brand_store = BrandStore()
campaign_store = CampaignStore()
job_store = JobStore()

app = FastAPI(title="Kaizen Control Plane", version="0.1.0")


def _register_routes(fastapi_app: FastAPI) -> None:
    # Imported here (not at module top) so `import kaizen.api.main` always
    # picks up whatever brand_store/job_store exist at call time -- matters
    # for tests that reload this module after changing env vars.
    from kaizen.api import routes_brands, routes_dashboard, routes_jobs

    fastapi_app.include_router(routes_brands.router)
    fastapi_app.include_router(routes_dashboard.router)
    fastapi_app.include_router(routes_jobs.router)


_register_routes(app)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
