# tests/orchestrator/test_registry.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.schemas.exceptions import AgentUnavailableException
from orchestrator.registry import AgentRegistry


def make_mock_card(name="weather", description="Weather agent"):
    card             = MagicMock()
    card.name        = name
    card.description = description
    card.skills      = []
    return card


def make_mock_resolver(card=None, raises=None):
    resolver = MagicMock()
    if raises:
        resolver.get_agent_card = AsyncMock(side_effect=raises)
    else:
        resolver.get_agent_card = AsyncMock(return_value=card or make_mock_card())
    return resolver


MOCK_AGENTS_CONFIG = {
    "agents": {
        "weather":         {"url": "http://localhost:8001"},
        "domestic_flight": {"url": "http://localhost:8002"},
        "intl_flight":     {"url": "http://localhost:8003"},
        "hotel":           {"url": "http://localhost:8004"},
        "budget":          {"url": "http://localhost:8005"},
    }
}


# ── resolve_all ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestResolveAll:

    async def test_resolves_all_agents_from_yaml(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        assert len(registry._urls) == 5

    async def test_reads_from_agents_yaml_not_settings(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        mock_cm.load.assert_called_once_with("agents")

    async def test_sets_expected_count_from_yaml(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        assert registry._expected == 5

    async def test_failed_agent_does_not_crash_resolve(self):
        registry = AgentRegistry()

        def resolver_factory(httpx_client, base_url):
            if "8001" in base_url:
                return make_mock_resolver(raises=Exception("connection refused"))
            return make_mock_resolver()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver",
                       side_effect=resolver_factory):
                await registry.resolve_all()

        assert len(registry._urls) == 4
        assert "weather" not in registry._urls

    async def test_stores_card_for_resolved_agents(self):
        registry = AgentRegistry()
        card     = make_mock_card(name="weather")

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = {
                "agents": {"weather": {"url": "http://localhost:8001"}}
            }
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver(card=card)
                await registry.resolve_all()

        assert registry.get_card("weather") is card

    async def test_expected_count_reflects_yaml_not_resolved_count(self):
        """_expected is set from YAML size, not how many succeeded."""
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver(
                    raises=Exception("all fail")
                )
                await registry.resolve_all()

        assert registry._expected == 5
        assert len(registry._urls) == 0


# ── get_endpoint ──────────────────────────────────────────────

@pytest.mark.asyncio
class TestGetEndpoint:

    async def test_returns_url_for_resolved_agent(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = {
                "agents": {"weather": {"url": "http://localhost:8001"}}
            }
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        assert registry.get_endpoint("weather") == "http://localhost:8001"

    async def test_raises_for_unknown_agent(self):
        registry = AgentRegistry()
        with pytest.raises(AgentUnavailableException):
            registry.get_endpoint("nonexistent")

    async def test_raises_for_failed_agent(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = {
                "agents": {"weather": {"url": "http://localhost:8001"}}
            }
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver(
                    raises=Exception("failed")
                )
                await registry.resolve_all()

        with pytest.raises(AgentUnavailableException):
            registry.get_endpoint("weather")


# ── get_card ──────────────────────────────────────────────────

class TestGetCard:

    def test_returns_none_for_unknown_agent(self):
        registry = AgentRegistry()
        assert registry.get_card("nonexistent") is None

    def test_returns_none_before_resolve(self):
        registry = AgentRegistry()
        assert registry.get_card("weather") is None


# ── get_all ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGetAll:

    async def test_returns_list_of_agent_dicts(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = {
                "agents": {"weather": {"url": "http://localhost:8001"}}
            }
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver(
                    card=make_mock_card("weather", "Weather forecast")
                )
                await registry.resolve_all()

        result = registry.get_all()
        assert len(result) == 1
        assert result[0]["name"]        == "weather"
        assert result[0]["url"]         == "http://localhost:8001"
        assert result[0]["description"] == "Weather forecast"

    async def test_returns_empty_list_before_resolve(self):
        registry = AgentRegistry()
        assert registry.get_all() == []

    async def test_skills_is_list(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = {
                "agents": {"weather": {"url": "http://localhost:8001"}}
            }
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        result = registry.get_all()
        assert isinstance(result[0]["skills"], list)

    async def test_only_resolved_agents_appear(self):
        registry = AgentRegistry()

        def resolver_factory(httpx_client, base_url):
            if "8001" in base_url:
                return make_mock_resolver()
            return make_mock_resolver(raises=Exception("down"))

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver",
                       side_effect=resolver_factory):
                await registry.resolve_all()

        result = registry.get_all()
        assert len(result) == 1
        assert result[0]["name"] == "weather"


# ── all_healthy ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestAllHealthy:

    async def test_true_when_all_resolved(self):
        registry = AgentRegistry()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        assert registry.all_healthy() is True

    async def test_false_when_some_failed(self):
        registry = AgentRegistry()

        def resolver_factory(httpx_client, base_url):
            if "8001" in base_url:
                return make_mock_resolver(raises=Exception("down"))
            return make_mock_resolver()

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = MOCK_AGENTS_CONFIG
            with patch("orchestrator.registry.A2ACardResolver",
                       side_effect=resolver_factory):
                await registry.resolve_all()

        assert registry.all_healthy() is False

    async def test_false_before_resolve(self):
        """Before resolve_all, no agents are registered."""
        registry = AgentRegistry()
        assert len(registry._urls) == 0
        assert len(registry._cards) == 0

    async def test_reflects_yaml_count_not_hardcoded_five(self):
        """Adding a 6th agent to YAML must not break all_healthy."""
        registry = AgentRegistry()
        config_with_six = {
            "agents": {
                "weather":         {"url": "http://localhost:8001"},
                "domestic_flight": {"url": "http://localhost:8002"},
                "intl_flight":     {"url": "http://localhost:8003"},
                "hotel":           {"url": "http://localhost:8004"},
                "budget":          {"url": "http://localhost:8005"},
                "new_agent":       {"url": "http://localhost:8006"},
            }
        }

        with patch("orchestrator.registry.config_manager") as mock_cm:
            mock_cm.load.return_value = config_with_six
            with patch("orchestrator.registry.A2ACardResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value = make_mock_resolver()
                await registry.resolve_all()

        assert registry._expected == 6
        assert registry.all_healthy() is True


# ── close ─────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestClose:

    async def test_close_does_not_raise(self):
        registry = AgentRegistry()
        with patch.object(registry._http, "aclose", new_callable=AsyncMock):
            await registry.close()

    async def test_close_calls_http_aclose(self):
        registry = AgentRegistry()
        with patch.object(registry._http, "aclose", new_callable=AsyncMock) as mock_close:
            await registry.close()
            mock_close.assert_called_once()