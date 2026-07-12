"""Tests for kaizen.tenancy: provisioning a tenant HERMES_HOME.

``provision_tenant`` scaffolds a per-brand HERMES_HOME directory containing
SOUL.md, AGENTS.md, config.yaml, honcho.json (and skills/ synced from the
repo, if present) -- the "projection" side of the split model described in
FOUNDATION_SLICE.md section 2 (render_home). None of this touches core
Hermes source; it only writes files that Hermes' own file-based conventions
already read (SOUL.md -- prompt_builder.py:1819, AGENTS.md -- cwd-scoped,
config.yaml -- hermes_cli/config.py:749, honcho.json --
plugins/memory/honcho/client.py:90).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kaizen.profile import BrandProfile
from kaizen.tenancy import provision_tenant, render_home


def _sample_profile(brand_id: str = "acme-widgets") -> BrandProfile:
    return BrandProfile(
        brand_id=brand_id,
        name="Acme Widgets",
        url="https://acme.example.com",
        positioning="The reliable widget for teams who hate flaky widgets.",
        voice_tone="Confident, plain-spoken.",
        audience="Ops leads at mid-market logistics companies.",
        dos=["Use concrete numbers"],
        donts=["Don't use exclamation points"],
        guardrails=["Never promise a delivery date we haven't confirmed."],
        channels=["twitter", "linkedin"],
    )


class TestRenderHome:
    def test_writes_soul_md(self, tmp_path: Path) -> None:
        render_home(_sample_profile(), tmp_path)
        soul_path = tmp_path / "SOUL.md"
        assert soul_path.exists()
        assert "Acme Widgets" in soul_path.read_text(encoding="utf-8")

    def test_writes_agents_md(self, tmp_path: Path) -> None:
        render_home(_sample_profile(), tmp_path)
        agents_path = tmp_path / "AGENTS.md"
        assert agents_path.exists()
        assert "KAIZEN:BRAND_DNA" in agents_path.read_text(encoding="utf-8")

    def test_writes_config_yaml_with_honcho_memory_provider(self, tmp_path: Path) -> None:
        render_home(_sample_profile(), tmp_path)
        config_path = tmp_path / "config.yaml"
        assert config_path.exists()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["memory"]["provider"] == "honcho"
        assert config["memory"]["user_profile_enabled"] is True

    def test_writes_honcho_json_with_workspace_and_peer_as_brand_id(
        self, tmp_path: Path
    ) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        render_home(profile, tmp_path)
        honcho_path = tmp_path / "honcho.json"
        assert honcho_path.exists()
        import json

        honcho_config = json.loads(honcho_path.read_text(encoding="utf-8"))
        assert honcho_config["workspace"] == "acme-widgets"
        assert honcho_config["aiPeer"] == "acme-widgets"

    def test_is_idempotent(self, tmp_path: Path) -> None:
        """Calling render_home twice produces byte-identical files.

        This is the property the deployment doc (FOUNDATION_SLICE.md section
        2) relies on: cold-start can always re-render onto scratch and get
        the same tenant home back.
        """
        profile = _sample_profile()
        render_home(profile, tmp_path)
        first_soul = (tmp_path / "SOUL.md").read_text(encoding="utf-8")
        first_agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        first_config = (tmp_path / "config.yaml").read_text(encoding="utf-8")

        render_home(profile, tmp_path)
        assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == first_soul
        assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first_agents
        assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == first_config


class TestProvisionTenant:
    def test_creates_tenant_dir_under_base_dir(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        home = provision_tenant("acme-widgets", profile, base_dir=tmp_path)
        assert home == tmp_path / "acme-widgets"
        assert home.is_dir()

    def test_creates_all_expected_files(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        home = provision_tenant("acme-widgets", profile, base_dir=tmp_path)
        assert (home / "SOUL.md").exists()
        assert (home / "AGENTS.md").exists()
        assert (home / "config.yaml").exists()
        assert (home / "honcho.json").exists()

    def test_returns_path_usable_as_hermes_home(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="beta-co")
        home = provision_tenant("beta-co", profile, base_dir=tmp_path)
        assert home.is_absolute() or home.is_dir()
        assert home.name == "beta-co"

    def test_default_base_dir_is_data_hermes_profiles(self) -> None:
        import inspect

        from kaizen.tenancy import provision_tenant as _provision_tenant

        sig = inspect.signature(_provision_tenant)
        default_base_dir = sig.parameters["base_dir"].default
        assert str(default_base_dir) == str(Path("/data/hermes/profiles"))

    def test_is_idempotent_across_repeated_calls(self, tmp_path: Path) -> None:
        profile = _sample_profile(brand_id="acme-widgets")
        home_first = provision_tenant("acme-widgets", profile, base_dir=tmp_path)
        home_second = provision_tenant("acme-widgets", profile, base_dir=tmp_path)
        assert home_first == home_second
        assert (home_second / "SOUL.md").exists()
