import json

import httpx
from starlette.applications import Starlette

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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = get_logger(__name__)

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL  = "https://api.open-meteo.com/v1/forecast"

weather_agent_card = AgentCard(
    name="weather",
    description="Provides weather forecasts using Open-Meteo.",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url="http://localhost:8001",
        )
    ],
    skills=[
        AgentSkill(
            id="weather_forecast",
            name="Weather Forecast",
            description="Returns current and 3-day forecast for a location.",
            tags=["weather", "forecast", "temperature", "climate"],
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
)


class WeatherExecutor(AgentExecutor):

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Step 1 — create or reuse task, signal working
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

            # parse location from "get weather in <city>"
            location = None
            lowered = instruction.lower()
            if " in " in lowered:
                location = instruction[lowered.index(" in ") + 4:].strip()

            if not location:
                raise ValueError(f"No location parsed from: {instruction!r}")

            async with httpx.AsyncClient(timeout=10.0) as client:

                geo_resp = await client.get(
                    _GEOCODING_URL,
                    params={
                        "name":     location,
                        "count":    1,
                        "language": "en",
                        "format":   "json",
                    },
                )
                geo_resp.raise_for_status()
                results = geo_resp.json().get("results")

                if not results:
                    raise ValueError(f"Location not found: {location!r}")

                lat           = results[0]["latitude"]
                lon           = results[0]["longitude"]
                resolved_name = results[0]["name"]

                forecast_resp = await client.get(
                    _FORECAST_URL,
                    params={
                        "latitude":      lat,
                        "longitude":     lon,
                        "current":       "temperature_2m,weather_code,wind_speed_10m",
                        "daily":         "temperature_2m_max,temperature_2m_min,weather_code",
                        "timezone":      "auto",
                        "forecast_days": 3,
                    },
                )
                forecast_resp.raise_for_status()
                forecast_data = forecast_resp.json()

            payload = {
                "location": resolved_name,
                "latitude": lat,
                "longitude": lon,
                "current":  forecast_data.get("current"),
                "daily":    forecast_data.get("daily"),
            }

            # publish artifact using SDK helper
            await event_queue.enqueue_event(
                new_data_artifact_update_event(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    name="weather_result",
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
            logger.error("WeatherExecutor failed: %s", e)
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
        "agent":  "Weather Agent",   
        "port":   8001,              
    })

def create_weather_app() -> Starlette:
    handler = DefaultRequestHandlerV2(
        agent_executor=WeatherExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=weather_agent_card,
    )
    routes = []
    routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))  
    routes.extend(create_agent_card_routes(weather_agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)