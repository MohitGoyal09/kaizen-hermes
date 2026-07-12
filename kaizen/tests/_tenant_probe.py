"""Subprocess probe used by the Phase 0 isolation spike.

Run as a standalone process with ``HERMES_HOME`` set in the environment
*before* Python starts. It imports Hermes' session store (which freezes
``DEFAULT_DB_PATH`` at import time — see ``hermes_state.py:123``), writes one
session + one message tagged with a per-tenant marker, and prints the resolved
DB path as JSON on stdout.

This is deliberately a separate process, not an in-process ContextVar override:
the state DB path is import-frozen, so process-per-tenant (env-before-import) is
the only sound isolation wall (see kaizen/CODE_GROUNDED_PLAN.md, "Multi-tenancy
verdict").

Usage:
    HERMES_HOME=/path/to/tenant python3 -m kaizen.tests._tenant_probe <marker>
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    marker = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    # Import AFTER HERMES_HOME is set in env. DEFAULT_DB_PATH is computed at
    # import time from get_hermes_home(), so it resolves to this tenant's dir.
    import hermes_state
    from hermes_state import SessionDB

    db = SessionDB()  # no path → uses import-frozen DEFAULT_DB_PATH

    session_id = f"sess-{marker}"
    db.create_session(session_id, source="kaizen-isolation-probe")
    db.append_message(session_id, role="user", content=f"marker::{marker}")
    db.close()

    print(
        json.dumps(
            {
                "marker": marker,
                "hermes_home": os.environ.get("HERMES_HOME"),
                "db_path": str(db.db_path),
                "default_db_path": str(hermes_state.DEFAULT_DB_PATH),
                "session_id": session_id,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
