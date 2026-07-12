"""Regression tests for kaizen.worker_pool.submit_turn's stdout-parsing
robustness.

Real Hermes internals write plain-text diagnostics straight to stdout in
several code paths that are NOT gated by ``quiet_mode`` -- most notably the
Nous-provider 401 auth-failure retry/diagnostic prints in
``agent/conversation_loop.py`` (around line 2765-2788), which fire exactly in
the "credentials are missing/invalid" scenario this review was asked to
verify degrades gracefully. Any such line breaks a naive
``json.loads(line)`` per stdout line with an uncaught ``JSONDecodeError``,
turning a recoverable per-turn failure into a hard crash of
``submit_turn`` (and its FastAPI caller), instead of the worker's own
try/except-wrapped "error" event making it through cleanly.

This module stubs ``subprocess.Popen`` so the test doesn't depend on the
real ``kaizen.worker`` subprocess or Hermes internals -- it isolates the bug
to exactly the code under test: ``submit_turn``'s stdout line loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from kaizen import worker_pool


class _FakeStdout:
    """Iterable that yields the given lines like a real Popen.stdout would."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakeStderr:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = _FakeStdout(lines)
        self.stderr = _FakeStderr("")
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


def _patch_popen(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    def _fake_popen(*_args, **_kwargs):
        return _FakeProcess(lines)

    monkeypatch.setattr(worker_pool.subprocess, "Popen", _fake_popen)


def _sample_call(on_event: Callable[[dict], None]) -> dict:
    return worker_pool.submit_turn(
        tenant_id="tenant-a",
        home=Path("/tmp/does-not-need-to-exist-for-this-test"),
        persona_path=Path("/tmp/persona.md"),
        user_message="hello",
        toolsets=["file"],
        on_event=on_event,
    )


class TestSubmitTurnStdoutRobustness:
    def test_ignores_non_json_line_interleaved_with_real_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stray plain-text line (e.g. Hermes' un-gated 401 diagnostic
        prints) between valid JSON-lines events must not crash submit_turn."""
        final_event = {"type": "final", "ts": 1.0, "data": {"final_response": "ok", "completed": True}}
        lines = [
            json.dumps({"type": "step", "ts": 0.0, "data": {"iteration": 1}}),
            "  \U0001f510 Nous 401 — Portal authentication failed.",
            json.dumps(final_event),
        ]
        _patch_popen(monkeypatch, lines)

        events: list[dict] = []
        result = _sample_call(events.append)

        assert result == final_event["data"]
        event_types = [e["type"] for e in events]
        assert event_types == ["step", "final"]

    def test_non_json_only_output_raises_the_documented_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the worker never emits a parseable final event (e.g. it only
        ever produced stray text), submit_turn must fail with its own
        documented RuntimeError -- not an unrelated JSONDecodeError."""
        lines = ["not json at all", "still not json"]
        _patch_popen(monkeypatch, lines)

        with pytest.raises(RuntimeError, match="without emitting a final event"):
            _sample_call(lambda _e: None)
