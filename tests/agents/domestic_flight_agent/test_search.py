import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.types import Message, Part, Role, TaskState

from agents.domestic_flight_agent.search import DomesticFlightExecutor


def make_context(instruction="Find flights from KTM to PKR on 2026-07-15 for 1 adult economy"):
    msg            = Message()
    msg.role       = Role.Value("ROLE_USER")
    msg.message_id = "test-message-id"
    part           = Part()
    part.text      = instruction
    msg.parts.append(part)

    ctx                             = MagicMock()
    ctx.task_id                     = "t-dom"
    ctx.context_id                  = "ctx-dom"
    ctx.message                     = msg
    ctx.current_task                = None
    ctx.get_user_input.return_value = instruction
    return ctx


def make_event_queue():
    q = MagicMock()
    q.enqueue_event = AsyncMock()
    return q


MOCK_FLIGHT_RESPONSE = {
    "data": {
        "outbound": {
            "flightsData": [
                {
                    "Airline":      "YT",
                    "FlightNo":     "101",
                    "Provider":     "Yeti Airlines",
                    "Departure":    "KTM",
                    "DepartureTime":"07:00",
                    "Arrival":      "PKR",
                    "ArrivalTime":  "07:25",
                    "AdultFare":    "4500",
                    "Currency":     "NPR",
                    "AircraftType": "ATR72",
                }
            ]
        }
    }
}


def make_mock_http_client(response=None):
    resp                  = MagicMock()
    resp.json             = MagicMock(return_value=response or MOCK_FLIGHT_RESPONSE)
    resp.raise_for_status = MagicMock()

    client            = AsyncMock()
    client.post       = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
class TestDomesticFlightExecutorSuccess:

    async def test_enqueues_working_then_completed(self):
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
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
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        artifact_events = [
            call[0][0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "artifact")
        ]
        assert len(artifact_events) == 1

    async def test_posts_to_tripturbo_api(self):
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        mock_client.post.assert_called_once()

    async def test_parses_ktm_to_pkr(self):
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["originLocationCode"]      == "KTM"
        assert call_json["destinationLocationCode"] == "PKR"

    async def test_parses_city_names_to_iata(self):
        executor    = DomesticFlightExecutor()
        context     = make_context(
            "Find flights from Kathmandu to Pokhara on 2026-07-15 for 1 adult economy"
        )
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["originLocationCode"]      == "KTM"
        assert call_json["destinationLocationCode"] == "PKR"

    async def test_parses_adult_count(self):
        executor    = DomesticFlightExecutor()
        context     = make_context(
            "Find flights from KTM to PKR on 2026-07-15 for 2 adult economy"
        )
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["adultPassenger"] == 2

    async def test_parses_departure_date(self):
        executor    = DomesticFlightExecutor()
        context     = make_context(
            "Find flights from KTM to PKR on 2026-09-01 for 1 adult economy"
        )
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["departureDate"] == "2026-09-01"


@pytest.mark.asyncio
class TestDomesticFlightExecutorFailure:

    async def test_unparseable_instruction_enqueues_failed(self):
        executor    = DomesticFlightExecutor()
        context     = make_context(instruction="show me flights")
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_unknown_airport_enqueues_failed(self):
        executor    = DomesticFlightExecutor()
        context     = make_context(
            "Find flights from XYZ to ABC on 2026-07-15 for 1 adult economy"
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
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.post       = AsyncMock(side_effect=Exception("network error"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_never_raises_to_caller(self):
        executor    = DomesticFlightExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.post       = AsyncMock(side_effect=RuntimeError("unexpected"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.domestic_flight_agent.search.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)