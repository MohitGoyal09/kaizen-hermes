"""Tests for Linkup MCP wiring + per-role toolset selection.

Everything here is gated on ``LINKUP_API_KEY``: when it's set in the
environment, ``render_home`` writes an ``mcp_servers.linkup`` block into
``config.yaml`` (per the schema in ``cli-config.yaml.example``'s
``mcp_servers:`` section -- ``command``/``args``/``env``) and
``kaizen.toolsets_for.toolsets_for`` includes the ``"mcp-linkup"`` toolset
(CODE_GROUNDED_PLAN.md: "each [MCP server] becomes toolset `mcp-<name>`").
When the key is absent, neither happens -- specialists still get their
baseline ``web``/``file`` tools, and no broken/empty MCP server entry is
ever written.

No live LLM or MCP calls anywhere in this file: ``render_home`` only writes
files, and ``toolsets_for`` is pure list logic. The Linkup MCP server itself
is never started.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kaizen.profile import BrandProfile
from kaizen.tenancy import provision_tenant, render_home
from kaizen.toolsets_for import toolsets_for


def _sample_profile(brand_id: str = "acme-widgets") -> BrandProfile:
    return BrandProfile(
        brand_id=brand_id,
        name="Acme Widgets",
        url="https://acme.example.com",
        positioning="The reliable widget for teams who hate flaky widgets.",
        voice_tone="Confident, plain-spoken.",
        audience="Ops leads at mid-market logistics companies.",
    )


class TestRenderHomeLinkupConfigured:
    """LINKUP_API_KEY set -> mcp_servers.linkup block written."""

    def test_writes_mcp_servers_linkup_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINKUP_API_KEY", "test-linkup-key")
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert "linkup" in config["mcp_servers"]

    def test_linkup_block_uses_npx_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINKUP_API_KEY", "test-linkup-key")
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        linkup = config["mcp_servers"]["linkup"]
        assert linkup["command"] == "npx"
        assert isinstance(linkup["args"], list)
        assert "linkup-mcp-server" in linkup["args"]

    def test_linkup_block_passes_key_via_env_not_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The secret must flow through ``env.LINKUP_API_KEY`` (matching the
        ``github`` example in cli-config.yaml.example, which also puts its
        PAT under ``env:``), never inlined into the ``args`` list as a bare
        ``apiKey=...`` CLI argument -- Linkup's docs show that form too, but
        it would put the raw key next to `command`/`args` rather than in the
        dedicated secret slot Hermes' schema provides."""
        monkeypatch.setenv("LINKUP_API_KEY", "sk-super-secret-value")
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        linkup = config["mcp_servers"]["linkup"]
        assert linkup["env"]["LINKUP_API_KEY"] == "sk-super-secret-value"
        assert not any("sk-super-secret-value" in arg for arg in linkup["args"])

    def test_other_config_keys_remain_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adding the linkup MCP block must not disturb model/memory config."""
        monkeypatch.setenv("LINKUP_API_KEY", "test-linkup-key")
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert config["model"]["provider"] == "openai-api"
        assert config["memory"]["provider"] == "honcho"
        assert config["memory"]["user_profile_enabled"] is True


class TestRenderHomeLinkupUnconfigured:
    """LINKUP_API_KEY unset -> no linkup block, no broken/empty server."""

    def test_omits_linkup_entirely_when_key_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert "linkup" not in config["mcp_servers"]

    def test_mcp_servers_key_still_present_but_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert config["mcp_servers"] == {}

    def test_other_config_keys_remain_intact_without_linkup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        render_home(_sample_profile(), tmp_path)

        config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert config["model"]["provider"] == "openai-api"
        assert config["memory"]["provider"] == "honcho"


class TestToolsetsForLinkupConfigured:
    def test_brand_strategist_includes_mcp_linkup_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINKUP_API_KEY", "test-linkup-key")
        tools = toolsets_for("brand_strategist")
        assert "mcp-linkup" in tools

    def test_brand_strategist_still_includes_web_and_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINKUP_API_KEY", "test-linkup-key")
        tools = toolsets_for("brand_strategist")
        assert "web" in tools
        assert "file" in tools


class TestToolsetsForLinkupUnconfigured:
    def test_brand_strategist_excludes_mcp_linkup_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        tools = toolsets_for("brand_strategist")
        assert "mcp-linkup" not in tools

    def test_brand_strategist_still_gets_web_and_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        tools = toolsets_for("brand_strategist")
        assert "web" in tools
        assert "file" in tools

    def test_content_creator_gets_web_and_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        tools = toolsets_for("content_creator")
        assert "web" in tools
        assert "file" in tools

    def test_unknown_role_falls_back_to_web_and_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINKUP_API_KEY", raising=False)
        tools = toolsets_for("some_future_role")
        assert tools == ["web", "file"]


class TestProvisionTenantSyncsSkill:
    """provision_tenant must copy the repo skill into $HERMES_HOME/skills/."""

    def test_copies_on_brand_content_skill_into_tenant_home(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        home = provision_tenant("acme-widgets", profile, base_dir=tmp_path)

        skill_path = home / "skills" / "marketing" / "on-brand-content" / "SKILL.md"
        assert skill_path.exists()

    def test_synced_skill_has_name_and_description_frontmatter(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        home = provision_tenant("acme-widgets", profile, base_dir=tmp_path)

        skill_path = home / "skills" / "marketing" / "on-brand-content" / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "name:" in text
        assert "description:" in text
