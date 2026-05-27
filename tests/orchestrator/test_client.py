# tests/orchestrator/test_client.py

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock

import httpx

from orchestrator.client import OrchestratorClient
from shared.schemas.task import AgentRequest, AgentResponse
from shared.schemas.exceptions import AgentUnavailableException, AgentExecutionException


def make_request(name="weather", instruction="Get weather in Bangkok"):
    return AgentRequest(task_id="task-001", instruction=instruction)


def make_stream_response(artifact_payload: dict | None = None, terminal_state: str = "TASK_STATE_COMPLETED"):
    """
    Build a list of fake protobuf-like dicts that MessageToDict would return.
    We patch MessageToDict to return these directly.
    """
    responses = []

    if artifact_payload is not None:
        responses.append({
            "artifactUpdate": {
                "artifact": {
                    "parts": [{"data": artifact_payload}]
                }
            }
        })

    responses.append({
        "statusUpdate": {
            "status": {"state": terminal_state}
        }
    })

    return responses


async def fake_send_message(stream_responses):
    """Async generator that yields pre-built response dicts."""
    for r in stream_responses:
        yield r


# ── Happy path ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCallAgentSuccess:

    async def test_returns_agent_response(self):
        client = OrchestratorClient()
        payload = {"temperature": 32, "location": "Bangkok"}

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(
            return_value=fake_send_message(make_stream_response(payload))
        )
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "weather",
                "http://localhost:8001",
                make_request(),
            )

        assert isinstance(result, AgentResponse)
        assert result.agent_name == "weather"

    async def test_artifact_payload_extracted(self):
        client = OrchestratorClient()
        payload = {"temperature": 32, "location": "Bangkok"}

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(
            return_value=fake_send_message(make_stream_response(payload))
        )
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "weather",
                "http://localhost:8001",
                make_request(),
            )

        assert result.artifact.payload == payload

    async def test_artifact_type_matches_agent_name(self):
        client = OrchestratorClient()
        payload = {"offers": []}

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(
            return_value=fake_send_message(make_stream_response(payload))
        )
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "domestic_flight",
                "http://localhost:8002",
                make_request("domestic_flight", "Find flights from KTM to PKR on 2026-07-15 for 1 adult economy"),
            )

        assert str(result.artifact.artifact_type) == "domestic_flight"

    async def test_duration_ms_is_non_negative(self):
        client = OrchestratorClient()

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(
            return_value=fake_send_message(make_stream_response({"k": "v"}))
        )
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "weather", "http://localhost:8001", make_request()
            )

        assert result.duration_ms >= 0

    async def test_empty_artifact_payload_returns_empty_dict(self):
        """Stream with no artifactUpdate should yield an empty payload, not crash."""
        client = OrchestratorClient()

        # Only a terminal status, no artifact
        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(
            return_value=fake_send_message(make_stream_response(artifact_payload=None))
        )
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "weather", "http://localhost:8001", make_request()
            )

        assert result.artifact.payload == {}

    async def test_stream_breaks_on_completed_state(self):
        """Verify iteration stops at TASK_STATE_COMPLETED and does not hang."""
        client = OrchestratorClient()
        items_consumed = 0

        async def counting_stream():
            nonlocal items_consumed
            # Increment BEFORE yield so the count reflects items actually consumed
            items_consumed += 1
            yield {"artifactUpdate": {"artifact": {"parts": [{"data": {"x": 1}}]}}}
            items_consumed += 1
            yield {"statusUpdate": {"status": {"state": "TASK_STATE_COMPLETED"}}}
            # Everything after the COMPLETED yield should never be reached
            items_consumed += 1
            yield {"statusUpdate": {"status": {"state": "TASK_STATE_COMPLETED"}}}

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(return_value=counting_stream())
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            await client.call_agent("weather", "http://localhost:8001", make_request())

        # 2 items consumed (artifact + COMPLETED); the 3rd increment never runs
        assert items_consumed == 2

    async def test_all_terminal_states_break_stream(self):
        """FAILED / CANCELED / REJECTED all stop the loop cleanly."""
        client = OrchestratorClient()

        for terminal in ("TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"):
            mock_a2a_client = MagicMock()
            mock_a2a_client.send_message = MagicMock(
                return_value=fake_send_message(make_stream_response(None, terminal))
            )
            mock_a2a_client.close = AsyncMock()

            with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
                 patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

                result = await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

            assert isinstance(result, AgentResponse)

    async def test_json_string_data_is_parsed(self):
        """artifact part.data as a JSON string (not dict) should be parsed."""
        client = OrchestratorClient()
        payload = {"location": "Pokhara"}
        payload_str = json.dumps(payload)

        async def stream_with_string_data():
            yield {
                "artifactUpdate": {
                    "artifact": {
                        "parts": [{"data": payload_str}]
                    }
                }
            }
            yield {"statusUpdate": {"status": {"state": "TASK_STATE_COMPLETED"}}}

        mock_a2a_client = MagicMock()
        mock_a2a_client.send_message = MagicMock(return_value=stream_with_string_data())
        mock_a2a_client.close = AsyncMock()

        with patch("orchestrator.client.create_client", AsyncMock(return_value=mock_a2a_client)), \
             patch("orchestrator.client.MessageToDict", side_effect=lambda msg, **kw: msg):

            result = await client.call_agent(
                "weather", "http://localhost:8001", make_request()
            )

        assert result.artifact.payload == payload


# ── Error handling ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestCallAgentErrors:

    async def test_connect_error_raises_agent_unavailable(self):
        client = OrchestratorClient()

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=httpx.ConnectError("refused"))):
            with pytest.raises(AgentUnavailableException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

    async def test_timeout_raises_agent_unavailable(self):
        client = OrchestratorClient()

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=httpx.TimeoutException("timeout"))):
            with pytest.raises(AgentUnavailableException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

    async def test_http_status_error_raises_agent_execution_exception(self):
        client = OrchestratorClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response)

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=http_error)):
            with pytest.raises(AgentExecutionException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

    async def test_unexpected_exception_raises_agent_execution_exception(self):
        client = OrchestratorClient()

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=RuntimeError("unexpected"))):
            with pytest.raises(AgentExecutionException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

    async def test_agent_unavailable_not_wrapped_again(self):
        """AgentUnavailableException should propagate as-is, not be re-wrapped."""
        client = OrchestratorClient()

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=AgentUnavailableException("weather"))):
            with pytest.raises(AgentUnavailableException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )

    async def test_agent_execution_exception_not_wrapped_again(self):
        """AgentExecutionException should propagate as-is."""
        client = OrchestratorClient()

        with patch("orchestrator.client.create_client", AsyncMock(side_effect=AgentExecutionException("weather", "boom"))):
            with pytest.raises(AgentExecutionException):
                await client.call_agent(
                    "weather", "http://localhost:8001", make_request()
                )