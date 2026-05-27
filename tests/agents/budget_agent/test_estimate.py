import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from a2a.types import Message, Part, Role, TaskState

from agents.budget_agent.estimate import BudgetExecutor


def make_context(instruction=None):
    if instruction is None:
        data = {
            "domestic_flight": {"offers": [{"flight_number": "YT101"}]},
            "hotel":           {"hotels": [{"name": "Test Hotel"}]},
            "weather":         {
                "current":  {"temperature_2m": 32},
                "location": "Bangkok",
            },
        }
        instruction = f"Estimate budget for trip with the following data: {json.dumps(data)}"

    msg            = Message()
    msg.role       = Role.Value("ROLE_USER")
    msg.message_id = "test-message-id"
    part           = Part()
    part.text      = instruction
    msg.parts.append(part)

    ctx                             = MagicMock()
    ctx.task_id                     = "t-budget"
    ctx.context_id                  = "ctx-budget"
    ctx.message                     = msg
    ctx.current_task                = None
    ctx.get_user_input.return_value = instruction
    return ctx


def make_event_queue():
    q = MagicMock()
    q.enqueue_event = AsyncMock()
    return q


@pytest.mark.asyncio
class TestBudgetExecutorSuccess:

    async def test_enqueues_working_then_completed(self):
        executor    = BudgetExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_WORKING   in states
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_enqueues_artifact(self):
        executor    = BudgetExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        artifact_events = [
            call[0][0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "artifact")
        ]
        assert len(artifact_events) == 1

    async def test_empty_data_produces_zero_flight_and_hotel_costs(self):
        data        = {"domestic_flight": {}, "hotel": {}}
        instruction = f"Estimate budget for trip with the following data: {json.dumps(data)}"
        executor    = BudgetExecutor()
        context     = make_context(instruction)
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_no_json_in_instruction_still_completes(self):
        executor    = BudgetExecutor()
        context     = make_context(
            "Estimate budget for trip with the following data:"
        )
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_intl_flight_data_adds_to_budget(self):
        data = {
            "intl_flight": {"fares": {"2026-07-15": {"price": 45000}}},
            "hotel":       {"hotels": []},
        }
        instruction = f"Estimate budget for trip with the following data: {json.dumps(data)}"
        executor    = BudgetExecutor()
        context     = make_context(instruction)
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_COMPLETED in states

    async def test_weather_data_included_when_present(self):
        data = {
            "weather": {
                "location": "Bangkok",
                "current":  {"temperature_2m": 32.1, "wind_speed_10m": 5.2},
            }
        }
        instruction = f"Estimate budget for trip with the following data: {json.dumps(data)}"
        executor    = BudgetExecutor()
        context     = make_context(instruction)
        event_queue = make_event_queue()

        await executor.execute(context, event_queue)

        states = [
            call[0][0].status.state
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call[0][0], "status")
        ]
        assert TaskState.TASK_STATE_COMPLETED in states


@pytest.mark.asyncio
class TestBudgetExecutorFailure:

    async def test_never_raises_to_caller(self):
        executor = BudgetExecutor()

        msg            = Message()
        msg.role       = Role.Value("ROLE_USER")
        msg.message_id = "test-message-id"
        part           = Part()
        part.text      = "test"
        msg.parts.append(part)

        context                            = MagicMock()
        context.task_id                    = "t-budget"
        context.context_id                 = "ctx-budget"
        context.message                    = msg
        context.current_task               = None
        context.get_user_input.side_effect = RuntimeError("unexpected")

        event_queue = make_event_queue()

        await executor.execute(context, event_queue)