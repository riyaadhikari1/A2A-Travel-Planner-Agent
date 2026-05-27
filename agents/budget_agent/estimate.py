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

# NPR → USD conversion rate (approximate; update as needed)
_NPR_TO_USD = 0.0075

# Fallback per-night hotel estimate in USD when no price data is available.
# Serper returns Google Search results which do not include structured prices,
# so this is used whenever hotels are found but no price can be extracted.
_HOTEL_FALLBACK_PER_NIGHT_USD = 60.0

# Default daily living expenses per day in USD (meals, transport, misc)
_DAILY_EXPENSES_USD = 40.0

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


def _extract_nights(intl_flight_data: dict, dom_flight_data: dict) -> int:
    """
    Derive trip length in nights from the international flight date range.
    Falls back to 1 for domestic-only trips, or 3 if nothing is available.
    """
    start = intl_flight_data.get("start_date", "")
    end   = intl_flight_data.get("end_date", "")

    if start and end and start != end:
        try:
            from datetime import date
            d0 = date.fromisoformat(start)
            d1 = date.fromisoformat(end)
            nights = (d1 - d0).days
            if nights > 0:
                return nights
        except ValueError:
            pass

    # Domestic-only trip — default to 1 night
    if dom_flight_data.get("offers"):
        return 1

    return 3  # final fallback


def _domestic_flight_cost(dom_flight_data: dict) -> tuple[float, int, str]:
    """
    Return (cost_usd, flights_found, notes).
    Reads the cheapest `fare_npr` from offers[] and converts to USD.
    """
    offers = dom_flight_data.get("offers", [])
    if not offers:
        return 0.0, 0, ""

    fares_usd = []
    for offer in offers:
        raw = offer.get("fare_npr", "")
        try:
            fare_npr = float(str(raw).replace(",", "").strip())
            fares_usd.append(round(fare_npr * _NPR_TO_USD, 2))
        except (ValueError, TypeError):
            pass

    if not fares_usd:
        # Offers exist but fares are unparseable — use a conservative fallback
        logger.warning("Domestic offers found but no parseable fare_npr; using fallback.")
        return 50.0, len(offers), "fare_npr unparseable, used $50 fallback"

    cheapest = min(fares_usd)
    note = f"cheapest of {len(fares_usd)} fares at NPR→USD rate {_NPR_TO_USD}"
    return cheapest, len(offers), note


def _intl_flight_cost(intl_flight_data: dict) -> tuple[float, bool, str]:
    """
    Return (cost_usd, has_data, notes).
    eSewa returns a dict of date→price entries in `fares`.
    We take the minimum available fare across all dates.
    """
    fares = intl_flight_data.get("fares", {})
    if not fares:
        return 0.0, False, ""

    prices: list[float] = []

    if isinstance(fares, dict):
        # Structure: { "2026-07-15": { "price": 450.0, ... }, ... }
        # or flat:   { "2026-07-15": 450.0, ... }
        for value in fares.values():
            if isinstance(value, dict):
                raw = value.get("price") or value.get("fare") or value.get("amount")
            else:
                raw = value
            try:
                prices.append(float(raw))
            except (TypeError, ValueError):
                pass

    elif isinstance(fares, list):
        # Some APIs return a list of fare objects
        for entry in fares:
            if isinstance(entry, dict):
                raw = entry.get("price") or entry.get("fare") or entry.get("amount")
            else:
                raw = entry
            try:
                prices.append(float(raw))
            except (TypeError, ValueError):
                pass

    if prices:
        cheapest = min(prices)
        note = f"cheapest of {len(prices)} fare date(s)"
        return cheapest, True, note

    # fares key exists but structure is unrecognised — use a conservative fallback
    logger.warning("intl fares present but no parseable price found; using fallback.")
    return 400.0, True, "fare structure unrecognised, used $400 fallback"


def _hotel_cost(hotel_data: dict, nights: int) -> tuple[float, int, str]:
    """
    Return (cost_usd, hotels_found, notes).
    Serper (Google Search) results do not carry structured nightly prices,
    so we use _HOTEL_FALLBACK_PER_NIGHT_USD when hotels are present.
    """
    hotels = hotel_data.get("hotels", [])
    if not hotels:
        return 0.0, 0, ""

    cost = round(_HOTEL_FALLBACK_PER_NIGHT_USD * nights, 2)
    note = (
        f"{nights} night(s) × ${_HOTEL_FALLBACK_PER_NIGHT_USD}/night estimate "
        f"(Serper results have no structured price)"
    )
    return cost, len(hotels), note


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

            # Extract JSON blob injected by the planner
            json_start = instruction.find("{")
            data = json.loads(instruction[json_start:]) if json_start != -1 else {}

            dom_flight_data  = data.get("domestic_flight", {})
            intl_flight_data = data.get("intl_flight", {})
            hotel_data       = data.get("hotel", {})
            weather_data     = data.get("weather", {})

            # Derive trip length from actual flight dates
            nights    = _extract_nights(intl_flight_data, dom_flight_data)
            trip_days = max(nights, 1)

            # --- Flight costs (read real prices) ---
            dom_cost,  dom_count,  dom_note  = _domestic_flight_cost(dom_flight_data)
            intl_cost, intl_found, intl_note = _intl_flight_cost(intl_flight_data)

            # --- Hotel cost (estimate per night, Serper has no price data) ---
            hotel_cost, hotel_count, hotel_note = _hotel_cost(hotel_data, nights)

            # --- Daily expenses ---
            daily_cost = round(_DAILY_EXPENSES_USD * trip_days, 2)

            total = round(dom_cost + intl_cost + hotel_cost + daily_cost, 2)

            # --- Weather summary ---
            weather_summary = None
            if weather_data:
                current = weather_data.get("current", {})
                weather_summary = {
                    "location":    weather_data.get("location"),
                    "temperature": current.get("temperature_2m"),
                    "wind_speed":  current.get("wind_speed_10m"),
                }

            # Collect transparency notes
            notes: list[str] = []
            if dom_note:
                notes.append(f"Domestic flight: {dom_note}.")
            if intl_note:
                notes.append(f"International flight: {intl_note}.")
            if hotel_note:
                notes.append(f"Hotel: {hotel_note}.")
            notes.append(
                f"Daily expenses: ${_DAILY_EXPENSES_USD}/day × {trip_days} day(s)."
            )

            payload = {
                "currency":          "USD",
                "nights":            nights,
                "days":              trip_days,
                "domestic_flight":   dom_cost,
                "intl_flight":       intl_cost,
                "hotel_cost":        hotel_cost,
                "daily_expenses":    daily_cost,
                "total":             total,
                "weather_summary":   weather_summary,
                "dom_flights_found": dom_count,
                "intl_fares_found":  intl_found,
                "hotels_found":      hotel_count,
                "notes":             " ".join(notes),
            }

            logger.info(
                "Budget for task %s: dom=$%.2f intl=$%.2f hotel=$%.2f daily=$%.2f → total=$%.2f",
                context.task_id, dom_cost, intl_cost, hotel_cost, daily_cost, total,
            )

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