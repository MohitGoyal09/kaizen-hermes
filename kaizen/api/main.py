"""Kaizen FastAPI control plane entrypoint.

Wires together the auth boundary (``deps.py``), the in-memory registries,
and the route modules. Run with:

    uvicorn kaizen.api.main:app --host $KAIZEN_API_HOST --port $KAIZEN_API_PORT

Route modules import the stores lazily from this module inside handlers, so
tests can reload this module with fresh environment variables and fresh
stores without stale route references.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kaizen.api.brand_store import BrandStore
from kaizen.api.campaign_store import CampaignStore
from kaizen.api.content_store import ContentStore
from kaizen.api.job_store import JobStore
from kaizen.api.publish_store import PublishStore

brand_store = BrandStore()
campaign_store = CampaignStore()
content_store = ContentStore()
job_store = JobStore()
publish_store = PublishStore()

app = FastAPI(title="Kaizen Control Plane", version="0.1.0")

# CORS: the frontend (a separate Next.js app / origin) calls this API from the
# browser, so cross-origin requests must be allowed. Origins are configurable
# via KAIZEN_CORS_ORIGINS (comma-separated); defaults cover local dev + the
# deployed frontend. Auth is via the Authorization: Bearer header (not cookies).
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3001,http://127.0.0.1:3001,"
    "https://kaizenn.xyz,https://www.kaizenn.xyz"
)
_cors_origins = [
    o.strip()
    for o in os.environ.get("KAIZEN_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _register_routes(fastapi_app: FastAPI) -> None:
    from kaizen.api import (
        routes_brands,
        routes_content,
        routes_dashboard,
        routes_jobs,
        routes_publish,
    )

    fastapi_app.include_router(routes_brands.router)
    fastapi_app.include_router(routes_content.router)
    fastapi_app.include_router(routes_dashboard.router)
    fastapi_app.include_router(routes_jobs.router)
    fastapi_app.include_router(routes_publish.router)


_register_routes(app)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
