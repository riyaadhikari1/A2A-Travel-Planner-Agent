import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.types import Message, Part, Role, TaskState

from agents.weather_agent.forecast import WeatherExecutor


def make_context(instruction="Get weather in Bangkok"):
    msg            = Message()
    msg.role       = Role.Value("ROLE_USER")
    msg.message_id = "test-message-id"
    part           = Part()
    part.text      = instruction
    msg.parts.append(part)

    ctx                             = MagicMock()
    ctx.task_id                     = "t-weather"
    ctx.context_id                  = "ctx-weather"
    ctx.message                     = msg
    ctx.current_task                = None
    ctx.get_user_input.return_value = instruction
    return ctx


def make_event_queue():
    q = MagicMock()
    q.enqueue_event = AsyncMock()
    return q


MOCK_GEO_RESPONSE = {
    "results": [{
        "name":      "Bangkok",
        "latitude":  13.7563,
        "longitude": 100.5018,
    }]
}

MOCK_FORECAST_RESPONSE = {
    "current": {
        "temperature_2m": 32.1,
        "weather_code":   1,
        "wind_speed_10m": 5.2,
    },
    "daily": {
        "temperature_2m_max": [34.0, 33.5, 32.8],
        "temperature_2m_min": [27.0, 26.5, 26.0],
        "weather_code":       [1, 2, 3],
    },
}


def make_mock_http_client(geo=None, forecast=None):
    geo_resp                  = MagicMock()
    geo_resp.json             = MagicMock(return_value=geo or MOCK_GEO_RESPONSE)
    geo_resp.raise_for_status = MagicMock()

    forecast_resp                  = MagicMock()
    forecast_resp.json             = MagicMock(return_value=forecast or MOCK_FORECAST_RESPONSE)
    forecast_resp.raise_for_status = MagicMock()

    client            = AsyncMock()
    client.get        = AsyncMock(side_effect=[geo_resp, forecast_resp])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
class TestWeatherExecutorSuccess:

    async def test_enqueues_working_status(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_WORKING in states

    async def test_enqueues_completed_status(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_enqueues_artifact(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        artifact_events = [
            call[0][0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "artifact")
        ]
        assert len(artifact_events) >= 1

    async def test_artifact_contains_parts(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=make_mock_http_client()):
            await executor.execute(context, event_queue)

        artifact_events = [
            call[0][0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "artifact")
        ]
        assert len(artifact_events) >= 1
        assert len(artifact_events[0].artifact.parts) > 0

    async def test_two_http_calls_made(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()
        mock_client = make_mock_http_client()

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=mock_client):
            await executor.execute(context, event_queue)

        assert mock_client.get.call_count == 2


@pytest.mark.asyncio
class TestWeatherExecutorFailure:

    async def test_no_location_in_instruction_enqueues_failed(self):
        executor    = WeatherExecutor()
        context     = make_context(instruction="Tell me the weather")
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_location_not_found_enqueues_failed(self):
        executor    = WeatherExecutor()
        context     = make_context(instruction="Get weather in Xyz123")
        event_queue = make_event_queue()

        geo_resp                  = MagicMock()
        geo_resp.json             = MagicMock(return_value={"results": []})
        geo_resp.raise_for_status = MagicMock()

        client            = AsyncMock()
        client.get        = AsyncMock(return_value=geo_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_http_error_enqueues_failed(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.get        = AsyncMock(side_effect=Exception("network error"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_FAILED in states

    async def test_never_raises_exception_to_caller(self):
        executor    = WeatherExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        client            = AsyncMock()
        client.get        = AsyncMock(side_effect=RuntimeError("unexpected"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__  = AsyncMock(return_value=False)

        with patch("agents.weather_agent.forecast.httpx.AsyncClient",
                   return_value=client):
            await executor.execute(context, event_queue)