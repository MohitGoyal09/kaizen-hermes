"""``/v1/brands`` routes: create a brand (provision its tenant home) and
kick off the onboarding job that runs the Brand Strategist persona.

Tenancy: ``tenant_id`` always comes from ``deps.require_tenant`` (the
validated JWT), never from the request body/path. ``GET /v1/brands/{id}``
and ``POST /v1/brands/{id}/onboard`` use ``deps.guard_tenant_hint`` to turn
a brand owned by a different tenant into a 403 rather than leaking its
existence via a 404-vs-403 timing/shape difference on ownership vs.
not-found -- concretely: unknown id -> 404, id exists but wrong tenant ->
403 (matches SPEC.md R7 examples and the acceptance tests).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from kaizen.api import convex_client
from kaizen.api import deps
from kaizen.api.brand_store import BrandStore, new_brand_id
from kaizen.api.convex_sync import sync_brand_profile
from kaizen.api.job_store import STREAM_DONE, JobStore
from kaizen.profile import BrandProfile, parse_agents
from kaizen.tenancy import provision_tenant
from kaizen.worker_pool import submit_turn

router = APIRouter(prefix="/v1/brands", tags=["brands"])

_PERSONAS_DIR = Path(__file__).resolve().parents[1] / "personas"
_BRAND_STRATEGIST_PERSONA = _PERSONAS_DIR / "brand_strategist.md"
_ONBOARDING_TOOLSETS = ["web", "file"]


class CreateBrandRequest(BaseModel):
    url: str


class CreateBrandResponse(BaseModel):
    brand_id: str
    home: str
    status: str


class BrandResponse(BaseModel):
    brand_id: str
    tenant_id: str
    url: str
    home: str
    status: str


class OnboardResponse(BaseModel):
    job_id: str
    status: str


def _skeleton_profile(brand_id: str, url: str) -> BrandProfile:
    """A minimal BrandProfile to provision with, before the Brand Strategist
    fills in real positioning/voice/audience during onboarding."""
    return BrandProfile(
        brand_id=brand_id,
        name=url,
        url=url,
        positioning="(not yet researched)",
        voice_tone="(not yet researched)",
        audience="(not yet researched)",
    )


def _get_owned_brand_or_404_403(brand_store: BrandStore, brand_id: str, tenant_id: str):
    record = brand_store.get(brand_id)
    if record is None:
        raise HTTPException(status_code=404, detail="brand not found")
    deps.guard_tenant_hint(record.tenant_id, tenant_id)
    return record


@router.post("", status_code=201, response_model=CreateBrandResponse)
def create_brand(
    body: CreateBrandRequest,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> CreateBrandResponse:
    """Provision a new brand for the authenticated tenant.

    Derives a fresh server-generated ``brand_id`` (never client-supplied),
    provisions its HERMES_HOME via ``provision_tenant`` under
    ``KAIZEN_PROFILES_DIR``, and registers a skeleton BrandProfile. Real
    brand DNA (positioning/voice/audience/etc.) is filled in by the
    onboarding job, not at creation time.
    """
    from kaizen.api.main import brand_store  # local import: avoids a cycle with main.py

    try:
        brand_id = (
            convex_client.create_brand(body.url, bearer_token=bearer_token)
            if convex_client.is_convex_configured()
            else new_brand_id()
        )
    except convex_client.ConvexAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    profile = _skeleton_profile(brand_id, body.url)
    home = provision_tenant(brand_id, profile, base_dir=deps.KAIZEN_PROFILES_DIR)

    record = brand_store.create(tenant_id=tenant_id, url=body.url, home=home, profile=profile)

    if convex_client.is_convex_configured():
        try:
            convex_client.update_brand_status(
                record.brand_id, "provisioned", bearer_token=bearer_token
            )
        except convex_client.ConvexAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CreateBrandResponse(brand_id=record.brand_id, home=str(record.home), status=record.status)


@router.get("/{brand_id}", response_model=BrandResponse)
def get_brand(brand_id: str, tenant_id: str = Depends(deps.require_tenant)) -> BrandResponse:
    from kaizen.api.main import brand_store

    record = _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)
    return BrandResponse(
        brand_id=record.brand_id,
        tenant_id=record.tenant_id,
        url=record.url,
        home=str(record.home),
        status=record.status,
    )


def _update_convex_job_failure(job_id: str, error: str, bearer_token: str) -> None:
    if not convex_client.is_convex_configured():
        return
    try:
        convex_client.update_job_status(job_id, "failed", error=error, bearer_token=bearer_token)
    except convex_client.ConvexAPIError:
        pass


def _run_onboarding_job(
    job_store: JobStore,
    brand_store: BrandStore,
    job,
    record,
    loop: asyncio.AbstractEventLoop,
    bearer_token: str,
) -> None:
    """Runs in a worker thread (via run_in_threadpool). Streams worker
    events into the job's asyncio.Queue via ``call_soon_threadsafe`` (the
    only safe way to touch an asyncio.Queue from a non-event-loop thread),
    then reconciles the resulting AGENTS.md back into Convex.
    """

    def on_event(event: dict) -> None:
        job_store.append_event(job, event)
        loop.call_soon_threadsafe(job.queue.put_nowait, event)

    try:
        job_store.mark_running(job)
        if convex_client.is_convex_configured():
            convex_client.update_brand_status(
                record.brand_id, "onboarding", bearer_token=bearer_token
            )
            convex_client.update_job_status(job.job_id, "running", bearer_token=bearer_token)

        submit_turn(
            tenant_id=record.tenant_id,
            home=record.home,
            persona_path=_BRAND_STRATEGIST_PERSONA,
            user_message=(
                f"Onboard the brand at {record.url}. This is an unattended backend job: "
                "do not ask follow-up questions or wait for confirmation. Research the "
                "site with your web tools; infer positioning, voice/tone, audience, do's, "
                "don'ts, guardrails and channels (use clearly labeled reasonable defaults "
                "if research is unavailable). Then read AGENTS.md, replace the Kaizen "
                "brand-DNA block with a complete first-pass profile, and call write_file "
                "before your final response."
            ),
            toolsets=_ONBOARDING_TOOLSETS,
            on_event=on_event,
        )

        agents_md_path = record.home / "AGENTS.md"
        updated_profile = parse_agents(agents_md_path.read_text(encoding="utf-8"))
        brand_store.update_profile(record.brand_id, updated_profile)
        brand_store.update_status(record.brand_id, "active")
        synced = sync_brand_profile(record.brand_id, updated_profile, bearer_token=bearer_token)
        if convex_client.is_convex_configured() and not synced:
            raise RuntimeError("Convex brand profile sync-back failed")

        result = {"brand_id": record.brand_id}
        job_store.mark_done(job, result)
        if convex_client.is_convex_configured():
            convex_client.update_brand_status(record.brand_id, "active", bearer_token=bearer_token)
            convex_client.update_job_status(
                job.job_id, "done", result=result, bearer_token=bearer_token
            )
        terminal = {"type": "job_complete", "data": {"status": "done", "brand_id": record.brand_id}}
        job_store.append_event(job, terminal)
        loop.call_soon_threadsafe(job.queue.put_nowait, terminal)
    except Exception as exc:  # noqa: BLE001 - job must always terminate, never hang the stream
        job_store.mark_failed(job, str(exc))
        _update_convex_job_failure(job.job_id, str(exc), bearer_token)
        terminal = {"type": "job_failed", "data": {"message": str(exc)}}
        job_store.append_event(job, terminal)
        loop.call_soon_threadsafe(job.queue.put_nowait, terminal)
    finally:
        loop.call_soon_threadsafe(job.queue.put_nowait, STREAM_DONE)


@router.post("/{brand_id}/onboard", status_code=202, response_model=OnboardResponse)
async def onboard_brand(
    brand_id: str,
    background_tasks: BackgroundTasks,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> OnboardResponse:
    """Enqueue an onboarding job: runs the Brand Strategist persona via
    ``submit_turn`` in a threadpool (so it doesn't block the event loop),
    streaming events into the job's queue for ``GET
    /v1/jobs/{id}/stream``. On completion, parses the resulting AGENTS.md
    and syncs it back to Convex (``convex_sync.sync_brand_profile``).

    Dispatched via Starlette's ``BackgroundTasks`` (runs after the response
    is sent, on the same event loop/ASGI lifecycle) rather than a bare
    ``asyncio.create_task`` -- the latter can be orphaned/cancelled once the
    request-handling task group exits, which is exactly the scenario
    FastAPI's ``TestClient`` exercises per-request.
    """
    from kaizen.api.main import brand_store, job_store

    record = _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    job = job_store.create(tenant_id=tenant_id, job_type="onboarding", brand_id=brand_id)
    if convex_client.is_convex_configured():
        try:
            convex_client.create_job(job.job_id, brand_id, bearer_token=bearer_token)
        except convex_client.ConvexAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    loop = asyncio.get_running_loop()

    background_tasks.add_task(
        run_in_threadpool, _run_onboarding_job, job_store, brand_store, job, record, loop, bearer_token
    )

    return OnboardResponse(job_id=job.job_id, status=job.status)
