"""Tests for kaizen.worker_pool.submit_turn in KAIZEN_WORKER_DRYRUN mode.

The worker (kaizen/worker.py, run via ``python -m kaizen.worker``) is a
subprocess launched with ``HERMES_HOME`` set in its env *before* Python
starts and Hermes is imported -- the same env-before-import isolation wall
proven in test_isolation.py. In dryrun mode (KAIZEN_WORKER_DRYRUN=1) the
worker emits a synthetic ``step`` then ``final`` event WITHOUT touching the
LLM, so this test can run with no API key and no network. It exists to prove
the wiring end-to-end: worker_pool spawns the right subprocess with the
right env/cwd, streams JSON-lines events back through on_event, and the
final event's data proves the subprocess actually saw HERMES_HOME and ran
with cwd == that same tenant home (the AGENTS.md-must-be-read-from-cwd
requirement in FOUNDATION_SLICE.md section 3).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kaizen.worker_pool import submit_turn


@pytest.fixture
def tenant_home(tmp_path: Path) -> Path:
    home = tmp_path / "tenant-a"
    home.mkdir()
    (home / "SOUL.md").write_text("# Test Soul\n", encoding="utf-8")
    return home


@pytest.fixture
def persona_path(tmp_path: Path) -> Path:
    path = tmp_path / "persona.md"
    path.write_text("You are a test persona.\n", encoding="utf-8")
    return path


def test_submit_turn_streams_step_then_final_event(
    tenant_home: Path, persona_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    events: list[dict] = []

    submit_turn(
        tenant_id="tenant-a",
        home=tenant_home,
        persona_path=persona_path,
        user_message="hello",
        toolsets=["file"],
        on_event=events.append,
    )

    event_types = [e["type"] for e in events]
    assert "step" in event_types
    assert "final" in event_types
    assert event_types.index("step") < event_types.index("final")


def test_submit_turn_returns_final_event_data(
    tenant_home: Path, persona_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    events: list[dict] = []

    result = submit_turn(
        tenant_id="tenant-a",
        home=tenant_home,
        persona_path=persona_path,
        user_message="hello",
        toolsets=["file"],
        on_event=events.append,
    )

    final_events = [e for e in events if e["type"] == "final"]
    assert len(final_events) == 1
    assert result == final_events[0]["data"]


def test_final_event_data_proves_cwd_and_hermes_home_match_tenant_home(
    tenant_home: Path, persona_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker subprocess must run with HERMES_HOME == cwd == the tenant
    home it was handed -- the env-before-import isolation wall requires both,
    and AGENTS.md is read from cwd (top-level only, no recursive walk)."""
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    events: list[dict] = []

    result = submit_turn(
        tenant_id="tenant-a",
        home=tenant_home,
        persona_path=persona_path,
        user_message="hello",
        toolsets=["file"],
        on_event=events.append,
    )

    assert Path(result["cwd"]).resolve() == tenant_home.resolve()
    assert Path(result["hermes_home"]).resolve() == tenant_home.resolve()


def test_every_emitted_event_is_well_formed_json_object(
    tenant_home: Path, persona_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    events: list[dict] = []

    submit_turn(
        tenant_id="tenant-a",
        home=tenant_home,
        persona_path=persona_path,
        user_message="hello",
        toolsets=["file"],
        on_event=events.append,
    )

    for event in events:
        assert "type" in event
        assert "ts" in event
        assert "data" in event
        assert isinstance(event["data"], dict)


def test_does_not_leak_parent_hermes_home_env(
    tenant_home: Path, persona_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the parent process happens to have its own HERMES_HOME set, the
    child worker must still resolve to the tenant home passed to
    submit_turn, not the parent's env var."""
    monkeypatch.setenv("KAIZEN_WORKER_DRYRUN", "1")
    monkeypatch.setenv("HERMES_HOME", "/tmp/should-not-be-used")
    events: list[dict] = []

    result = submit_turn(
        tenant_id="tenant-a",
        home=tenant_home,
        persona_path=persona_path,
        user_message="hello",
        toolsets=["file"],
        on_event=events.append,
    )

    assert Path(result["hermes_home"]).resolve() == tenant_home.resolve()
