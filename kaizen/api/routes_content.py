"""``/v1/brands/{id}/content`` route: run the Content Creator persona
against a brand's already-onboarded brand DNA to turn a brief into on-brand
content.

Mirrors ``routes_brands.py``'s onboarding route almost exactly: same
``require_tenant`` auth boundary, same owned-brand 404/403 guard, same
job-store + ``submit_turn`` + threadpool + ``BackgroundTasks`` streaming
shape. The only real differences are (a) the persona
(``content_creator.md``) and user message (the brief, plus an explicit
"don't ask questions" instruction -- see the API-test finding where the
Brand Strategist stalled mid-run waiting on a human answer; the Content
Creator must never do that in automated mode), and (b) what happens after
the job completes: instead of parsing AGENTS.md, we read the
``content_latest.md`` the persona wrote and record it (in-memory
``ContentStore`` + best-effort Convex sync via
``convex_sync.sync_post``, matching the existing brand-profile sync-back
posture exactly -- see that module's docstring for why it's stubbed).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from kaizen.api import deps
from kaizen.api.brand_store import BrandRecord, BrandStore
from kaizen.api.content_store import ContentStore
from kaizen.api.convex_sync import sync_post
from kaizen.api.job_store import STREAM_DONE, Job, JobStore
from kaizen.toolsets_for import toolsets_for
from kaizen.worker_pool import submit_turn

router = APIRouter(prefix="/v1/brands", tags=["content"])

_PERSONAS_DIR = Path(__file__).resolve().parents[1] / "personas"
_CONTENT_CREATOR_PERSONA = _PERSONAS_DIR / "content_creator.md"
# The Content Creator drafts from brand DNA already written to
# AGENTS.md/SOUL.md during onboarding, not fresh research -- so it stays on
# the baseline web+file toolsets from kaizen.toolsets_for rather than
# preferring Linkup (see toolsets_for.py's _LINKUP_PREFERRING_ROLES
# docstring). Routed through the shared helper anyway so this stays in sync
# if that call changes later, and so both specialist routes share one
# source of truth for toolset selection.
_CONTENT_LATEST_FILENAME = "content_latest.md"
_DEFAULT_CHANNEL = "social_post"

_NO_QUESTIONS_INSTRUCTION = (
    "Do not ask me any questions and do not wait for a reply -- this is an "
    "automated run with no human available to answer. Use the brand DNA "
    "already in AGENTS.md/SOUL.md, make any judgment calls needed to fill "
    "gaps in the brief, and produce the content directly now."
)


class CreateContentRequest(BaseModel):
    brief: str
    format: str | None = None


class ContentJobResponse(BaseModel):
    job_id: str
    status: str


def _get_owned_brand_or_404_403(brand_store: BrandStore, brand_id: str, tenant_id: str) -> BrandRecord:
    record = brand_store.get(brand_id)
    if record is None:
        raise HTTPException(status_code=404, detail="brand not found")
    deps.guard_tenant_hint(record.tenant_id, tenant_id)
    return record


def _build_user_message(brief: str, format: str | None) -> str:
    format_line = f"\n\nRequested format: {format}" if format else ""
    return f"Content brief: {brief}{format_line}\n\n{_NO_QUESTIONS_INSTRUCTION}"


def _record_generated_content(
    content_store: ContentStore, record: BrandRecord, job: Job, request_body: CreateContentRequest
) -> None:
    """Read ``content_latest.md`` (if the persona wrote one) and record it
    in the in-memory ``ContentStore`` + best-effort sync to Convex.

    In ``KAIZEN_WORKER_DRYRUN`` mode the worker never actually invokes the
    persona (it just emits a synthetic step/final -- see
    ``kaizen/worker.py:_run_dryrun``), so the file legitimately won't exist
    yet. That must not fail an otherwise-successful job: recording is a
    downstream convenience, not the deliverable itself (the deliverable is
    the file, written directly by the persona via ``write_file``).
    """
    content_path = record.home / _CONTENT_LATEST_FILENAME
    if not content_path.exists():
        return

    body = content_path.read_text(encoding="utf-8")
    synced = sync_post(record.brand_id, _DEFAULT_CHANNEL, body)
    content_store.record(
        brand_id=record.brand_id,
        job_id=job.job_id,
        brief=request_body.brief,
        format=request_body.format,
        body=body,
        synced_to_convex=synced,
    )


def _run_content_job(
    job_store: JobStore,
    content_store: ContentStore,
    job: Job,
    record: BrandRecord,
    request_body: CreateContentRequest,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Runs in a worker thread (via run_in_threadpool). Same event-streaming
    shape as ``routes_brands._run_onboarding_job``: pushes each worker event
    onto the job's asyncio.Queue via ``call_soon_threadsafe`` (the only safe
    way to touch an asyncio.Queue from a non-event-loop thread)."""

    def on_event(event: dict) -> None:
        job_store.append_event(job, event)
        loop.call_soon_threadsafe(job.queue.put_nowait, event)

    try:
        job_store.mark_running(job)
        submit_turn(
            tenant_id=record.tenant_id,
            home=record.home,
            persona_path=_CONTENT_CREATOR_PERSONA,
            user_message=_build_user_message(request_body.brief, request_body.format),
            toolsets=toolsets_for("content_creator"),
            on_event=on_event,
        )

        _record_generated_content(content_store, record, job, request_body)

        job_store.mark_done(job, {"brand_id": record.brand_id})
        terminal = {"type": "job_complete", "data": {"status": "done", "brand_id": record.brand_id}}
        job_store.append_event(job, terminal)
        loop.call_soon_threadsafe(job.queue.put_nowait, terminal)
    except Exception as exc:  # noqa: BLE001 - job must always terminate, never hang the stream
        job_store.mark_failed(job, str(exc))
        terminal = {"type": "job_failed", "data": {"message": str(exc)}}
        job_store.append_event(job, terminal)
        loop.call_soon_threadsafe(job.queue.put_nowait, terminal)
    finally:
        loop.call_soon_threadsafe(job.queue.put_nowait, STREAM_DONE)


@router.post("/{brand_id}/content", status_code=202, response_model=ContentJobResponse)
async def create_content(
    brand_id: str,
    body: CreateContentRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(deps.require_tenant),
) -> ContentJobResponse:
    """Enqueue a content-generation job: runs the Content Creator persona
    via ``submit_turn`` in a threadpool, streaming events into the job's
    queue for ``GET /v1/jobs/{id}/stream`` (reused as-is -- no new job
    routes needed). On completion, reads back ``content_latest.md`` and
    records it via ``ContentStore`` + best-effort Convex sync.

    Same ``BackgroundTasks``-over-bare-``asyncio.create_task`` rationale as
    ``routes_brands.onboard_brand``: dispatched after the response is sent,
    on the same event loop/ASGI lifecycle, so it isn't orphaned by
    ``TestClient``'s per-request task group teardown.
    """
    from kaizen.api.main import brand_store, content_store, job_store

    record = _get_owned_brand_or_404_403(brand_store, brand_id, tenant_id)

    job = job_store.create(tenant_id=tenant_id, job_type="content", brand_id=brand_id)
    loop = asyncio.get_running_loop()

    background_tasks.add_task(
        run_in_threadpool, _run_content_job, job_store, content_store, job, record, body, loop
    )

    return ContentJobResponse(job_id=job.job_id, status=job.status)
