# tests/state/test_memory_store.py

import asyncio
import pytest

from shared.schemas.exceptions import InvalidTaskStateException, TaskNotFoundException
from shared.schemas.task import TaskStatus
from state.memory_store import MemoryStore


@pytest.fixture
def store():
    return MemoryStore()


@pytest.mark.asyncio
class TestMemoryStoreCreate:

    async def test_create_returns_task_record(self, store):
        record = await store.create("t1", "fly to Bangkok")
        assert record.task_id == "t1"
        assert record.input   == "fly to Bangkok"
        assert record.status  == TaskStatus.QUEUED

    async def test_create_sets_queued_status(self, store):
        record = await store.create("t1", "test")
        assert record.status == TaskStatus.QUEUED

    async def test_create_two_tasks_are_independent(self, store):
        r1 = await store.create("t1", "task one")
        r2 = await store.create("t2", "task two")
        assert r1.task_id != r2.task_id
        assert r1.input   != r2.input


@pytest.mark.asyncio
class TestMemoryStoreGet:

    async def test_get_returns_created_task(self, store):
        await store.create("t1", "test")
        record = await store.get("t1")
        assert record.task_id == "t1"

    async def test_get_nonexistent_task_raises(self, store):
        with pytest.raises(TaskNotFoundException):
            await store.get("nonexistent")

    async def test_get_returns_same_object(self, store):
        await store.create("t1", "test")
        r1 = await store.get("t1")
        r2 = await store.get("t1")
        assert r1 is r2


@pytest.mark.asyncio
class TestMemoryStoreTransition:

    async def test_queued_to_running(self, store):
        await store.create("t1", "test")
        record = await store.transition("t1", TaskStatus.RUNNING)
        assert record.status == TaskStatus.RUNNING

    async def test_running_to_completed(self, store):
        await store.create("t1", "test")
        await store.transition("t1", TaskStatus.RUNNING)
        record = await store.transition("t1", TaskStatus.COMPLETED)
        assert record.status == TaskStatus.COMPLETED

    async def test_running_to_failed(self, store):
        await store.create("t1", "test")
        await store.transition("t1", TaskStatus.RUNNING)
        record = await store.transition("t1", TaskStatus.FAILED)
        assert record.status == TaskStatus.FAILED

    async def test_invalid_transition_raises(self, store):
        await store.create("t1", "test")
        with pytest.raises(InvalidTaskStateException):
            await store.transition("t1", TaskStatus.COMPLETED)

    async def test_transition_nonexistent_task_raises(self, store):
        with pytest.raises(TaskNotFoundException):
            await store.transition("nonexistent", TaskStatus.RUNNING)

    async def test_updated_at_changes_after_transition(self, store):
        record = await store.create("t1", "test")
        before = record.updated_at
        await asyncio.sleep(0.01)
        await store.transition("t1", TaskStatus.RUNNING)
        after = await store.get("t1")
        assert after.updated_at >= before


@pytest.mark.asyncio
class TestMemoryStorePushEvent:

    async def test_push_event_does_not_raise(self, store):
        await store.create("t1", "test")
        await store.push_event("t1", "status", "running")

    async def test_push_event_nonexistent_task_raises(self, store):
        with pytest.raises(TaskNotFoundException):
            await store.push_event("nonexistent", "status", "running")

    async def test_event_format_is_sse_compatible(self, store):
        await store.create("t1", "test")
        await store.push_event("t1", "status", "running")
        queue = store._queues["t1"]
        item  = await queue.get()
        assert item.startswith("event:status")
        assert "data:running" in item


@pytest.mark.asyncio
class TestMemoryStoreStreamEvents:

    async def test_stream_yields_pushed_events(self, store):
        await store.create("t1", "test")
        await store.push_event("t1", "status", "running")
        await store.push_event("t1", "status", "completed")

        received = []
        async for item in store.stream_events("t1"):
            received.append(item)
            if "completed" in item:
                break

        assert len(received) >= 1
        assert any("running" in e for e in received)

    async def test_stream_stops_on_terminal_event(self, store):
        await store.create("t1", "test")
        await store.push_event("t1", "status", "running")
        await store.push_event("t1", "status", "completed")

        received = []
        async for item in store.stream_events("t1"):
            received.append(item)

        assert any("completed" in e for e in received)

    async def test_stream_nonexistent_task_raises(self, store):
        with pytest.raises(TaskNotFoundException):
            async for _ in store.stream_events("nonexistent"):
                pass