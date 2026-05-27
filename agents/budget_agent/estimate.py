import json
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.helpers.proto_helpers import (
    new_task_from_user_message,
    new_data_artifact_update_event,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from shared.logging import get_logger

logger = get_logger(__name__)

budget_agent_card = AgentCard(
    name="budget",
    description="Estimates trip budget from flight and hotel data.",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url="http://localhost:8005",
        )
    ],
    skills=[
        AgentSkill(
            id="budget_estimate",
            name="Budget Estimator",
            description="Calculates total trip cost from flights and hotels data.",
            tags=["budget", "cost", "estimate", "travel"],
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
)


class BudgetExecutor(AgentExecutor):

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )

        try:
            instruction = context.get_user_input()

            # Extract JSON blob from instruction
            json_start = instruction.find("{")
            data = json.loads(instruction[json_start:]) if json_start != -1 else {}

            dom_flight_data  = data.get("domestic_flight", {})
            intl_flight_data = data.get("intl_flight", {})
            hotel_data       = data.get("hotel", {})
            weather_data     = data.get("weather", {})

            nights    = 3
            trip_days = 3

            # Domestic flight cost estimate
            dom_offers     = dom_flight_data.get("offers", [])
            dom_flight_cost = 50.0 if dom_offers else 0.0    # USD equivalent estimate

            # International flight cost estimate
            intl_fares     = intl_flight_data.get("fares", {})
            intl_has_data  = bool(intl_fares)
            intl_flight_cost = 400.0 if intl_has_data else 0.0

            # Hotel cost estimate
            hotels     = hotel_data.get("hotels", [])
            hotel_cost = 60.0 * nights if hotels else 0.0

            # Daily expenses
            daily_cost = 40.0 * trip_days

            total = dom_flight_cost + intl_flight_cost + hotel_cost + daily_cost

            # Weather summary if available
            weather_summary = None
            if weather_data:
                current = weather_data.get("current", {})
                weather_summary = {
                    "location":    weather_data.get("location"),
                    "temperature": current.get("temperature_2m"),
                    "wind_speed":  current.get("wind_speed_10m"),
                }

            payload = {
                "currency":           "USD",
                "nights":             nights,
                "days":               trip_days,
                "domestic_flight":    dom_flight_cost,
                "intl_flight":        intl_flight_cost,
                "hotel_cost":         hotel_cost,
                "daily_expenses":     daily_cost,
                "total":              total,
                "weather_summary":    weather_summary,
                "dom_flights_found":  len(dom_offers),
                "hotels_found":       len(hotels),
                "notes": (
                    "Flight and hotel costs are estimates. "
                    "Domestic flight ~$50 USD, international ~$400 USD. "
                    "Actual prices may vary."
                ),
            }

            await event_queue.enqueue_event(
                new_data_artifact_update_event(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    name="budget_result",
                    data=payload,
                    media_type="application/json",
                    last_chunk=True,
                )
            )

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                )
            )

        except Exception as e:
            logger.error("BudgetExecutor failed: %s", e)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
                )
            )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        raise Exception("cancel not supported")


async def health_handler(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "healthy",
        "agent":  "Budget Agent",
        "port":   8005,
    })


def create_budget_app() -> Starlette:
    handler = DefaultRequestHandlerV2(
        agent_executor=BudgetExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=budget_agent_card,
    )
    routes = []
    routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))
    routes.extend(create_agent_card_routes(budget_agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)