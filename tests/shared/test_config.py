# tests/shared/test_config.py

import pytest
from pathlib import Path

from shared.config import Settings, YAMLConfigManager, get_settings, settings


# ── Settings — critical fields work ──────────────────────────

class TestSettingsCriticalFields:

    def test_singleton(self):
        assert get_settings() is get_settings()
        assert settings is get_settings()

    def test_llm_api_key_readable(self):
        assert hasattr(settings, "llm_api_key")
        assert isinstance(settings.llm_api_key, str)

    def test_llm_model_readable(self):
        assert hasattr(settings, "llm_model")
        assert isinstance(settings.llm_model, str)

    def test_old_openai_field_names_removed(self):
        assert not hasattr(settings, "openai_api_key")
        assert not hasattr(settings, "openai_model")

    def test_database_url_does_not_crash_when_empty(self):
        s = Settings(database_url="")
        assert s.database_url == ""

    def test_all_agent_urls_are_reachable_strings(self):
        assert settings.weather_agent_url.startswith("http")
        assert settings.domestic_flight_agent_url.startswith("http")
        assert settings.intl_flight_agent_url.startswith("http")
        assert settings.hotel_agent_url.startswith("http")
        assert settings.budget_agent_url.startswith("http")

    def test_all_ports_are_positive_integers(self):
        assert settings.gateway_port               > 0
        assert settings.weather_agent_port         > 0
        assert settings.domestic_flight_agent_port > 0
        assert settings.intl_flight_agent_port     > 0
        assert settings.hotel_agent_port           > 0
        assert settings.budget_agent_port          > 0

    def test_timeout_is_positive(self):
        assert settings.default_timeout > 0

    def test_cors_origins_is_non_empty_list(self):
        assert isinstance(settings.cors_origins, list)
        assert len(settings.cors_origins) > 0

    def test_temperature_is_valid_range(self):
        assert 0.0 <= settings.temperature <= 2.0

    def test_max_tokens_is_positive(self):
        assert settings.max_tokens > 0


# ── YAMLConfigManager behavior ────────────────────────────────

class TestYAMLConfigManagerBehavior:

    def test_load_returns_dict_for_valid_file(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "agents.yaml").write_text(
            "agents:\n  weather:\n    url: http://localhost:8001\n"
        )
        mgr  = YAMLConfigManager(tmp_path)
        data = mgr.load("agents")
        assert isinstance(data, dict)
        assert data["agents"]["weather"]["url"] == "http://localhost:8001"

    def test_load_unknown_key_raises_key_error(self, tmp_path):
        mgr = YAMLConfigManager(tmp_path)
        with pytest.raises(KeyError):
            mgr.load("does_not_exist")

    def test_load_missing_file_raises_file_not_found(self, tmp_path):
        mgr = YAMLConfigManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.load("agents")

    def test_second_load_returns_same_object(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "agents.yaml").write_text("x: 1\n")
        mgr = YAMLConfigManager(tmp_path)
        assert mgr.load("agents") is mgr.load("agents")

    def test_reload_picks_up_file_changes(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        f = config_dir / "agents.yaml"

        f.write_text("version: 1\n")
        mgr   = YAMLConfigManager(tmp_path)
        first = mgr.load("agents")
        assert first["version"] == 1

        f.write_text("version: 2\n")
        second = mgr.reload("agents")
        assert second["version"] == 2

    def test_clear_cache_forces_reload_on_next_load(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        f = config_dir / "agents.yaml"

        f.write_text("value: old\n")
        mgr = YAMLConfigManager(tmp_path)
        mgr.load("agents")

        f.write_text("value: new\n")
        mgr.clear_cache()

        assert mgr.load("agents")["value"] == "new"

    def test_empty_yaml_file_returns_empty_dict(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "agents.yaml").write_text("")
        mgr  = YAMLConfigManager(tmp_path)
        data = mgr.load("agents")
        assert data == {}

    def test_all_four_keys_are_registered(self):
        assert set(YAMLConfigManager.REGISTRY.keys()) == {
            "agents", "events", "planner_system", "planner_routing"
        }