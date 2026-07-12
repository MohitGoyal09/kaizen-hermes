"""Per-tenant Hermes worker: run one conversation turn in an isolated
HERMES_HOME, emitting JSON-lines events on stdout.

This is the subprocess launched by ``kaizen.worker_pool.submit_turn``. It is
the isolation wall proven in ``kaizen/tests/test_isolation.py``:
``HERMES_HOME`` MUST be set in this process's environment *before* Hermes is
imported, because ``hermes_state.DEFAULT_DB_PATH`` (the sessions DB path)
and the Honcho client singleton are both frozen/created at import time
(CODE_GROUNDED_PLAN.md, "Multi-tenancy verdict"). Running this as
``python -m kaizen.worker`` with ``env={"HERMES_HOME": ...}`` passed to
``subprocess.Popen`` gets this for free — no in-process import has happened
yet when the interpreter starts.

The worker also chdirs to HERMES_HOME before running a turn: AGENTS.md is
read from the process cwd, not from HERMES_HOME
(``prompt_builder.py:_load_agents_md`` ``:1876``, top-level only, no
recursive walk) — so if cwd drifted from HERMES_HOME the worker would read
the wrong (or the 71 KB Hermes repo-root) AGENTS.md.

Job spec (JSON, from argv[1] or stdin if argv[1] is absent/"-"):
    {"persona_path": str, "user_message": str, "toolsets": [str, ...]}

Emitted events (one JSON object per stdout line):
    {"type": "step"|"tool_start"|"tool_complete"|"text_delta"|"final"|"error",
     "ts": float, "data": {...}}

  - "final".data   -> {"final_response": str, "completed": bool,
                       "cwd": str, "hermes_home": str}
  - "error".data   -> {"message": str}

Set KAIZEN_WORKER_DRYRUN=1 to skip the LLM entirely: emits a synthetic
"step" then "final" (with real cwd/hermes_home) so the wiring
(env-before-import, chdir, event streaming) can be tested without an API
key or network access.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _emit(event_type: str, data: dict[str, Any]) -> None:
    """Write one JSON-lines event to stdout and flush immediately.

    Flushing per-line matters: the parent (worker_pool.submit_turn) reads
    stdout line-by-line as the subprocess runs, so buffering would delay
    events until the OS pipe buffer filled or the process exited.
    """
    line = json.dumps({"type": event_type, "ts": time.time(), "data": data})
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _ensure_cwd_matches_hermes_home(hermes_home: Path) -> None:
    """Chdir into hermes_home if the process didn't already start there.

    worker_pool.submit_turn always passes cwd=home to Popen, so this is a
    belt-and-braces guard for any other launcher of this module.
    """
    if Path.cwd().resolve() != hermes_home.resolve():
        os.chdir(hermes_home)


def _read_job_spec() -> dict[str, Any]:
    """Read the job spec from argv[1], or stdin if no argv[1] is given."""
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    return json.loads(raw)


def _run_dryrun(hermes_home: Path) -> None:
    """Emit a synthetic step + final event without touching the LLM.

    The final event's data includes cwd + hermes_home specifically so
    callers can assert the isolation wiring (env-before-import, chdir to
    HERMES_HOME) actually took effect, with no API key required.
    """
    _emit("step", {"iteration": 1, "note": "dryrun"})
    _emit(
        "final",
        {
            "final_response": "[dryrun] no LLM call was made",
            "completed": True,
            "cwd": str(Path.cwd()),
            "hermes_home": str(hermes_home),
        },
    )


def _run_live(hermes_home: Path, job: dict[str, Any]) -> None:
    """Build an AIAgent and run one conversation turn, streaming events.

    Imported here (not at module top) so that in dryrun mode — and so that
    importing kaizen.worker itself — never pulls in Hermes before
    HERMES_HOME is set. This mirrors hermes_cli/oneshot.py:_run_agent's
    local-import pattern (``:297-420``).
    """
    from run_agent import AIAgent

    persona_path = Path(job["persona_path"])
    persona_text = persona_path.read_text(encoding="utf-8")
    toolsets = job.get("toolsets") or []
    user_message = job["user_message"]

    def _on_step(iteration: int, *_args: Any) -> None:
        _emit("step", {"iteration": iteration})

    def _on_tool_start(_task_id: Any, name: str, args: Any) -> None:
        _emit("tool_start", {"name": name, "args": args})

    def _on_tool_complete(_task_id: Any, name: str, args: Any, result: Any) -> None:
        _emit("tool_complete", {"name": name, "args": args, "result": result})

    def _on_event(event_name: str, payload: dict) -> None:
        _emit(event_name, payload)

    def _on_stream_delta(delta: str) -> None:
        _emit("text_delta", {"delta": delta})

    agent = AIAgent(
        model="",
        enabled_toolsets=toolsets,
        ephemeral_system_prompt=persona_text,
        quiet_mode=True,
        step_callback=_on_step,
        tool_start_callback=_on_tool_start,
        tool_complete_callback=_on_tool_complete,
        event_callback=_on_event,
    )

    result = agent.run_conversation(user_message, stream_callback=_on_stream_delta)

    _emit(
        "final",
        {
            "final_response": result.get("final_response"),
            "completed": result.get("completed"),
            "cwd": str(Path.cwd()),
            "hermes_home": str(hermes_home),
        },
    )


def main() -> int:
    """Entrypoint for ``python -m kaizen.worker``. Never raises: any failure
    is caught and emitted as an "error" event so the parent always gets a
    terminating event instead of hanging on a dead pipe."""
    hermes_home_raw = os.environ.get("HERMES_HOME", "").strip()
    if not hermes_home_raw:
        _emit("error", {"message": "HERMES_HOME is not set in worker env"})
        return 1
    hermes_home = Path(hermes_home_raw)

    try:
        _ensure_cwd_matches_hermes_home(hermes_home)

        if os.environ.get("KAIZEN_WORKER_DRYRUN", "").strip() == "1":
            _run_dryrun(hermes_home)
            return 0

        job = _read_job_spec()
        _run_live(hermes_home, job)
        return 0
    except Exception as exc:  # noqa: BLE001 - worker must never crash hard
        _emit("error", {"message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
