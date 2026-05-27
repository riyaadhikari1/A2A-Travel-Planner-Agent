# tests/gateway/test_stream.py

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.stream import event_stream


async def make_store(events: list[str]):
    """Helper — returns a mock store whose stream_events yields the given items."""
    store = MagicMock()

    async def _stream(task_id):
        for event in events:
            yield event

    store.stream_events = _stream
    return store


@pytest.mark.asyncio
class TestEventStream:

    async def test_yields_all_events(self):
        store  = await make_store(["event:status\ndata:running\n\n",
                                   "event:status\ndata:completed\n\n"])
        events = []
        async for item in event_stream("t1", store):
            events.append(item)

        assert len(events) == 2

    async def test_yields_correct_content(self):
        store  = await make_store(["event:artifact\ndata:{}\n\n"])
        events = []
        async for item in event_stream("t1", store):
            events.append(item)

        item = events[0]
        if isinstance(item, bytes):
            item = item.decode("utf-8")
        assert "artifact" in item
        assert "{}" in item

    async def test_empty_store_yields_nothing(self):
        store  = await make_store([])
        events = []
        async for item in event_stream("t1", store):
            events.append(item)

        assert events == []

    async def test_passes_task_id_to_store(self):
        store           = MagicMock()
        received_ids    = []

        async def _stream(task_id):
            received_ids.append(task_id)
            return
            yield  # make it an async generator

        store.stream_events = _stream
        async for _ in event_stream("specific-task-id", store):
            pass

        assert received_ids == ["specific-task-id"]

    async def test_multiple_artifacts_all_yielded(self):
        events_in = [
            "event:status\ndata:running\n\n",
            "event:artifact\ndata:{weather}\n\n",
            "event:artifact\ndata:{hotel}\n\n",
            "event:artifact\ndata:{budget}\n\n",
            "event:status\ndata:completed\n\n",
        ]
        store      = await make_store(events_in)
        events_out = []
        async for item in event_stream("t1", store):
            events_out.append(item)

        assert len(events_out) == 5