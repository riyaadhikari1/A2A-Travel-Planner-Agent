# tests/gateway/test_app.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from shared.schemas.exceptions import (
    AgentExecutionException,
    AgentUnavailableException,
    CORSViolationException,
    InvalidTaskStateException,
    OrchestratorException,
    TaskNotFoundException,
)


def make_app_with_mocked_lifespan():
    """
    Import the app but bypass lifespan entirely.
    We test exception handlers and middleware in isolation.
    """
    from gateway.app import app
    return app


# ── Exception handlers ────────────────────────────────────────

class TestExceptionHandlers:

    def test_task_not_found_returns_404(self):
        from gateway.app import app
        from fastapi.routing import APIRoute
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.get("/test-task-not-found")
        async def _raise(request: Request):
            raise TaskNotFoundException("task-xyz")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-task-not-found")

        assert response.status_code == 404
        assert "task-xyz" in response.json()["detail"]

    def test_agent_unavailable_returns_503(self):
        from gateway.app import app

        @app.get("/test-agent-unavailable")
        async def _raise():
            raise AgentUnavailableException("weather")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-agent-unavailable")

        assert response.status_code == 503
        assert "weather" in response.json()["detail"]

    def test_agent_execution_returns_500(self):
        from gateway.app import app

        @app.get("/test-agent-execution")
        async def _raise():
            raise AgentExecutionException("hotel", "timeout")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-agent-execution")

        assert response.status_code == 500
        assert "hotel"   in response.json()["detail"]
        assert "timeout" in response.json()["detail"]

    def test_invalid_state_returns_409(self):
        from gateway.app import app

        @app.get("/test-invalid-state")
        async def _raise():
            raise InvalidTaskStateException("t1", "queued", "completed")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-invalid-state")

        assert response.status_code == 409

    def test_orchestrator_error_returns_500(self):
        from gateway.app import app

        @app.get("/test-orchestrator")
        async def _raise():
            raise OrchestratorException("planner failed")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-orchestrator")

        assert response.status_code == 500
        assert "planner failed" in response.json()["detail"]

    def test_cors_violation_returns_403(self):
        from gateway.app import app

        @app.get("/test-cors")
        async def _raise():
            raise CORSViolationException("http://evil.com")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-cors")

        assert response.status_code == 403
        assert "http://evil.com" in response.json()["detail"]

    def test_detail_is_not_doubled_with_status_code(self):
        """
        str(HTTPException) returns '404: Task not found'.
        exc.detail returns 'Task not found'.
        This test confirms we use exc.detail not str(exc).
        """
        from gateway.app import app

        @app.get("/test-detail-format")
        async def _raise():
            raise TaskNotFoundException("t-check")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test-detail-format")

        detail = response.json()["detail"]
        assert not detail.startswith("404")
        assert not detail.startswith("404:")


# ── Response format ───────────────────────────────────────────

class TestResponseFormat:

    def test_all_error_responses_have_detail_key(self):
        from gateway.app import app

        exceptions = [
            ("/test-fmt-404", TaskNotFoundException("t1")),
            ("/test-fmt-503", AgentUnavailableException("weather")),
            ("/test-fmt-500", OrchestratorException("reason")),
        ]

        for path, exc in exceptions:
            captured = exc

            @app.get(path)
            async def _raise(e=captured):
                raise e

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(path)

            assert "detail" in response.json(), f"Missing 'detail' for {path}"
            assert isinstance(response.json()["detail"], str)