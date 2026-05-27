# tests/gateway/test_router.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.routing import APIRouter

from shared.schemas.task import TaskRecord, TaskStatus
from shared.schemas.exceptions import TaskNotFoundException


def make_task_record(task_id="t1", status=TaskStatus.QUEUED):
    return TaskRecord(
        task_id=task_id,
        status=status,
        input="fly to Bangkok",
    )


def make_app():
    """Build a minimal FastAPI app with the router mounted and mocked app.state."""
    from gateway.router import router

    app       = FastAPI()
    app.include_router(router)

    store          = MagicMock()
    postgres_store = MagicMock()
    registry       = MagicMock()
    planner        = MagicMock()

    record = make_task_record()

    store.create       = AsyncMock(return_value=record)
    store.get          = AsyncMock(return_value=record)
    store.transition   = AsyncMock(return_value=record)
    store.push_event   = AsyncMock()

    async def _stream(task_id):
        yield "event:status\ndata:running\n\n"
        yield "event:status\ndata:completed\n\n"

    store.stream_events = _stream

    postgres_store.get = AsyncMock(return_value=record)

    registry.get_all   = MagicMock(return_value=[
        {"name": "weather", "url": "http://localhost:8001",
         "description": "Weather", "skills": []}
    ])

    app.state.store          = store
    app.state.postgres_store = postgres_store
    app.state.registry       = registry
    app.state.planner        = planner

    return app, store, postgres_store, registry


# ── /health ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHealthEndpoint:

    async def test_returns_200(self):
        app, *_ = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200

    async def test_returns_healthy_status(self):
        app, *_ = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        assert response.json()["status"] == "healthy"


# ── /agents ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAgentsEndpoint:

    async def test_returns_200(self):
        app, *_ = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/agents")
        assert response.status_code == 200

    async def test_returns_list(self):
        app, *_ = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/agents")
        assert isinstance(response.json(), list)

    async def test_returns_agent_data(self):
        app, *_ = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/agents")
        agents = response.json()
        assert agents[0]["name"] == "weather"


# ── /tasks/send ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestTasksSendEndpoint:

    async def test_returns_200(self):
        app, *_ = make_app()
        with patch("gateway.router.task_manager.create_task",
                   new_callable=AsyncMock,
                   return_value=make_task_record()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/tasks/send", json={"input": "fly to Bangkok"})
        assert response.status_code == 200

    async def test_returns_task_id(self):
        app, *_ = make_app()
        with patch("gateway.router.task_manager.create_task",
                   new_callable=AsyncMock,
                   return_value=make_task_record(task_id="abc-123")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/tasks/send", json={"input": "fly to Bangkok"})
        assert response.json()["task_id"] == "abc-123"

    async def test_returns_status(self):
        app, *_ = make_app()
        with patch("gateway.router.task_manager.create_task",
                   new_callable=AsyncMock,
                   return_value=make_task_record()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/tasks/send", json={"input": "test"})
        assert "status" in response.json()


# ── /tasks/{task_id} ──────────────────────────────────────────

@pytest.mark.asyncio
class TestGetTaskEndpoint:

    async def test_returns_200_for_existing_task(self):
        app, store, *_ = make_app()
        store.get.return_value = make_task_record(task_id="t1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/tasks/t1")
        assert response.status_code == 200

    async def test_returns_task_data(self):
        app, store, *_ = make_app()
        store.get.return_value = make_task_record(task_id="t1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/tasks/t1")
        assert response.json()["task_id"] == "t1"

    async def test_falls_back_to_postgres_when_not_in_store(self):
        app, store, postgres_store, *_ = make_app()
        store.get.side_effect          = TaskNotFoundException("t1")
        postgres_store.get.return_value = make_task_record(task_id="t1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/tasks/t1")
        assert response.status_code == 200
        assert response.json()["task_id"] == "t1"

    async def test_returns_404_when_not_in_either_store(self):
        app, store, postgres_store, *_ = make_app()
        store.get.side_effect           = TaskNotFoundException("t1")
        postgres_store.get.side_effect  = TaskNotFoundException("t1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/tasks/missing")
        assert response.status_code == 404