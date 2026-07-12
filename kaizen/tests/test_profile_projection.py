"""Tests for kaizen.profile: BrandProfile + SOUL.md/AGENTS.md rendering.

Covers the projection half of the split model (Convex/BrandProfile -> files):
``render_soul`` builds the agency identity + hard guardrails that every
Hermes agent auto-reads from ``$HERMES_HOME/SOUL.md``
(``prompt_builder.py:load_soul_md`` ``:1819``); ``render_agents`` builds the
editable brand DNA that Hermes reads from the worker's cwd as ``AGENTS.md``
(``prompt_builder.py:_load_agents_md`` ``:1876``, top-level only, no
recursive walk). ``parse_agents`` must round-trip whatever ``render_agents``
produced, since the foundation slice treats AGENTS.md as agent-editable
(the Brand Strategist writes brand DNA directly into it via ``write_file``).
"""

from __future__ import annotations

from kaizen.profile import BrandProfile, parse_agents, render_agents, render_soul


def _sample_profile() -> BrandProfile:
    return BrandProfile(
        brand_id="acme-widgets",
        name="Acme Widgets",
        url="https://acme.example.com",
        positioning="The reliable widget for teams who hate flaky widgets.",
        voice_tone="Confident, plain-spoken, a little dry.",
        audience="Ops leads at mid-market logistics companies.",
        dos=["Use concrete numbers", "Lead with the customer's problem"],
        donts=["Don't use exclamation points", "Don't claim #1 without a source"],
        guardrails=[
            "Never promise a delivery date we haven't confirmed.",
            "Never disparage named competitors.",
        ],
        channels=["twitter", "linkedin", "blog"],
    )


class TestBrandProfile:
    def test_is_frozen(self) -> None:
        profile = _sample_profile()
        try:
            profile.name = "Someone Else"  # type: ignore[misc]
        except Exception as exc:
            assert "frozen" in str(exc).lower() or isinstance(exc, AttributeError)
        else:
            raise AssertionError("BrandProfile should be immutable (frozen dataclass)")

    def test_holds_all_fields(self) -> None:
        profile = _sample_profile()
        assert profile.brand_id == "acme-widgets"
        assert profile.name == "Acme Widgets"
        assert profile.url == "https://acme.example.com"
        assert profile.positioning.startswith("The reliable widget")
        assert profile.voice_tone.startswith("Confident")
        assert profile.audience.startswith("Ops leads")
        assert profile.dos == ["Use concrete numbers", "Lead with the customer's problem"]
        assert profile.donts == [
            "Don't use exclamation points",
            "Don't claim #1 without a source",
        ]
        assert len(profile.guardrails) == 2
        assert profile.channels == ["twitter", "linkedin", "blog"]


class TestRenderSoul:
    def test_contains_brand_name_and_identity(self) -> None:
        soul = render_soul(_sample_profile())
        assert "Acme Widgets" in soul

    def test_contains_hard_guardrails_section(self) -> None:
        soul = render_soul(_sample_profile())
        assert "GUARDRAIL" in soul.upper()
        for guardrail in _sample_profile().guardrails:
            assert guardrail in soul

    def test_is_non_empty_markdown(self) -> None:
        soul = render_soul(_sample_profile())
        assert soul.strip()
        assert soul.startswith("#")


class TestRenderAgents:
    def test_contains_delimited_section_markers(self) -> None:
        agents_md = render_agents(_sample_profile())
        assert "<!-- KAIZEN:BRAND_DNA:START -->" in agents_md
        assert "<!-- KAIZEN:BRAND_DNA:END -->" in agents_md

    def test_contains_positioning_and_voice(self) -> None:
        profile = _sample_profile()
        agents_md = render_agents(profile)
        assert profile.positioning in agents_md
        assert profile.voice_tone in agents_md
        assert profile.audience in agents_md

    def test_contains_dos_and_donts(self) -> None:
        profile = _sample_profile()
        agents_md = render_agents(profile)
        for item in profile.dos:
            assert item in agents_md
        for item in profile.donts:
            assert item in agents_md

    def test_contains_channels(self) -> None:
        profile = _sample_profile()
        agents_md = render_agents(profile)
        for channel in profile.channels:
            assert channel in agents_md


class TestParseAgentsRoundTrip:
    def test_round_trips_all_scalar_fields(self) -> None:
        original = _sample_profile()
        rendered = render_agents(original)
        parsed = parse_agents(rendered)

        assert parsed.brand_id == original.brand_id
        assert parsed.name == original.name
        assert parsed.url == original.url
        assert parsed.positioning == original.positioning
        assert parsed.voice_tone == original.voice_tone
        assert parsed.audience == original.audience

    def test_round_trips_list_fields(self) -> None:
        original = _sample_profile()
        parsed = parse_agents(render_agents(original))

        assert parsed.dos == original.dos
        assert parsed.donts == original.donts
        assert parsed.guardrails == original.guardrails
        assert parsed.channels == original.channels

    def test_round_trip_is_idempotent(self) -> None:
        """Rendering the parsed profile again produces the same AGENTS.md.

        This is the property the Brand Strategist relies on: it can read
        AGENTS.md, hand it to parse_agents, and any subsequent render_home
        call reproduces the same file (no drift from re-projection).
        """
        original = _sample_profile()
        first_render = render_agents(original)
        parsed = parse_agents(first_render)
        second_render = render_agents(parsed)
        assert first_render == second_render

    def test_round_trips_when_brand_dna_edited_by_hand(self) -> None:
        """Simulates an agent editing AGENTS.md via write_file: as long as the
        section markers and field labels survive, parsing still works."""
        original = _sample_profile()
        rendered = render_agents(original)
        edited = rendered.replace(
            original.positioning, "A sturdier, more specific positioning statement."
        )
        parsed = parse_agents(edited)
        assert parsed.positioning == "A sturdier, more specific positioning statement."
        # Unrelated fields are untouched by the hand-edit.
        assert parsed.voice_tone == original.voice_tone
        assert parsed.dos == original.dos
