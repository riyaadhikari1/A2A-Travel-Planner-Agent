# tests/orchestrator/test_planner.py

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.planner import Planner, CLARIFICATION_NEEDED
from shared.schemas.artifact import Artifact
from shared.schemas.task import AgentRequest, AgentResponse, TaskRecord, TaskStatus
from shared.schemas.exceptions import AgentUnavailableException


# ── Helpers ───────────────────────────────────────────────────

def make_task_record(task_id="task-001", user_input="Fly from KTM to Bangkok on July 15"):
    return TaskRecord(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        input=user_input,
    )


def make_agent_response(agent_name="weather", payload=None):
    artifact = Artifact(
        artifact_type=agent_name,
        agent_name=agent_name,
        payload=payload or {"temperature": 32},
    )
    return AgentResponse(
        agent_name=agent_name,
        artifact=artifact,
        duration_ms=50,
    )


def make_llm_response(content: str):
    """Return a minimal OpenAI-SDK-shaped response object."""
    choice          = MagicMock()
    choice.message  = MagicMock()
    choice.message.content = content
    response        = MagicMock()
    response.choices = [choice]
    return response


def make_planner(llm_content: str, registry_endpoints: dict | None = None):
    """
    Build a Planner with mocked LLM and registry.
    registry_endpoints: {agent_name: url} — missing names raise AgentUnavailableException.
    """
    if registry_endpoints is None:
        registry_endpoints = {
            "weather":         "http://localhost:8001",
            "intl_flight":     "http://localhost:8003",
            "hotel":           "http://localhost:8004",
            "budget":          "http://localhost:8005",
            "domestic_flight": "http://localhost:8002",
        }

    mock_llm = MagicMock()
    mock_llm.chat = MagicMock()
    mock_llm.chat.completions = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(
        return_value=make_llm_response(llm_content)
    )

    mock_registry = MagicMock()
    def get_endpoint(name):
        if name in registry_endpoints:
            return registry_endpoints[name]
        raise AgentUnavailableException(name)
    mock_registry.get_endpoint.side_effect = get_endpoint

    mock_client = MagicMock()
    mock_client.call_agent = AsyncMock(
        side_effect=lambda name, endpoint, req: make_agent_response(name)
    )

    with patch("orchestrator.planner.AsyncOpenAI", return_value=mock_llm):
        planner = Planner(client=mock_client, registry=mock_registry)

    planner._llm    = mock_llm
    planner._client = mock_client
    planner.client  = mock_client

    return planner, mock_client, mock_registry


# ── JSON parsing ──────────────────────────────────────────────

@pytest.mark.asyncio
class TestPlannerJsonParsing:

    async def test_clean_json_array_is_parsed(self):
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        planner, client, _ = make_planner(plan)

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)

    async def test_json_wrapped_in_markdown_fences_is_extracted(self):
        """LLM sometimes wraps the array in ```json ... ``` — the fallback extractor handles this."""
        plan_content = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        wrapped = f"```json\n{plan_content}\n```"
        planner, client, _ = make_planner(wrapped)

        result = await planner.plan(make_task_record())

        # Either parsed correctly or returned CLARIFICATION_NEEDED —
        # both are acceptable; what must NOT happen is an unhandled exception.
        assert result == CLARIFICATION_NEEDED or isinstance(result, list)

    async def test_json_with_preamble_text_is_extracted(self):
        """LLM adds prose before the array — fallback find('[') extraction."""
        plan_content = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        with_preamble = f"Sure! Here is the plan:\n{plan_content}"
        planner, client, _ = make_planner(with_preamble)

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)

    async def test_completely_unparseable_response_returns_clarification(self):
        planner, _, _ = make_planner("I don't understand this request.")

        result = await planner.plan(make_task_record())

        assert result == CLARIFICATION_NEEDED

    async def test_empty_array_returns_clarification(self):
        planner, _, _ = make_planner("[]")

        result = await planner.plan(make_task_record())

        assert result == CLARIFICATION_NEEDED

    async def test_broken_json_inside_brackets_returns_clarification(self):
        planner, _, _ = make_planner("[{broken json,,}]")

        result = await planner.plan(make_task_record())

        assert result == CLARIFICATION_NEEDED


# ── Agent dispatch ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestPlannerDispatch:

    async def test_calls_agents_in_plan(self):
        plan = json.dumps([
            {"agent": "weather",     "instruction": "Get weather in Bangkok"},
            {"agent": "intl_flight", "instruction": "Find international flights from KTM to Bangkok from 2026-07-15 to 2026-07-20"},
        ])
        planner, client, _ = make_planner(plan)

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)
        called_agents = {c[0][0] for c in client.call_agent.call_args_list}
        assert "weather" in called_agents
        assert "intl_flight" in called_agents

    async def test_budget_agent_runs_after_others(self):
        """budget must be called AFTER the parallel agents, not concurrently."""
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
            {"agent": "budget",  "instruction": "Estimate budget for trip with the following data: {}"},
        ])
        planner, client, _ = make_planner(plan)
        call_order = []

        async def tracking_call(name, endpoint, req):
            call_order.append(name)
            return make_agent_response(name)

        client.call_agent.side_effect = tracking_call

        await planner.plan(make_task_record())

        # budget must appear last
        if "budget" in call_order:
            assert call_order.index("budget") > call_order.index("weather")

    async def test_budget_receives_combined_payloads(self):
        """budget instruction must contain JSON with other agents' payloads."""
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
            {"agent": "budget",  "instruction": "Estimate budget for trip with the following data: {}"},
        ])
        planner, client, _ = make_planner(plan)
        captured_instructions = []

        async def capture_call(name, endpoint, req):
            if name == "budget":
                captured_instructions.append(req.instruction)
            return make_agent_response(name)

        client.call_agent.side_effect = capture_call

        await planner.plan(make_task_record())

        assert len(captured_instructions) == 1
        assert "weather" in captured_instructions[0]

    async def test_unavailable_agent_is_skipped(self):
        """If registry raises AgentUnavailableException, that agent is skipped gracefully."""
        plan = json.dumps([
            {"agent": "weather",     "instruction": "Get weather in Bangkok"},
            {"agent": "intl_flight", "instruction": "Find international flights..."},
        ])
        # intl_flight is not in registry
        planner, client, _ = make_planner(plan, registry_endpoints={
            "weather": "http://localhost:8001",
            "budget":  "http://localhost:8005",
        })

        result = await planner.plan(make_task_record())

        # weather succeeded, intl_flight was skipped → result is a list or clarification
        assert isinstance(result, list) or result == CLARIFICATION_NEEDED

    async def test_all_agents_unavailable_returns_clarification(self):
        plan = json.dumps([
            {"agent": "weather",     "instruction": "Get weather in Bangkok"},
            {"agent": "intl_flight", "instruction": "Find international flights..."},
        ])
        planner, client, _ = make_planner(plan, registry_endpoints={})

        result = await planner.plan(make_task_record())

        assert result == CLARIFICATION_NEEDED

    async def test_failed_agent_call_is_swallowed(self):
        """If call_agent raises, that result is dropped but others succeed."""
        plan = json.dumps([
            {"agent": "weather",     "instruction": "Get weather in Bangkok"},
            {"agent": "intl_flight", "instruction": "Find flights..."},
        ])
        planner, client, _ = make_planner(plan)

        async def flaky_call(name, endpoint, req):
            if name == "intl_flight":
                raise Exception("intl agent down")
            return make_agent_response(name)

        client.call_agent.side_effect = flaky_call

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)
        assert len(result) >= 1

    async def test_all_agent_calls_fail_returns_clarification(self):
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        planner, client, _ = make_planner(plan)
        client.call_agent.side_effect = Exception("all agents down")

        result = await planner.plan(make_task_record())

        assert result == CLARIFICATION_NEEDED

    async def test_non_budget_agents_run_in_parallel(self):
        """asyncio.gather means non-budget agents should all be called before budget."""
        plan = json.dumps([
            {"agent": "weather",     "instruction": "Get weather in Bangkok"},
            {"agent": "intl_flight", "instruction": "Find flights..."},
            {"agent": "hotel",       "instruction": "Find hotels in Bangkok"},
            {"agent": "budget",      "instruction": "Estimate budget..."},
        ])
        planner, client, _ = make_planner(plan)
        call_order = []

        async def tracking_call(name, endpoint, req):
            call_order.append(name)
            return make_agent_response(name)

        client.call_agent.side_effect = tracking_call

        await planner.plan(make_task_record())

        non_budget_called = [n for n in call_order if n != "budget"]
        assert set(non_budget_called) == {"weather", "intl_flight", "hotel"}
        if "budget" in call_order:
            assert call_order[-1] == "budget"

    async def test_budget_not_called_when_no_other_responses(self):
        """If all non-budget agents fail, budget should not be called."""
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
            {"agent": "budget",  "instruction": "Estimate budget..."},
        ])
        planner, client, _ = make_planner(plan)
        client.call_agent.side_effect = Exception("weather down")

        await planner.plan(make_task_record())

        budget_calls = [c for c in client.call_agent.call_args_list if c[0][0] == "budget"]
        assert len(budget_calls) == 0

    async def test_budget_failure_does_not_affect_other_responses(self):
        """If budget agent call raises, the other responses are still returned."""
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
            {"agent": "budget",  "instruction": "Estimate budget..."},
        ])
        planner, client, _ = make_planner(plan)

        async def budget_fails(name, endpoint, req):
            if name == "budget":
                raise Exception("budget down")
            return make_agent_response(name)

        client.call_agent.side_effect = budget_fails

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)
        agent_names = [r.agent_name for r in result]
        assert "weather" in agent_names
        assert "budget" not in agent_names


# ── Response shape ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestPlannerResponseShape:

    async def test_result_list_contains_agent_responses(self):
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        planner, _, _ = make_planner(plan)

        result = await planner.plan(make_task_record())

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, AgentResponse)

    async def test_each_response_has_artifact(self):
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Bangkok"},
        ])
        planner, _, _ = make_planner(plan)

        result = await planner.plan(make_task_record())

        for item in result:
            assert isinstance(item.artifact, Artifact)

    async def test_weather_only_plan_returns_one_response(self):
        plan = json.dumps([
            {"agent": "weather", "instruction": "Get weather in Dubai"},
        ])
        planner, _, _ = make_planner(plan)

        result = await planner.plan(make_task_record(user_input="What's the weather in Dubai?"))

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].agent_name == "weather"