# tests/state/test_postgres_store.py

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from shared.schemas.artifact import Artifact
from shared.schemas.exceptions import TaskNotFoundException
from shared.schemas.task import TaskRecord, TaskStatus
from state.postgres_store import PostgresStore


def make_task_record(
    task_id: str = "t1",
    status: TaskStatus = TaskStatus.COMPLETED,
    artifacts: list = None,
) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        status=status,
        input="fly to Bangkok",
        artifacts=artifacts or [],
    )


def make_artifact(agent: str = "weather") -> Artifact:
    return Artifact(
        artifact_type=agent,
        agent_name=agent,
        payload={"temp": 32},
    )


def make_mock_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__  = AsyncMock(return_value=False)
    session.begin      = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__  = AsyncMock(return_value=False)
    session.add        = MagicMock()
    session.execute    = AsyncMock()
    return session


def make_mock_factory(session):
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__  = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
class TestPostgresStoreSaveCompleted:

    async def test_save_completed_without_artifacts(self):
        session = make_mock_session()
        store   = PostgresStore(make_mock_factory(session))
        record  = make_task_record()

        await store.save_completed(record)

        session.add.assert_called()

    async def test_save_completed_with_artifacts(self):
        session  = make_mock_session()
        store    = PostgresStore(make_mock_factory(session))
        record   = make_task_record(artifacts=[
            make_artifact("weather"),
            make_artifact("hotel"),
        ])

        await store.save_completed(record)

        assert session.add.call_count == 3  # 1 task + 2 artifacts

    async def test_save_completed_uses_correct_task_fields(self):
        session = make_mock_session()
        store   = PostgresStore(make_mock_factory(session))
        record  = make_task_record(task_id="task-xyz")

        await store.save_completed(record)

        first_call_arg = session.add.call_args_list[0][0][0]
        assert first_call_arg.task_id == "task-xyz"
        assert first_call_arg.input   == "fly to Bangkok"


@pytest.mark.asyncio
class TestPostgresStoreGet:

    async def _make_store_with_result(self, task_id, artifacts=None):
        from database.models import TaskModel, ArtifactModel

        artifact_models = []
        for a in (artifacts or []):
            m            = MagicMock(spec=ArtifactModel)
            m.type       = a.artifact_type
            m.agent_name = a.agent_name
            m.payload    = a.payload
            m.created_at = datetime.now(UTC)
            artifact_models.append(m)

        task_model           = MagicMock(spec=TaskModel)
        task_model.task_id   = task_id
        task_model.status    = "completed"
        task_model.input     = "fly to Bangkok"
        task_model.created_at = datetime.now(UTC)
        task_model.updated_at = datetime.now(UTC)
        task_model.artifacts  = artifact_models

        session = make_mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = task_model
        session.execute.return_value = scalar_result

        store = PostgresStore(make_mock_factory(session))
        return store

    async def test_get_returns_task_record(self):
        store  = await self._make_store_with_result("t1")
        record = await store.get("t1")
        assert record.task_id == "t1"
        assert record.input   == "fly to Bangkok"

    async def test_get_returns_artifacts(self):
        store  = await self._make_store_with_result(
            "t1", artifacts=[make_artifact("weather"), make_artifact("hotel")]
        )
        record = await store.get("t1")
        assert len(record.artifacts) == 2

    async def test_get_nonexistent_raises(self):
        session = make_mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute.return_value = scalar_result

        store = PostgresStore(make_mock_factory(session))
        with pytest.raises(TaskNotFoundException):
            await store.get("nonexistent")

    async def test_artifact_type_reconstructed_correctly(self):
        store  = await self._make_store_with_result(
            "t1", artifacts=[make_artifact("weather")]
        )
        record = await store.get("t1")
        assert record.artifacts[0].artifact_type == "weather"
        assert record.artifacts[0].agent_name    == "weather"