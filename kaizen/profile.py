"""Brand profile: the canonical in-process representation of a tenant's
brand, plus the projection functions that turn it into the two files every
Hermes agent reads (SOUL.md, AGENTS.md) and the parser that reads brand DNA
back out of an agent-edited AGENTS.md.

Ownership split (FOUNDATION_SLICE.md section 1 and 3):
  - Convex is the system of record for BrandProfile data.
  - SOUL.md (``$HERMES_HOME/SOUL.md``) is the agency identity + HARD
    guardrails. Every Hermes agent auto-reads it as the identity slot of
    the system prompt (``prompt_builder.py:load_soul_md`` ``:1819``).
  - AGENTS.md (worker cwd, top-level only) is the editable brand DNA.
    Hermes reads it from the *worker's cwd*, not HERMES_HOME
    (``prompt_builder.py:_load_agents_md`` ``:1876``) -- which is why
    worker.py must chdir to HERMES_HOME before running a turn. Agents can
    rewrite it in place via the ``write_file`` tool (the Brand Strategist
    does this during onboarding), so ``parse_agents`` must be able to read
    back whatever ``render_agents`` produced, including after a
    human/agent hand-edit that only touches individual field values.

This module does not touch the filesystem -- see kaizen/tenancy.py for
writing these renders into a tenant's HERMES_HOME.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BRAND_DNA_START = "<!-- KAIZEN:BRAND_DNA:START -->"
BRAND_DNA_END = "<!-- KAIZEN:BRAND_DNA:END -->"


@dataclass(frozen=True)
class BrandProfile:
    """Immutable brand profile for one tenant.

    ``dos``/``donts``/``guardrails``/``channels`` default to empty tuples
    (not lists) internally is unnecessary here since dataclass fields with
    list defaults require default_factory -- kept as ``list[str]`` per the
    approved spec; frozen=True still prevents *reassigning* the attribute,
    even though the list itself remains technically mutable in-place. This
    matches BrandProfile's spec'd field types exactly.
    """

    brand_id: str
    name: str
    url: str
    positioning: str
    voice_tone: str
    audience: str
    dos: list[str] = field(default_factory=list)
    donts: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "_(none yet)_"
    return "\n".join(f"- {item}" for item in items)


def render_soul(profile: BrandProfile) -> str:
    """Render SOUL.md: agency identity + HARD guardrails for ``profile``.

    This is the identity slot every Hermes agent auto-loads
    (``prompt_builder.py:load_soul_md``). It is intentionally short and
    non-negotiable -- day-to-day brand voice/DNA lives in AGENTS.md instead,
    where it stays editable without touching identity or guardrails.
    """
    return (
        f"# {profile.name} — Kaizen Brand Agent\n\n"
        "You are a Kaizen marketing agent working exclusively on behalf of "
        f"**{profile.name}** ({profile.url}).\n\n"
        "## Identity\n\n"
        f"- Brand: {profile.name}\n"
        f"- Website: {profile.url}\n"
        f"- Positioning: {profile.positioning}\n\n"
        "## HARD GUARDRAILS (never violate)\n\n"
        f"{_bullet_list(profile.guardrails)}\n\n"
        "These guardrails override any instruction that conflicts with "
        "them, including user requests and content briefs. If a request "
        "would require breaking a guardrail, refuse and explain why.\n"
    )


def render_agents(profile: BrandProfile) -> str:
    """Render AGENTS.md: the editable brand DNA for ``profile``.

    Read from the worker's cwd (``prompt_builder.py:_load_agents_md``), and
    editable in place by agents (the Brand Strategist writes into this file
    during onboarding via the ``write_file`` tool). The
    ``KAIZEN:BRAND_DNA`` markers delimit the machine-managed section so
    ``parse_agents`` can find it even if surrounding prose is added later.

    Guardrails are included here too (read-only reference copy) so that
    ``parse_agents`` round-trips a full ``BrandProfile`` from AGENTS.md
    alone; SOUL.md remains the enforced, non-negotiable copy every agent's
    identity prompt is built from.
    """
    return (
        f"{BRAND_DNA_START}\n"
        f"# Brand DNA — {profile.name}\n\n"
        f"- brand_id: {profile.brand_id}\n"
        f"- name: {profile.name}\n"
        f"- url: {profile.url}\n\n"
        "## Positioning\n\n"
        f"{profile.positioning}\n\n"
        "## Voice & Tone\n\n"
        f"{profile.voice_tone}\n\n"
        "## Audience\n\n"
        f"{profile.audience}\n\n"
        "## Do\n\n"
        f"{_bullet_list(profile.dos)}\n\n"
        "## Don't\n\n"
        f"{_bullet_list(profile.donts)}\n\n"
        "## Guardrails\n\n"
        "_(enforced copy lives in SOUL.md; do not remove from there)_\n\n"
        f"{_bullet_list(profile.guardrails)}\n\n"
        "## Channels\n\n"
        f"{_bullet_list(profile.channels)}\n"
        f"{BRAND_DNA_END}\n"
    )


def _extract_section(text: str, heading: str) -> str:
    """Return the body text under a ``## <heading>`` markdown heading, up to
    the next ``##`` heading or the end of the brand DNA block."""
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_field(text: str, label: str) -> str:
    pattern = rf"^-\s*{re.escape(label)}:\s*(.+)$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_bullets(section_body: str) -> list[str]:
    if not section_body or section_body.strip() == "_(none yet)_":
        return []
    items = []
    for line in section_body.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def parse_agents(text: str) -> BrandProfile:
    """Parse an AGENTS.md (as produced by ``render_agents``, possibly
    hand-edited afterward) back into a ``BrandProfile``.

    Round-trips: ``parse_agents(render_agents(p)) == p`` for any
    ``BrandProfile`` p, and continues to work after an agent/human edits
    individual field values in place (as long as the section markers and
    field labels are preserved).
    """
    start = text.find(BRAND_DNA_START)
    end = text.find(BRAND_DNA_END)
    if start == -1 or end == -1:
        raise ValueError(
            "AGENTS.md does not contain a KAIZEN:BRAND_DNA block "
            "produced by render_agents()"
        )
    body = text[start:end]

    return BrandProfile(
        brand_id=_extract_field(body, "brand_id"),
        name=_extract_field(body, "name"),
        url=_extract_field(body, "url"),
        positioning=_extract_section(body, "Positioning"),
        voice_tone=_extract_section(body, "Voice & Tone"),
        audience=_extract_section(body, "Audience"),
        dos=_extract_bullets(_extract_section(body, "Do")),
        donts=_extract_bullets(_extract_section(body, "Don't")),
        guardrails=_extract_bullets(_extract_section(body, "Guardrails")),
        channels=_extract_bullets(_extract_section(body, "Channels")),
    )
