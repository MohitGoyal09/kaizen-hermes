"""Spawn a per-tenant Hermes worker subprocess for one conversation turn.

``submit_turn`` is the FastAPI-facing entry point for running a turn: it
launches ``python -m kaizen.worker`` as a fresh subprocess with
``HERMES_HOME`` set in that subprocess's environment *before* Python starts
(so Hermes' import-time-frozen paths — state.db, the Honcho client
singleton — resolve under the tenant's home; see
CODE_GROUNDED_PLAN.md "Multi-tenancy verdict" and
``kaizen/tests/test_isolation.py``), streams the worker's JSON-lines stdout
back through ``on_event`` as each line arrives, and returns the ``final``
event's data once the subprocess exits.

Fresh process per turn (no pooling/reuse/idle-eviction yet) — the docstring
in FOUNDATION_SLICE.md section 7 calls this out as good enough for Wave 1;
pooling is a later optimization, not a correctness requirement.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Repo root: kaizen/worker_pool.py -> kaizen/ -> repo root. The worker is
# launched with cwd=HERMES_HOME (required so AGENTS.md resolves from the
# tenant's home, not the repo), so "python -m kaizen.worker" can only find
# the kaizen package if the repo root is on the child's PYTHONPATH too.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def submit_turn(
    tenant_id: str,
    home: Path,
    persona_path: Path,
    user_message: str,
    toolsets: list[str],
    on_event: Callable[[dict], None],
) -> dict:
    """Run one conversation turn for ``tenant_id`` in a fresh worker process.

    Launches ``python -m kaizen.worker`` with ``HERMES_HOME=str(home)`` in
    its env and ``cwd=str(home)`` — both required for the isolation wall
    (env-before-import) and for AGENTS.md to be read from the right
    directory. Streams each JSON-lines event from the worker's stdout to
    ``on_event`` as it's produced, and returns the ``data`` payload of the
    worker's terminal ``final`` event.

    ``KAIZEN_WORKER_DRYRUN`` in *this* process's environment is forwarded
    to the child so tests can exercise the whole path without an LLM call.

    Raises ``RuntimeError`` if the worker exits without ever emitting a
    ``final`` event (e.g. it crashed before reaching one, or only emitted
    ``error``).
    """
    home = Path(home)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = (
        f"{_REPO_ROOT}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(_REPO_ROOT)
    )
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": pythonpath}

    job_spec = json.dumps(
        {
            "persona_path": str(persona_path),
            "user_message": user_message,
            "toolsets": toolsets,
        }
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "kaizen.worker", job_spec],
        env=env,
        cwd=str(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    final_data: dict | None = None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        # Hermes internals print several plain-text diagnostics straight to
        # stdout that are NOT gated by quiet_mode -- most notably the Nous
        # provider's 401-auth-failure retry/diagnostic prints in
        # agent/conversation_loop.py (~2765-2788), which fire in exactly the
        # "credentials missing/invalid" scenario this worker must degrade
        # from, not crash on. A stray non-JSON line here must be skipped,
        # not allowed to blow up the parent with an unrelated
        # JSONDecodeError -- worker.py's own try/except already guarantees a
        # terminating "error"/"final" JSON event either way.
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        on_event(event)
        if event.get("type") == "final":
            final_data = event.get("data")

    proc.wait()

    if final_data is None:
        stderr_output = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(
            f"worker for tenant {tenant_id!r} exited (rc={proc.returncode}) "
            f"without emitting a final event. stderr:\n{stderr_output}"
        )

    return final_data
