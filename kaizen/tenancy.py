"""Tenant provisioning: materialize a per-brand HERMES_HOME on disk.

This is the "render_home" abstraction from FOUNDATION_SLICE.md section 2:
one function that reads a canonical BrandProfile and writes the files
Hermes' own conventions already read --

  - SOUL.md      identity + HARD guardrails (prompt_builder.py:load_soul_md
                 ``:1819``)
  - AGENTS.md    editable brand DNA (prompt_builder.py:_load_agents_md
                 ``:1876``, read from the worker's cwd, top-level only)
  - config.yaml  model + memory.provider: honcho (hermes_cli/config.py
                 resolves this at ``get_hermes_home() / "config.yaml"``,
                 ``:749``)
  - honcho.json  per-tenant workspace/peer (plugins/memory/honcho/client.py
                 resolves ``$HERMES_HOME/honcho.json`` first, ``:90``)

render_home is idempotent by construction (each call fully overwrites its
managed files with the same deterministic content for the same profile) so
it works unmodified across every deployment model in the spec: provision
time onto a persistent volume (A), cold-start onto scratch (B), or inside a
per-tenant sandbox (C). No core Hermes source is touched -- this only
writes files that Hermes already knows how to read.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from kaizen.profile import BrandProfile, render_agents, render_soul

DEFAULT_MODEL = "anthropic/claude-opus-4.6"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_SKILLS_DIR = _REPO_ROOT / "skills"


def _build_config_yaml() -> dict:
    """Build the config.yaml mapping for a tenant HERMES_HOME.

    ``memory.provider: honcho`` + ``memory.user_profile_enabled: true`` are
    the two keys agent_init.py reads to activate the Honcho memory plugin
    (``agent_init.py:1338-1364``); ``model.default``/``model.base_url`` are
    read by ``hermes_cli/config.py``'s model resolution (see
    ``cli-config.yaml.example``).
    """
    return {
        "model": {
            "default": DEFAULT_MODEL,
            "base_url": DEFAULT_BASE_URL,
        },
        "memory": {
            "memory_enabled": True,
            "provider": "honcho",
            "user_profile_enabled": True,
        },
        "mcp_servers": {},
    }


def _build_honcho_json(brand_id: str) -> dict:
    """Build the honcho.json mapping for a tenant.

    Keys match what ``HonchoClientConfig.from_global_config`` actually
    reads from ``$HERMES_HOME/honcho.json``
    (``plugins/memory/honcho/client.py:433-459``): ``workspace``, ``aiPeer``
    (camelCase — confirmed against source, not ``api_key``), ``baseUrl``.
    One workspace/peer per brand keeps each tenant's Honcho memory
    partitioned from every other tenant.
    """
    return {
        "workspace": brand_id,
        "aiPeer": brand_id,
        "enabled": True,
    }


def render_home(profile: BrandProfile, dest: Path) -> None:
    """Materialize ``profile`` into ``dest`` as a Hermes HERMES_HOME.

    Writes SOUL.md, AGENTS.md, config.yaml, and honcho.json. Idempotent:
    calling this twice with the same profile overwrites with identical
    content. Does not create ``dest`` itself — callers (e.g.
    ``provision_tenant``) are responsible for the directory existing.
    """
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "SOUL.md").write_text(render_soul(profile), encoding="utf-8")
    (dest / "AGENTS.md").write_text(render_agents(profile), encoding="utf-8")

    config_yaml = yaml.safe_dump(
        _build_config_yaml(), sort_keys=False, default_flow_style=False
    )
    (dest / "config.yaml").write_text(config_yaml, encoding="utf-8")

    honcho_json = json.dumps(_build_honcho_json(profile.brand_id), indent=2) + "\n"
    (dest / "honcho.json").write_text(honcho_json, encoding="utf-8")


def _sync_skills(dest: Path) -> None:
    """Copy the repo's shared ``skills/`` tree into the tenant home, if any.

    Skills are declarative and version-controlled in the repo
    (``$HERMES_HOME/skills/<category>/<name>/SKILL.md`` per
    CODE_GROUNDED_PLAN.md); syncing them at provision time makes them
    available to the tenant's worker without touching core Hermes source.
    A missing repo skills/ dir is not an error — the tenant simply starts
    with no skills.
    """
    if not _REPO_SKILLS_DIR.is_dir():
        return
    dest_skills = dest / "skills"
    shutil.copytree(_REPO_SKILLS_DIR, dest_skills, dirs_exist_ok=True)


def provision_tenant(
    brand_id: str,
    profile: BrandProfile,
    base_dir: Path = Path("/data/hermes/profiles"),
) -> Path:
    """Provision a tenant HERMES_HOME under ``base_dir`` for ``brand_id``.

    Creates ``base_dir/<brand_id>/``, calls ``render_home`` to write
    SOUL.md/AGENTS.md/config.yaml/honcho.json, syncs the repo's ``skills/``
    tree if present, and returns the resulting path. This path is what a
    caller sets as ``HERMES_HOME`` (in the worker's env, before Hermes is
    imported — see kaizen/worker.py) for that tenant.

    ``base_dir`` defaults to ``/data/hermes/profiles`` (the production
    volume mount from FOUNDATION_SLICE.md's Approach A) but is overridable
    so tests can provision into a tmp_path.
    """
    home = base_dir / brand_id
    home.mkdir(parents=True, exist_ok=True)
    render_home(profile, home)
    _sync_skills(home)
    return home
