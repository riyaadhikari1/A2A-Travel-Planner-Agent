# tests/state/test_redis_store.py

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from shared.schemas.exceptions import InvalidTaskStateException, TaskNotFoundException
from shared.schemas.task import TaskRecord, TaskStatus
from state.redis_store import RedisStore


def make_mock_redis():
    client         = AsyncMock()
    client.setex   = AsyncMock(return_value=True)
    client.get     = AsyncMock(return_value=None)
    client.rpush   = AsyncMock(return_value=1)
    client.expire  = AsyncMock(return_value=True)
    client.blpop   = AsyncMock(return_value=None)
    return client


def make_stored_record(task_id: str = "t1", status: TaskStatus = TaskStatus.QUEUED) -> str:
    record = TaskRecord(task_id=task_id, input="test input", status=status)
    return record.model_dump_json()


@pytest.fixture
def redis_client():
    return make_mock_redis()


@pytest.fixture
def store(redis_client):
    return RedisStore(client=redis_client)


@pytest.mark.asyncio
class TestRedisStoreCreate:

    async def test_create_returns_task_record(self, store):
        record = await store.create("t1", "fly to Bangkok")
        assert record.task_id == "t1"
        assert record.input   == "fly to Bangkok"
        assert record.status  == TaskStatus.QUEUED

    async def test_create_writes_to_redis(self, store, redis_client):
        await store.create("t1", "test")
        redis_client.setex.assert_called_once()
        call_args = redis_client.setex.call_args
        assert "task:t1" in str(call_args)

    async def test_create_sets_ttl(self, store, redis_client):
        await store.create("t1", "test")
        call_args = redis_client.setex.call_args[0]
        assert call_args[1] == store.ttl


@pytest.mark.asyncio
class TestRedisStoreGet:

    async def test_get_returns_task_when_found(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1").encode()
        record = await store.get("t1")
        assert record.task_id == "t1"

    async def test_get_raises_when_not_found(self, store, redis_client):
        redis_client.get.return_value = None
        with pytest.raises(TaskNotFoundException):
            await store.get("nonexistent")

    async def test_get_handles_bytes_response(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1").encode("utf-8")
        record = await store.get("t1")
        assert record.task_id == "t1"

    async def test_get_handles_string_response(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1")
        record = await store.get("t1")
        assert record.task_id == "t1"


@pytest.mark.asyncio
class TestRedisStoreTransition:

    async def test_valid_transition_updates_status(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1", TaskStatus.QUEUED)
        record = await store.transition("t1", TaskStatus.RUNNING)
        assert record.status == TaskStatus.RUNNING

    async def test_valid_transition_writes_back_to_redis(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1", TaskStatus.QUEUED)
        await store.transition("t1", TaskStatus.RUNNING)
        assert redis_client.setex.call_count == 1

    async def test_invalid_transition_raises(self, store, redis_client):
        redis_client.get.return_value = make_stored_record("t1", TaskStatus.QUEUED)
        with pytest.raises(InvalidTaskStateException):
            await store.transition("t1", TaskStatus.COMPLETED)

    async def test_transition_nonexistent_task_raises(self, store, redis_client):
        redis_client.get.return_value = None
        with pytest.raises(TaskNotFoundException):
            await store.transition("nonexistent", TaskStatus.RUNNING)


@pytest.mark.asyncio
class TestRedisStorePushEvent:

    async def test_push_event_writes_to_queue(self, store, redis_client):
        await store.push_event("t1", "status", "running")
        redis_client.rpush.assert_called_once()
        call_args = str(redis_client.rpush.call_args)
        assert "queue:t1" in call_args

    async def test_push_event_resets_ttl(self, store, redis_client):
        await store.push_event("t1", "status", "running")
        redis_client.expire.assert_called_once_with("queue:t1", store.ttl)

    async def test_event_payload_is_sse_formatted(self, store, redis_client):
        await store.push_event("t1", "status", "running")
        payload = redis_client.rpush.call_args[0][1]
        assert "event:status" in payload
        assert "data:running"  in payload


@pytest.mark.asyncio
class TestRedisStoreStreamEvents:

    async def test_stream_yields_events_until_terminal(self, store, redis_client):
        events = [
            (b"queue:t1", b"event:status\ndata:running\n\n"),
            (b"queue:t1", b"event:status\ndata:completed\n\n"),
        ]
        redis_client.blpop.side_effect = events

        received = []
        async for item in store.stream_events("t1"):
            received.append(item)

        assert len(received) == 2
        assert any("running"   in e for e in received)
        assert any("completed" in e for e in received)

    async def test_stream_continues_on_blpop_timeout(self, store, redis_client):
        events = [
            None,
            (b"queue:t1", b"event:status\ndata:completed\n\n"),
        ]
        redis_client.blpop.side_effect = events

        received = []
        async for item in store.stream_events("t1"):
            received.append(item)

        assert len(received) == 1
        assert "completed" in received[0]