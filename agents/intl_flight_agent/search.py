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

# eSewa Travels international fare calendar endpoint
# Always departs from KTM (Tribhuvan International)
_ESEWA_INTL_URL  = settings.esewa_intl_api
_DEPART_AIRPORT  = "KTM"

# Common international destination IATA codes
_INTL_IATA: dict[str, str] = {
    # Middle East
    "doha":         "DOH",
    "dubai":        "DXB",
    "abu dhabi":    "AUH",
    "riyadh":       "RUH",
    "jeddah":       "JED",
    "kuwait":       "KWI",
    "muscat":       "MCT",
    "bahrain":      "BAH",
    # South / Southeast Asia
    "delhi":        "DEL",
    "new delhi":    "DEL",
    "mumbai":       "BOM",
    "bangalore":    "BLR",
    "kolkata":      "CCU",
    "chennai":      "MAA",
    "bangkok":      "BKK",
    "singapore":    "SIN",
    "kuala lumpur": "KUL",
    "jakarta":      "CGK",
    "manila":       "MNL",
    "colombo":      "CMB",
    "dhaka":        "DAC",
    "karachi":      "KHI",
    "islamabad":    "ISB",
    "lahore":       "LHE",
    # East Asia
    "tokyo":        "NRT",
    "osaka":        "KIX",
    "seoul":        "ICN",
    "beijing":      "PEK",
    "shanghai":     "PVG",
    "hong kong":    "HKG",
    "taipei":       "TPE",
    # Europe
    "london":       "LHR",
    "paris":        "CDG",
    "amsterdam":    "AMS",
    "frankfurt":    "FRA",
    "istanbul":     "IST",
    "zurich":       "ZRH",
    "madrid":       "MAD",
    "rome":         "FCO",
    # Oceania / Americas
    "sydney":       "SYD",
    "melbourne":    "MEL",
    "new york":     "JFK",
    "los angeles":  "LAX",
    "toronto":      "YYZ",
}

intl_flight_agent_card = AgentCard(
    name="intl_flight",
    description="Searches international flights from Kathmandu using eSewa Travels.",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url="http://localhost:8003",
        )
    ],
    skills=[
        AgentSkill(
            id="intl_flight_search",
            name="International Flight Search",
            description="Returns fare calendar for international flights from KTM to a given destination.",
            tags=["flights", "international", "nepal", "ktm", "fare"],
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
)


class IntlFlightExecutor(AgentExecutor):

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

            # Parse: "Find international flights from KTM to Bangkok
            #          from 2026-07-15 to 2026-07-20"
            # Also accepts: "...on 2026-07-15" for single date

            to_idx = lowered.find(" to ")
            if to_idx == -1:
                raise ValueError(f"No destination found in: {instruction!r}")

            # destination is between " to " and the next date keyword
            after_to = instruction[to_idx + 4:]
            lowered_after = after_to.lower()

            # find where the date range starts
            date_markers = [" from ", " on ", " between "]
            dest_end = len(after_to)
            for marker in date_markers:
                idx = lowered_after.find(marker)
                if idx != -1 and idx < dest_end:
                    dest_end = idx

            dest_raw   = after_to[:dest_end].strip()
            date_part  = after_to[dest_end:].strip()

            # parse start_date and end_date from date_part
            date_words = date_part.lower().split()
            dates = [w for w in date_words if len(w) == 10 and w[4] == "-"]

            if len(dates) >= 2:
                start_date, end_date = dates[0], dates[1]
            elif len(dates) == 1:
                start_date = dates[0]
                end_date   = dates[0]
            else:
                raise ValueError(f"No dates found in: {instruction!r}")

            dest_code = _INTL_IATA.get(dest_raw.lower())
            if not dest_code:
                # Try as IATA code directly (3 letters)
                if len(dest_raw) == 3:
                    dest_code = dest_raw.upper()
                else:
                    raise ValueError(f"Unknown international destination: {dest_raw!r}")

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    _ESEWA_INTL_URL,
                    params={
                        "depart_airport": _DEPART_AIRPORT,
                        "dest_airport":   dest_code,
                        "start_date":     start_date,
                        "end_date":       end_date,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()

            payload = {
                "origin":      _DEPART_AIRPORT,
                "destination": dest_code,
                "start_date":  start_date,
                "end_date":    end_date,
                "fares":       raw,
            }

            await event_queue.enqueue_event(
                new_data_artifact_update_event(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    name="intl_flight_result",
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
            logger.error("IntlFlightExecutor failed: %s", e)
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
        "agent":  "Intl Flight Agent",
        "port":   8003,
    })


def create_intl_flight_app() -> Starlette:
    handler = DefaultRequestHandlerV2(
        agent_executor=IntlFlightExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=intl_flight_agent_card,
    )
    routes = []
    routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))
    routes.extend(create_agent_card_routes(intl_flight_agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)