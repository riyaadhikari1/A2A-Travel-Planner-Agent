import httpx
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

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)

_DOMESTIC_URL = settings.tripturbo_domestic_api

# IATA codes for Nepal domestic airports
_NEPAL_IATA: dict[str, str] = {
    "kathmandu":  "KTM",
    "ktm":        "KTM",
    "pokhara":    "PKR",
    "pkr":        "PKR",
    "bhairahawa": "BWA",
    "biratnagar": "BIR",
    "janakpur":   "JKR",
    "nepalgunj":  "KEP",
    "dhangadhi":  "DHI",
    "simara":     "SIF",
    "tumlingtar": "TMI",
    "lukla":      "LUA",
    "jomsom":     "JMO",
    "bharatpur":  "BHR",
    "chandragadhi": "BIR",
}

domestic_flight_agent_card = AgentCard(
    name="domestic_flight",
    description="Searches Nepal domestic flight schedules using TripTurbo.",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url="http://localhost:8002",
        )
    ],
    skills=[
        AgentSkill(
            id="domestic_flight_search",
            name="Domestic Flight Search",
            description="Returns available Nepal domestic flights between two cities on a given date.",
            tags=["flights", "domestic", "nepal", "airline", "schedule"],
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
)


class DomesticFlightExecutor(AgentExecutor):

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
            lowered = instruction.lower()

            from_idx = lowered.find(" from ")
            to_idx   = lowered.find(" to ")
            on_idx   = lowered.find(" on ")

            if from_idx == -1 or to_idx == -1 or on_idx == -1:
                raise ValueError(f"Cannot parse flight instruction: {instruction!r}")

            origin_raw  = instruction[from_idx + 6 : to_idx].strip()
            dest_raw    = instruction[to_idx + 4 : on_idx].strip()
            rest        = instruction[on_idx + 4:].strip()

            parts       = rest.split()
            depart_date = parts[0] if parts else ""

            adults = 1
            if "adult" in lowered:
                for i, w in enumerate(lowered.split()):
                    if w == "adult" or w == "adults":
                        try:
                            adults = int(lowered.split()[i - 1])
                        except (ValueError, IndexError):
                            pass

            # Parse seat class
            seat_class = "E"
            if "business" in lowered:
                seat_class = "B"
            elif "first" in lowered:
                seat_class = "F"

            origin_code = _NEPAL_IATA.get(origin_raw.lower())
            dest_code   = _NEPAL_IATA.get(dest_raw.lower())

            if not origin_code:
                raise ValueError(f"Unknown Nepal airport: {origin_raw!r}")
            if not dest_code:
                raise ValueError(f"Unknown Nepal airport: {dest_raw!r}")
            if not depart_date:
                raise ValueError("No departure date found in instruction")

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _DOMESTIC_URL,
                    json={
                        "originLocationCode":      origin_code,
                        "destinationLocationCode": dest_code,
                        "departureDate":           depart_date,
                        "adultPassenger":          adults,
                        "childPassenger":          0,
                        "returnFlight":            False,
                        "seatClass":               seat_class,
                        "nationality":             settings.default_nationality,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()

            outbound    = raw.get("data", {}).get("outbound", {})
            flights_raw = outbound.get("flightsData", [])

            flights = []
            for f in flights_raw[:10]:   
                flights.append({
                    "flight_number":  f.get("Airline", "") + f.get("FlightNo", ""),
                    "airline":        f.get("Provider", ""),
                    "departure":      f.get("Departure", ""),
                    "departure_time": f.get("DepartureTime", ""),
                    "arrival":        f.get("Arrival", ""),
                    "arrival_time":   f.get("ArrivalTime", ""),
                    "fare_npr":       f.get("AdultFare", ""),
                    "currency":       f.get("Currency", "NPR"),
                    "aircraft":       f.get("AircraftType", ""),
                })

            payload = {
                "origin":         origin_code,
                "destination":    dest_code,
                "departure_date": depart_date,
                "seat_class":     seat_class,
                "adults":         adults,
                "flights_found":  len(flights),
                "offers":         flights,
            }

            await event_queue.enqueue_event(
                new_data_artifact_update_event(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    name="domestic_flight_result",
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
            logger.error("DomesticFlightExecutor failed: %s", e)
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
        "agent":  "Domestic Flight Agent",
        "port":   8002,
    })


def create_domestic_flight_app() -> Starlette:
    handler = DefaultRequestHandlerV2(
        agent_executor=DomesticFlightExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=domestic_flight_agent_card,
    )
    routes = []
    routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))
    routes.extend(create_agent_card_routes(domestic_flight_agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)