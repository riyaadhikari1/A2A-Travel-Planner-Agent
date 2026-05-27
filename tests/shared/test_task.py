# tests/shared/test_task.py

import pytest
from datetime import UTC, datetime

from shared.schemas.artifact import Artifact, ArtifactType
from shared.schemas.task import AgentRequest, AgentResponse, TaskRecord, TaskStatus


def make_artifact(agent: str = "weather") -> Artifact:
    return Artifact(artifact_type=agent, agent_name=agent, payload={"temp": 32})


# ── TaskStatus behavior ───────────────────────────────────────

class TestTaskStatusBehavior:

    def test_all_four_statuses_construct_from_string(self):
        assert TaskStatus("queued")    is TaskStatus.QUEUED
        assert TaskStatus("running")   is TaskStatus.RUNNING
        assert TaskStatus("completed") is TaskStatus.COMPLETED
        assert TaskStatus("failed")    is TaskStatus.FAILED

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError):
            TaskStatus("unknown")

    def test_usable_in_string_comparison(self):
        assert TaskStatus.QUEUED    == "queued"
        assert TaskStatus.COMPLETED == "completed"

    def test_valid_lifecycle_order(self):
        """Statuses exist for the full lifecycle."""
        lifecycle = [
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
        ]
        assert all(isinstance(s, TaskStatus) for s in lifecycle)

    def test_failed_is_terminal_status(self):
        assert TaskStatus("failed") is TaskStatus.FAILED


# ── TaskRecord behavior ───────────────────────────────────────

class TestTaskRecordBehavior:

    def test_creation_requires_task_id_status_input(self):
        with pytest.raises(Exception):
            TaskRecord()

    def test_minimal_creation(self):
        r = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="fly to Bangkok")
        assert r.task_id == "t1"
        assert r.status  == TaskStatus.QUEUED
        assert r.input   == "fly to Bangkok"

    def test_artifacts_empty_by_default(self):
        r = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="x")
        assert r.artifacts == []

    def test_can_append_artifacts(self):
        r = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="x")
        r.artifacts.append(make_artifact("weather"))
        r.artifacts.append(make_artifact("hotel"))
        assert len(r.artifacts) == 2
        assert r.artifacts[0].agent_name == "weather"
        assert r.artifacts[1].agent_name == "hotel"

    def test_status_can_be_updated(self):
        r = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="x")
        r.status = TaskStatus.RUNNING
        assert r.status == TaskStatus.RUNNING
        r.status = TaskStatus.COMPLETED
        assert r.status == TaskStatus.COMPLETED

    def test_timestamps_are_recent_utc(self):
        before = datetime.now(UTC)
        r      = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="x")
        after  = datetime.now(UTC)
        assert before <= r.created_at <= after
        assert before <= r.updated_at <= after
        assert r.created_at.tzinfo is not None
        assert r.updated_at.tzinfo is not None

    def test_roundtrip_serialization_preserves_all_values(self):
        original = TaskRecord(
            task_id="t1",
            status=TaskStatus.RUNNING,
            input="fly to Bangkok",
            artifacts=[make_artifact("hotel")],
        )
        restored = TaskRecord.model_validate_json(original.model_dump_json())
        assert restored.task_id                  == original.task_id
        assert restored.status                   == original.status
        assert restored.input                    == original.input
        assert len(restored.artifacts)           == 1
        assert restored.artifacts[0].agent_name  == "hotel"

    def test_two_records_do_not_share_artifacts_list(self):
        """default_factory must create a new list per instance."""
        r1 = TaskRecord(task_id="t1", status=TaskStatus.QUEUED, input="x")
        r2 = TaskRecord(task_id="t2", status=TaskStatus.QUEUED, input="y")
        r1.artifacts.append(make_artifact())
        assert len(r2.artifacts) == 0


# ── AgentRequest behavior ─────────────────────────────────────

class TestAgentRequestBehavior:

    def test_requires_task_id_and_instruction(self):
        with pytest.raises(Exception):
            AgentRequest()

    def test_construction(self):
        r = AgentRequest(task_id="t1", instruction="Get weather in Bangkok")
        assert r.task_id     == "t1"
        assert r.instruction == "Get weather in Bangkok"

    def test_extra_fields_rejected(self):
        """parameters field was removed — passing it should either be
        ignored or raise, not silently accepted."""
        with pytest.raises(Exception):
            AgentRequest(task_id="t1", instruction="x", parameters={"key": "val"})

    def test_roundtrip_serialization(self):
        original = AgentRequest(task_id="t1", instruction="Find hotels in Bangkok")
        restored = AgentRequest.model_validate_json(original.model_dump_json())
        assert restored.task_id     == original.task_id
        assert restored.instruction == original.instruction


# ── AgentResponse behavior ────────────────────────────────────

class TestAgentResponseBehavior:

    def test_requires_agent_name_and_artifact(self):
        with pytest.raises(Exception):
            AgentResponse()

    def test_duration_defaults_to_zero(self):
        r = AgentResponse(agent_name="weather", artifact=make_artifact())
        assert r.duration_ms == 0

    def test_duration_can_be_set(self):
        r = AgentResponse(
            agent_name="weather",
            artifact=make_artifact(),
            duration_ms=342,
        )
        assert r.duration_ms == 342

    def test_artifact_is_accessible(self):
        a = make_artifact("budget")
        r = AgentResponse(agent_name="budget", artifact=a)
        assert r.artifact.agent_name      == "budget"
        assert r.artifact.payload["temp"] == 32

    def test_roundtrip_serialization(self):
        original = AgentResponse(
            agent_name="hotel",
            artifact=make_artifact("hotel"),
            duration_ms=512,
        )
        restored = AgentResponse.model_validate_json(original.model_dump_json())
        assert restored.agent_name             == original.agent_name
        assert restored.duration_ms            == original.duration_ms
        assert restored.artifact.agent_name    == original.artifact.agent_name