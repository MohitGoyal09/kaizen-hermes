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

from kaizen.api import deps
from kaizen.api.job_store import STREAM_DONE, Job, JobStore

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

_TERMINAL_EVENT_TYPES = ("final", "error")


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    type: str
    brand_id: str | None
    error: str | None


def _get_owned_job_or_404_403(job_store: JobStore, job_id: str, tenant_id: str) -> Job:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    deps.guard_tenant_hint(job.tenant_id, tenant_id)
    return job


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, tenant_id: str = Depends(deps.require_tenant)) -> JobStatusResponse:
    from kaizen.api.main import job_store

    job = _get_owned_job_or_404_403(job_store, job_id, tenant_id)
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        type=job.type,
        brand_id=job.brand_id,
        error=job.error,
    )


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
