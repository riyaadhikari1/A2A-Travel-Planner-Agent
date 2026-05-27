# tests/database/test_models.py

import pytest
import inspect
from datetime import datetime, UTC

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from database.models import Base, TaskModel, ArtifactModel


# ── in-memory SQLite engine for tests ────────────────────────

@pytest.fixture(scope="module")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest.fixture(scope="module")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session(engine, tables):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ── TaskModel behavior ────────────────────────────────────────

@pytest.mark.asyncio
class TestTaskModelBehavior:

    async def test_can_save_and_retrieve_task(self, session):
        task = TaskModel(
            task_id="t-001",
            status="queued",
            input="fly to Bangkok",
        )
        session.add(task)
        await session.commit()

        result = await session.get(TaskModel, "t-001")
        assert result is not None
        assert result.task_id == "t-001"
        assert result.status  == "queued"
        assert result.input   == "fly to Bangkok"

    async def test_task_id_is_unique(self, session):
        session.add(TaskModel(task_id="dup", status="queued", input="x"))
        await session.commit()

        from sqlalchemy.exc import IntegrityError
        session.add(TaskModel(task_id="dup", status="queued", input="y"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async def test_status_is_stored_as_string(self, session):
        session.add(TaskModel(task_id="t-status", status="running", input="x"))
        await session.commit()

        result = await session.get(TaskModel, "t-status")
        assert isinstance(result.status, str)
        assert result.status == "running"


# ── ArtifactModel behavior ────────────────────────────────────

@pytest.mark.asyncio
class TestArtifactModelBehavior:

    async def test_can_save_and_retrieve_artifact(self, session):
        session.add(TaskModel(task_id="t-art", status="completed", input="x"))
        await session.commit()

        artifact = ArtifactModel(
            task_id="t-art",
            type="weather",
            agent_name="weather",
            payload={"temp": 32, "city": "Bangkok"},
        )
        session.add(artifact)
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(ArtifactModel).where(ArtifactModel.task_id == "t-art")
        )
        saved = result.scalar_one()
        assert saved.type       == "weather"
        assert saved.agent_name == "weather"
        assert saved.payload    == {"temp": 32, "city": "Bangkok"}

    async def test_payload_preserves_nested_structure(self, session):
        session.add(TaskModel(task_id="t-nested", status="completed", input="x"))
        await session.commit()

        payload = {
            "location": "Bangkok",
            "current": {"temperature_2m": 32.1},
            "daily": {"max": [34.0, 33.5]},
        }
        session.add(ArtifactModel(
            task_id="t-nested",
            type="weather",
            agent_name="weather",
            payload=payload,
        ))
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(ArtifactModel).where(ArtifactModel.task_id == "t-nested")
        )
        saved = result.scalar_one()
        assert saved.payload["current"]["temperature_2m"] == 32.1
        assert saved.payload["daily"]["max"] == [34.0, 33.5]



# ── Cascade behavior ──────────────────────────────────────────

@pytest.mark.asyncio
class TestCascadeBehavior:

    async def test_deleting_task_deletes_artifacts(self, session):
        session.add(TaskModel(task_id="t-cascade", status="completed", input="x"))
        await session.commit()

        session.add(ArtifactModel(
            task_id="t-cascade",
            type="weather",
            agent_name="weather",
            payload={},
        ))
        await session.commit()

        task = await session.get(TaskModel, "t-cascade")
        await session.delete(task)
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(ArtifactModel).where(ArtifactModel.task_id == "t-cascade")
        )
        assert result.scalars().all() == []

    async def test_task_can_have_multiple_artifacts(self, session):
        session.add(TaskModel(task_id="t-multi", status="completed", input="x"))
        await session.commit()

        for agent in ["weather", "hotel", "budget"]:
            session.add(ArtifactModel(
                task_id="t-multi",
                type=agent,
                agent_name=agent,
                payload={"agent": agent},
            ))
        await session.commit()

        from sqlalchemy import select
        result = await session.execute(
            select(ArtifactModel).where(ArtifactModel.task_id == "t-multi")
        )
        artifacts = result.scalars().all()
        assert len(artifacts) == 3


# ── No logger in class bodies ─────────────────────────────────

class TestNoLoggerInClassBodies:

    def test_task_model_has_no_logger_call(self):
        source = inspect.getsource(TaskModel)
        assert "logger.info" not in source
        assert "get_logger"  not in source

    def test_artifact_model_has_no_logger_call(self):
        source = inspect.getsource(ArtifactModel)
        assert "logger.info" not in source
        assert "get_logger"  not in source