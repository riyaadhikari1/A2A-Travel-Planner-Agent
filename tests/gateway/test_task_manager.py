# tests/gateway/test_task_manager.py

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.schemas.task import TaskRecord, TaskStatus
from shared.schemas.artifact import Artifact
from shared.schemas.exceptions import TaskNotFoundException
from gateway.task_manager import create_task, _run
from orchestrator.planner import CLARIFICATION_NEEDED


def make_store():
    store                   = MagicMock()
    store.create            = AsyncMock()
    store.get               = AsyncMock()
    store.transition        = AsyncMock()
    store.push_event        = AsyncMock()
    store.stream_events     = AsyncMock()
    return store


def make_postgres_store():
    pg                      = MagicMock()
    pg.save_completed       = AsyncMock()
    return pg


def make_planner(result):
    planner                 = MagicMock()
    planner.plan            = AsyncMock(return_value=result)
    return planner


def make_task_record(task_id="t1", status=TaskStatus.QUEUED):
    return TaskRecord(
        task_id=task_id,
        status=status,
        input="fly to Bangkok",
    )


def make_agent_response(agent_name="weather"):
    artifact = Artifact(
        artifact_type=agent_name,
        agent_name=agent_name,
        payload={"temp": 32},
    )
    response             = MagicMock()
    response.artifact    = artifact
    response.agent_name  = agent_name
    response.duration_ms = 100
    return response


# ── create_task ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestCreateTask:

    async def test_returns_task_record(self):
        store    = make_store()
        pg       = make_postgres_store()
        planner  = make_planner([])
        record   = make_task_record()
        store.create.return_value = record

        result = await create_task("fly to Bangkok", store, pg, planner)

        assert result is record

    async def test_calls_store_create(self):
        store    = make_store()
        pg       = make_postgres_store()
        planner  = make_planner([])
        store.create.return_value = make_task_record()

        await create_task("fly to Bangkok", store, pg, planner)

        store.create.assert_called_once()
        call_args = store.create.call_args
        assert call_args[0][1] == "fly to Bangkok"

    async def test_returns_immediately_without_waiting_for_planner(self):
        store   = make_store()
        pg      = make_postgres_store()
        record  = make_task_record()
        store.create.return_value = record

        slow_planner      = MagicMock()
        slow_planner.plan = AsyncMock(side_effect=lambda r: asyncio.sleep(999))

        result = await create_task("test", store, pg, slow_planner)
        assert result is record

        # cancel any pending background tasks to avoid warning
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


# ── _run: success path ────────────────────────────────────────

@pytest.mark.asyncio
class TestRunSuccess:

    async def test_transitions_to_running_then_completed(self):
        store    = make_store()
        pg       = make_postgres_store()
        record   = make_task_record()
        running  = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner  = make_planner([make_agent_response()])

        await _run("t1", store, pg, planner)

        transition_calls = [c[0][1] for c in store.transition.call_args_list]
        assert TaskStatus.RUNNING   in transition_calls
        assert TaskStatus.COMPLETED in transition_calls

    async def test_pushes_running_event(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner([make_agent_response()])

        await _run("t1", store, pg, planner)

        event_calls = [(c[0][1], c[0][2]) for c in store.push_event.call_args_list]
        assert ("status", "running") in event_calls

    async def test_pushes_artifact_for_each_response(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        responses = [
            make_agent_response("weather"),
            make_agent_response("hotel"),
        ]
        planner = make_planner(responses)

        await _run("t1", store, pg, planner)

        artifact_calls = [
            c for c in store.push_event.call_args_list
            if c[0][1] == "artifact"
        ]
        assert len(artifact_calls) == 2

    async def test_pushes_completed_event(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner([make_agent_response()])

        await _run("t1", store, pg, planner)

        event_calls = [(c[0][1], c[0][2]) for c in store.push_event.call_args_list]
        assert ("status", "completed") in event_calls

    async def test_saves_to_postgres_on_completion(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner([make_agent_response()])

        await _run("t1", store, pg, planner)

        pg.save_completed.assert_called_once()


# ── _run: clarification_needed path ──────────────────────────

@pytest.mark.asyncio
class TestRunClarificationNeeded:

    async def test_pushes_clarification_needed_event(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner(CLARIFICATION_NEEDED)

        await _run("t1", store, pg, planner)

        event_calls = [(c[0][1], c[0][2]) for c in store.push_event.call_args_list]
        assert ("status", "clarification_needed") in event_calls

    async def test_transitions_to_failed_on_clarification(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner(CLARIFICATION_NEEDED)

        await _run("t1", store, pg, planner)

        transition_calls = [c[0][1] for c in store.transition.call_args_list]
        assert TaskStatus.FAILED in transition_calls

    async def test_saves_to_postgres_on_clarification(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner(CLARIFICATION_NEEDED)

        await _run("t1", store, pg, planner)

        pg.save_completed.assert_called_once()

    async def test_does_not_push_completed_on_clarification(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = make_planner(CLARIFICATION_NEEDED)

        await _run("t1", store, pg, planner)

        event_calls = [(c[0][1], c[0][2]) for c in store.push_event.call_args_list]
        assert ("status", "completed") not in event_calls


# ── _run: failure path ────────────────────────────────────────

@pytest.mark.asyncio
class TestRunFailure:

    async def test_transitions_to_failed_on_exception(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = MagicMock()
        planner.plan = AsyncMock(side_effect=Exception("planner crashed"))

        await _run("t1", store, pg, planner)

        transition_calls = [c[0][1] for c in store.transition.call_args_list]
        assert TaskStatus.FAILED in transition_calls

    async def test_pushes_failed_event_on_exception(self):
        store   = make_store()
        pg      = make_postgres_store()
        running = make_task_record(status=TaskStatus.RUNNING)
        store.transition.return_value = running
        planner = MagicMock()
        planner.plan = AsyncMock(side_effect=Exception("crash"))

        await _run("t1", store, pg, planner)

        event_calls = [(c[0][1], c[0][2]) for c in store.push_event.call_args_list]
        assert ("status", "failed") in event_calls

    async def test_does_not_raise_to_caller(self):
        store   = make_store()
        pg      = make_postgres_store()
        store.transition.side_effect = Exception("store is down")
        planner = make_planner([])

        await _run("t1", store, pg, planner)

    async def test_unbound_record_does_not_cause_error(self):
        """
        If store.transition(RUNNING) raises, record is never assigned.
        The except block must not crash with UnboundLocalError.
        """
        store   = make_store()
        pg      = make_postgres_store()
        store.transition.side_effect = Exception("Redis down")
        planner = make_planner([])

        await _run("t1", store, pg, planner)

        pg.save_completed.assert_not_called()