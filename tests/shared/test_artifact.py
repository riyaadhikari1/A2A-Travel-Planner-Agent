# tests/shared/test_artifact.py

import json
import pytest
from datetime import datetime, UTC

from shared.schemas.artifact import Artifact, ArtifactType


# ── ArtifactType behavior ─────────────────────────────────────

class TestArtifactTypeBehavior:

    def test_known_type_constructs_from_string(self):
        for value in ["weather", "domestic_flight", "intl_flight", "hotel", "budget"]:
            t = ArtifactType(value)
            assert t == value

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            ArtifactType("nonexistent_agent")

    def test_enum_values_match_agent_names(self):
        """
        If an agent is renamed, this test fails and tells you
        to update ArtifactType to match.
        """
        expected = {"weather", "domestic_flight", "intl_flight", "hotel", "budget"}
        assert {m.value for m in ArtifactType} == expected

    def test_usable_as_dict_key(self):
        d = {ArtifactType.WEATHER: "forecast data"}
        assert d[ArtifactType.WEATHER] == "forecast data"

    def test_usable_in_string_comparison(self):
        assert ArtifactType.WEATHER == "weather"
        assert ArtifactType.HOTEL   == "hotel"


# ── Artifact construction behavior ───────────────────────────

class TestArtifactConstruction:

    def test_known_agent_name_constructs_successfully(self):
        for agent in ["weather", "domestic_flight", "intl_flight", "hotel", "budget"]:
            a = Artifact(artifact_type=agent, agent_name=agent, payload={})
            assert a.artifact_type == agent
            assert a.agent_name    == agent

    def test_unknown_agent_name_does_not_crash(self):
        """
        This was the original bug — unknown agent names raised ValueError.
        """
        a = Artifact(
            artifact_type="future_agent",
            agent_name="future_agent",
            payload={},
        )
        assert a.artifact_type == "future_agent"

    def test_known_type_coerced_to_enum(self):
        a = Artifact(artifact_type="weather", agent_name="weather", payload={})
        assert a.artifact_type is ArtifactType.WEATHER

    def test_unknown_type_stays_as_string(self):
        a = Artifact(artifact_type="unknown_agent", agent_name="x", payload={})
        assert a.artifact_type == "unknown_agent"
        assert not isinstance(a.artifact_type, ArtifactType)

    def test_empty_payload_is_valid(self):
        a = Artifact(artifact_type="budget", agent_name="budget", payload={})
        assert a.payload == {}

    def test_complex_payload_preserved(self):
        payload = {
            "location": "Bangkok",
            "current": {"temperature_2m": 32.1, "wind_speed_10m": 5.2},
            "daily": {"max": [34.0, 33.5, 32.8]},
        }
        a = Artifact(artifact_type="weather", agent_name="weather", payload=payload)
        assert a.payload["current"]["temperature_2m"] == 32.1
        assert a.payload["daily"]["max"]              == [34.0, 33.5, 32.8]

    def test_created_at_is_recent_utc(self):
        before = datetime.now(UTC)
        a      = Artifact(artifact_type="weather", agent_name="weather", payload={})
        after  = datetime.now(UTC)
        assert before <= a.created_at <= after
        assert a.created_at.tzinfo is not None


# ── Artifact serialization behavior ──────────────────────────

class TestArtifactSerialization:

    def test_roundtrip_known_type_preserves_values(self):
        original = Artifact(
            artifact_type="weather",
            agent_name="weather",
            payload={"city": "Bangkok", "temp": 32},
        )
        restored = Artifact.model_validate_json(original.model_dump_json())
        assert restored.artifact_type == original.artifact_type
        assert restored.agent_name    == original.agent_name
        assert restored.payload       == original.payload
        assert restored.created_at    == original.created_at

    def test_roundtrip_unknown_type_preserves_values(self):
        original = Artifact(
            artifact_type="future_agent",
            agent_name="future_agent",
            payload={"data": 123},
        )
        restored = Artifact.model_validate_json(original.model_dump_json())
        assert restored.artifact_type == "future_agent"
        assert restored.payload       == {"data": 123}

    def test_serialized_json_is_valid_json(self):
        a    = Artifact(artifact_type="hotel", agent_name="hotel", payload={"hotels": []})
        data = json.loads(a.model_dump_json())
        assert "artifact_type" in data
        assert "agent_name"    in data
        assert "payload"       in data
        assert "created_at"    in data

    def test_multiple_roundtrips_stable(self):
        """Value does not drift across multiple serialization cycles."""
        a = Artifact(artifact_type="budget", agent_name="budget", payload={"total": 700})
        for _ in range(5):
            a = Artifact.model_validate_json(a.model_dump_json())
        assert a.payload["total"] == 700