import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.types import Message, Part, Role, TaskState

from agents.intl_flight_agent.search import IntlFlightExecutor


def make_context(instruction="Find international flights from KTM to Bangkok from 2026-07-15 to 2026-07-20"):
    msg            = Message()
    msg.role       = Role.Value("ROLE_USER")
    msg.message_id = "test-message-id"
    part           = Part()
    part.text      = instruction
    msg.parts.append(part)

    ctx                             = MagicMock()
    ctx.task_id                     = "t-intl"
    ctx.context_id                  = "ctx-intl"
    ctx.message                     = msg
    ctx.current_task                = None
    ctx.get_user_input.return_value = instruction
    return ctx


def make_event_queue():
    q = MagicMock()
    q.enqueue_event = AsyncMock()
    return q


MOCK_FARE_RESPONSE = {
    "2026-07-15": {"price": 45000, "currency": "NPR"},
    "2026-07-16": {"price": 48000, "currency": "NPR"},
}


def make_mock_http_client(response=None):
    resp                  = MagicMock()
    resp.json             = MagicMock(return_value=response or MOCK_FARE_RESPONSE)
    resp.raise_for_status = MagicMock()

    client            = AsyncMock()
    client.get        = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
class TestIntlFlightExecutorSuccess:

    async def test_enqueues_working_then_completed(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_WORKING   in states
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_enqueues_artifact(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        artifact_events = [
            call[0][0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "artifact")
        ]
        assert len(artifact_events) == 1

    async def test_resolves_bangkok_to_bkk(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["dest_airport"] == "BKK"

    async def test_parses_date_range(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["start_date"] == "2026-07-15"
        assert call_params["end_date"]   == "2026-07-20"

    async def test_origin_always_ktm(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["depart_airport"] == "KTM"

    async def test_single_date_instruction(self):
        executor    = IntlFlightExecutor()
        context     = make_context(
            "Find international flights from KTM to Dubai on 2026-08-01"
        )
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["start_date"] == "2026-08-01"
        assert call_params["end_date"]   == "2026-08-01"


@pytest.mark.asyncio
class TestIntlFlightExecutorFailure:

    async def test_unknown_destination_enqueues_failed(self):
        executor    = IntlFlightExecutor()
        context     = make_context(
            "Find international flights from KTM to Narnia from 2026-07-15 to 2026-07-20"
        )
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_no_dates_enqueues_failed(self):
        executor    = IntlFlightExecutor()
        context     = make_context(
            "Find international flights from KTM to Bangkok"
        )
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_http_error_enqueues_failed(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.get        = AsyncMock(side_effect=Exception("timeout"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_never_raises_to_caller(self):
        executor    = IntlFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.get        = AsyncMock(side_effect=RuntimeError("unexpected"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.intl_flight_agent.search.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)