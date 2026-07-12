"""Phase 0 — the isolation spike. THE GATE.

Proves the multi-tenancy wall before anything is built on it: two Hermes
tenants, each launched as its own process with ``HERMES_HOME`` set in the
environment, write to their own ``state.db`` with **zero cross-tenant bleed**.

Why subprocesses and not an in-process ContextVar override? Because
``hermes_state.DEFAULT_DB_PATH`` is computed at *import time* from
``get_hermes_home()`` (``hermes_state.py:123``), and ``SessionDB()`` defaults to
it (``:928``). A ContextVar override set after import cannot move an
already-frozen path. Setting ``HERMES_HOME`` before the process imports Hermes
makes every path resolve to the tenant's dir by construction. This is Hermes'
own documented intent ("subprocess spawner should pass HERMES_HOME explicitly").

See: kaizen/SPEC.md §8, kaizen/CODE_GROUNDED_PLAN.md ("Multi-tenancy verdict").

Nothing downstream (tenancy.py, worker.py, the agents) may be trusted until
this file is green.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_MODULE = "kaizen.tests._tenant_probe"


def _run_probe(hermes_home: Path, marker: str) -> dict:
    """Launch the tenant probe as its own process with HERMES_HOME set.

    Mirrors the production isolation mechanism exactly: env-before-import.
    Returns the probe's parsed JSON report.
    """
    proc = subprocess.run(
        [sys.executable, "-m", PROBE_MODULE, marker],
        cwd=REPO_ROOT,
        env={"HERMES_HOME": str(hermes_home), "PATH": _path_env()},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"probe for {marker!r} failed (rc={proc.returncode}):\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    # The probe prints exactly one JSON line last; tolerate leading log noise.
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def _path_env() -> str:
    import os

    return os.environ.get("PATH", "")


def _markers_in_db(db_path: Path) -> set[str]:
    """Read every message marker out of a tenant's state.db (read-only)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT content FROM messages WHERE content LIKE 'marker::%'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0].split("::", 1)[1] for r in rows}


def test_process_per_tenant_isolation(tmp_path: pytest.TempPathFactory) -> None:
    """Two tenants run concurrently; each state.db holds only its own data."""
    home_a = tmp_path / "A"
    home_b = tmp_path / "B"

    # Run BOTH tenants concurrently — the demo claim is "two brands at the
    # same time". If tenancy bled under concurrency, this is where it shows.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(_run_probe, home_a, "alpha")
        fut_b = pool.submit(_run_probe, home_b, "bravo")
        report_a = fut_a.result()
        report_b = fut_b.result()

    # Each tenant's DB resolved under its own HERMES_HOME.
    db_a = Path(report_a["db_path"])
    db_b = Path(report_b["db_path"])
    assert db_a == home_a / "state.db"
    assert db_b == home_b / "state.db"
    assert db_a.exists() and db_b.exists()
    assert db_a != db_b

    # The wall: A contains only alpha, B contains only bravo. No shared rows.
    markers_a = _markers_in_db(db_a)
    markers_b = _markers_in_db(db_b)
    assert markers_a == {"alpha"}, f"tenant A leaked/missing data: {markers_a}"
    assert markers_b == {"bravo"}, f"tenant B leaked/missing data: {markers_b}"


def test_reader_scoped_to_a_cannot_see_b(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Negative test: a reader pointed at tenant A never sees tenant B's rows."""
    home_a = tmp_path / "A"
    home_b = tmp_path / "B"
    _run_probe(home_a, "alpha")
    _run_probe(home_b, "bravo")

    db_a = home_a / "state.db"
    conn = sqlite3.connect(f"file:{db_a}?mode=ro", uri=True)
    try:
        (bravo_count,) = conn.execute(
            "SELECT count(*) FROM messages WHERE content LIKE '%bravo%'"
        ).fetchone()
    finally:
        conn.close()
    assert bravo_count == 0, "tenant A's store must not contain tenant B data"


def test_inprocess_override_does_not_relocate_state_db(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Documents WHY we use process-per-tenant, not an in-process override.

    Once ``hermes_state`` is imported, ``DEFAULT_DB_PATH`` is frozen. Setting a
    ContextVar override afterward must NOT change where ``SessionDB()`` writes —
    that is precisely the hazard that makes the override an unsafe wall.
    """
    import hermes_state
    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    frozen_default = hermes_state.DEFAULT_DB_PATH

    token = set_hermes_home_override(str(tmp_path / "override_target"))
    try:
        # The override changes get_hermes_home() for call-time resolvers...
        from hermes_constants import get_hermes_home

        assert get_hermes_home() == tmp_path / "override_target"
        # ...but the import-frozen state.db path is unmoved, and SessionDB()
        # still defaults to it. The override is NOT the isolation wall.
        assert hermes_state.DEFAULT_DB_PATH == frozen_default
        db = hermes_state.SessionDB()
        try:
            assert db.db_path == frozen_default
        finally:
            db.close()
    finally:
        reset_hermes_home_override(token)
