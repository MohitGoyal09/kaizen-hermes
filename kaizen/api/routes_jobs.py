"""``/v1/jobs`` routes: job status + SSE event stream.

``GET /v1/jobs/{id}/stream`` powers the frontend's live run-tree
(FOUNDATION_SLICE.md section 6a): it tails the job's per-job asyncio.Queue
(fed by the onboarding job's ``on_event`` callback in
``routes_brands.py``), formatting each event as a ``text/event-stream``
``data:`` line, and terminates the stream after a ``final`` or ``error``
event (the two terminal event types the worker's JSON-lines protocol
defines -- see ``kaizen/worker.py``).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from kaizen.api import convex_client, deps
from kaizen.api.job_store import STREAM_DONE, Job, JobStore

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

_TERMINAL_EVENT_TYPES = ("final", "error")


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    type: str
    brand_id: str | None
    error: str | None
    id: str
    campaignId: str
    progress: int
    currentAgent: str
    startedAt: str
    completedAt: str | None = None
    costUsd: float
    durationSeconds: int


def _get_owned_job_or_404_403(job_store: JobStore, job_id: str, tenant_id: str) -> Job:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    deps.guard_tenant_hint(job.tenant_id, tenant_id)
    return job


def _iso_from_seconds(value: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(value, tz=_dt.UTC).isoformat()


def _progress_for_status(status: str) -> int:
    return {
        "queued": 0,
        "running": 50,
        "done": 100,
        "failed": 100,
    }.get(status, 0)


def _job_status_response(job: Job) -> JobStatusResponse:
    completed_at = _iso_from_seconds(job.updated_at) if job.status in {"done", "failed"} else None
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        type=job.type,
        brand_id=job.brand_id,
        error=job.error,
        id=job.job_id,
        campaignId=job.brand_id or "",
        progress=_progress_for_status(job.status),
        currentAgent="orchestrator",
        startedAt=_iso_from_seconds(job.created_at),
        completedAt=completed_at,
        costUsd=0,
        durationSeconds=max(0, int(job.updated_at - job.created_at)),
    )


def _job_doc_status_response(doc: dict) -> JobStatusResponse:
    job_id = str(doc.get("jobId") or doc.get("job_id") or doc.get("_id") or "")
    created_at_ms = doc.get("createdAt") or doc.get("_creationTime") or 0
    updated_at_ms = doc.get("updatedAt") or created_at_ms
    started_at = _iso_from_seconds(float(created_at_ms) / 1000) if created_at_ms else ""
    completed_at = (
        _iso_from_seconds(float(updated_at_ms) / 1000)
        if doc.get("status") in {"done", "failed"} and updated_at_ms
        else None
    )
    return JobStatusResponse(
        job_id=job_id,
        status=str(doc.get("status") or "queued"),
        type=str(doc.get("type") or "job"),
        brand_id=doc.get("brandId") or doc.get("brand_id"),
        error=doc.get("error"),
        id=job_id,
        campaignId=str(doc.get("campaignId") or doc.get("campaign_id") or doc.get("brandId") or ""),
        progress=_progress_for_status(str(doc.get("status") or "queued")),
        currentAgent="orchestrator",
        startedAt=started_at,
        completedAt=completed_at,
        costUsd=0,
        durationSeconds=max(0, int((float(updated_at_ms or 0) - float(created_at_ms or 0)) / 1000)),
    )


@router.get("", response_model=list[JobStatusResponse])
def list_jobs(
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> list[JobStatusResponse]:
    from kaizen.api.main import job_store

    if convex_client.is_convex_configured():
        try:
            return [
                _job_doc_status_response(job)
                for job in convex_client.list_jobs(bearer_token=bearer_token)
                if isinstance(job, dict)
            ]
        except convex_client.ConvexAPIError:
            pass

    return [_job_status_response(job) for job in job_store.list_for_tenant(tenant_id)]


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(
    job_id: str,
    bearer_token: str = Depends(deps.require_bearer_token),
    tenant_id: str = Depends(deps.require_tenant),
) -> JobStatusResponse:
    from kaizen.api.main import job_store

    job = job_store.get(job_id)
    if job is not None:
        deps.guard_tenant_hint(job.tenant_id, tenant_id)
        return _job_status_response(job)

    if convex_client.is_convex_configured():
        try:
            convex_job = convex_client.get_job(job_id, bearer_token=bearer_token)
            if isinstance(convex_job, dict):
                return _job_doc_status_response(convex_job)
        except convex_client.ConvexAPIError:
            pass

    raise HTTPException(status_code=404, detail="job not found")


async def _sse_event_generator(job: Job) -> AsyncIterator[str]:
    # Replay any events recorded before the stream connected (e.g. the
    # client reconnects, or the job started before /stream was requested),
    # then tail live events off the queue until a terminal event or the
    # STREAM_DONE sentinel.
    for event in list(job.events):
        yield f"data: {json.dumps(event)}\n\n"
        if event.get("type") in _TERMINAL_EVENT_TYPES:
            return

    while True:
        event = await job.queue.get()
        if event is STREAM_DONE:
            return
        yield f"data: {json.dumps(event)}\n\n"
        if event.get("type") in _TERMINAL_EVENT_TYPES:
            return


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, tenant_id: str = Depends(deps.require_tenant)) -> StreamingResponse:
    from kaizen.api.main import job_store

    job = _get_owned_job_or_404_403(job_store, job_id, tenant_id)
    return StreamingResponse(_sse_event_generator(job), media_type="text/event-stream")
