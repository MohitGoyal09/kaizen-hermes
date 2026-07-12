"""In-memory job model + per-job event queue for the Kaizen control plane.

Job shape (SPEC.md section 5 / FOUNDATION_SLICE.md section 6a):
    {job_id, tenant_id, type, status: queued|running|done|failed, events: [...]}

Each job also owns an ``asyncio.Queue`` that ``routes_jobs.py``'s SSE
endpoint drains: ``worker_pool.submit_turn``'s ``on_event`` callback (called
from a worker thread via ``run_in_threadpool``) pushes each event onto the
queue with ``loop.call_soon_threadsafe`` (see ``routes_brands.py``), and the
stream endpoint awaits items off of it. A sentinel (``None``) marks stream
completion so the SSE generator knows when to stop without polling.

In-memory only, per FOUNDATION_SLICE.md's Wave-1/2 scope (JSON-lines over
stdout, not Redis pub-sub yet) -- this is not durable across a process
restart, matching the "events[]" job model as specced, not a queueing
system. Convex's ``jobs`` table (createJob/updateJobStatus) is the durable
record; this in-memory store is just what powers the live SSE stream.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed"]

# Sentinel pushed onto a job's event queue to signal "no more events".
STREAM_DONE = None


@dataclass
class Job:
    job_id: str
    tenant_id: str
    type: str
    status: JobStatus = "queued"
    brand_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    queue: "asyncio.Queue[dict[str, Any] | None]" = field(default_factory=asyncio.Queue)


class JobStore:
    """Process-wide in-memory job registry.

    A single instance is created at app start (``main.py``) and shared by
    ``routes_brands.py`` (creates + runs jobs) and ``routes_jobs.py`` (reads
    status, streams events). Not process-safe (fine: the control plane runs
    as one process for the foundation slice).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, *, tenant_id: str, job_type: str, brand_id: str | None = None) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, tenant_id=tenant_id, type=job_type, brand_id=brand_id)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_for_tenant(self, tenant_id: str) -> list[Job]:
        return [job for job in self._jobs.values() if job.tenant_id == tenant_id]

    def append_event(self, job: Job, event: dict[str, Any]) -> None:
        """Record ``event`` on the job and enqueue it for any active SSE
        stream. Safe to call from a worker thread (only mutates a plain
        list/dict; the asyncio.Queue put is scheduled onto the loop by the
        caller when called from a non-event-loop thread -- see
        routes_brands.py's on_event wiring)."""
        job.events.append(event)

    def mark_running(self, job: Job) -> None:
        job.status = "running"
        job.updated_at = now_ts()

    def mark_done(self, job: Job, result: dict[str, Any]) -> None:
        job.status = "done"
        job.result = result
        job.updated_at = now_ts()

    def mark_failed(self, job: Job, error: str) -> None:
        job.status = "failed"
        job.error = error
        job.updated_at = now_ts()


def now_ts() -> float:
    return time.time()
