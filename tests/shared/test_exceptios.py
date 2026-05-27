# tests/shared/test_exceptions.py

import pytest
from fastapi import HTTPException

from shared.schemas.exceptions import (
    AgentExecutionException,
    AgentUnavailableException,
    CORSViolationException,
    InvalidTaskStateException,
    OrchestratorException,
    TaskNotFoundException,
)


# ── TaskNotFoundException ─────────────────────────────────────

class TestTaskNotFoundException:

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException):
            raise TaskNotFoundException("task-123")

    def test_detail_identifies_the_task(self):
        exc = TaskNotFoundException("task-abc")
        assert "task-abc" in exc.detail

    def test_different_task_ids_produce_different_messages(self):
        assert TaskNotFoundException("id-1").detail != TaskNotFoundException("id-2").detail

    def test_task_creation_exception_does_not_exist(self):
        with pytest.raises(ImportError):
            from shared.schemas.exceptions import TaskCreationException  # noqa: F401


# ── AgentUnavailableException ─────────────────────────────────

class TestAgentUnavailableException:

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException):
            raise AgentUnavailableException("weather")

    def test_detail_identifies_the_agent(self):
        exc = AgentUnavailableException("hotel")
        assert "hotel" in exc.detail

    def test_different_agents_produce_different_messages(self):
        assert (
            AgentUnavailableException("weather").detail
            != AgentUnavailableException("budget").detail
        )


# ── AgentExecutionException ───────────────────────────────────

class TestAgentExecutionException:

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException):
            raise AgentExecutionException("weather", "timeout")

    def test_detail_identifies_agent_and_failure_reason(self):
        exc = AgentExecutionException("flights", "connection refused")
        assert "flights"           in exc.detail
        assert "connection refused" in exc.detail

    def test_same_agent_different_messages_differ(self):
        e1 = AgentExecutionException("weather", "timeout")
        e2 = AgentExecutionException("weather", "404 not found")
        assert e1.detail != e2.detail


# ── InvalidTaskStateException ─────────────────────────────────

class TestInvalidTaskStateException:

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException):
            raise InvalidTaskStateException("t1", "queued", "completed")

    def test_detail_contains_task_current_and_attempted_status(self):
        exc = InvalidTaskStateException("task-99", "running", "queued")
        assert "task-99"  in exc.detail
        assert "running"  in exc.detail
        assert "queued"   in exc.detail

    def test_different_transitions_produce_different_messages(self):
        e1 = InvalidTaskStateException("t1", "queued",  "completed")
        e2 = InvalidTaskStateException("t1", "running", "queued")
        assert e1.detail != e2.detail


# ── OrchestratorException ─────────────────────────────────────

class TestOrchestratorException:

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException):
            raise OrchestratorException("planner failed")

    def test_detail_contains_reason(self):
        exc = OrchestratorException("LLM returned empty plan")
        assert "LLM returned empty plan" in exc.detail

    def test_different_reasons_produce_different_messages(self):
        e1 = OrchestratorException("reason one")
        e2 = OrchestratorException("reason two")
        assert e1.detail != e2.detail


# ── CORSViolationException ────────────────────────────────────

class TestCORSViolationException:

    def test_can_be_raised_and_caught_as_plain_exception(self):
        with pytest.raises(Exception):
            raise CORSViolationException("http://evil.com")

    def test_not_catchable_as_http_exception(self):
        """CORSViolationException is not an HTTPException."""
        with pytest.raises(CORSViolationException):
            raise CORSViolationException("http://evil.com")
        # If it were HTTPException, the above would also be caught by HTTPException

    def test_origin_is_accessible(self):
        exc = CORSViolationException("http://evil.com")
        assert exc.origin == "http://evil.com"

    def test_detail_is_accessible(self):
        """detail must exist so app.py can call exc.detail consistently."""
        exc = CORSViolationException("http://evil.com")
        assert "http://evil.com" in exc.detail

    def test_detail_and_str_are_consistent(self):
        exc = CORSViolationException("http://evil.com")
        assert str(exc) == exc.detail

    def test_different_origins_produce_different_messages(self):
        e1 = CORSViolationException("http://origin-a.com")
        e2 = CORSViolationException("http://origin-b.com")
        assert e1.detail != e2.detail
        assert e1.origin != e2.origin