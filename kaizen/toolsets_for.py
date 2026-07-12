"""Per-role ``enabled_toolsets`` selection for Kaizen specialists.

CODE_GROUNDED_PLAN.md: "MCP servers = per profile in ``$HERMES_HOME/
config.yaml`` under ``mcp_servers:``. Each becomes toolset ``mcp-<name>``;
scope a specialist to it via that agent's ``enabled_toolsets``." This module
is the single place that decides which toolsets a given specialist role
gets, so every call site (``routes_brands.py``, ``routes_content.py``, and
any future specialist route) stays in sync with whether Linkup is actually
configured -- instead of each route hardcoding its own toolset list and
drifting.

Gating mirrors ``kaizen.tenancy``'s ``_linkup_mcp_block``: both read
``LINKUP_API_KEY`` from the environment at call time (not import time), so
tests can monkeypatch it per-test without reloading this module.
"""

from __future__ import annotations

import os

_BASE_TOOLSETS = ["web", "file"]

# Roles that should prefer Linkup (real web research via a dedicated search
# API) over the generic ``web`` toolset when it's configured. Per
# FEATURES_AND_AGENTS.md, Linkup is scoped to the Brand Strategist (brand
# research) and the not-yet-built Competitor Analyst; the Content Creator
# stays on plain ``web``/``file`` (it drafts from brand DNA already on disk,
# not fresh research) -- documented call, not a code-forced constraint, so
# adding "content_creator" here later is a one-line change if that changes.
_LINKUP_PREFERRING_ROLES = {"brand_strategist"}


def linkup_configured() -> bool:
    """True when ``LINKUP_API_KEY`` is set in the current environment.

    Truthiness only -- an empty string is treated as unset (mirrors
    ``os.environ.get(...)`` truthiness checks used elsewhere in kaizen, e.g.
    ``convex_client.is_convex_configured``).
    """
    return bool(os.environ.get("LINKUP_API_KEY"))


def toolsets_for(role: str) -> list[str]:
    """Return the ``enabled_toolsets`` list for a specialist role.

    Always includes the baseline ``["web", "file"]`` so a specialist keeps
    working even when Linkup isn't configured. Adds ``"mcp-linkup"`` only
    when both (a) the role is one that prefers Linkup research and (b)
    ``LINKUP_API_KEY`` is set -- absent the key, no ``mcp-linkup`` toolset
    is ever requested, since Hermes wouldn't have a ``linkup`` MCP server
    entry in ``config.yaml`` to back it (see ``kaizen.tenancy.render_home``).

    Unknown roles fall back to the same baseline, so a typo'd or
    not-yet-modeled role name never silently loses ``web``/``file``.
    """
    tools = list(_BASE_TOOLSETS)
    if role in _LINKUP_PREFERRING_ROLES and linkup_configured():
        tools.append("mcp-linkup")
    return tools
