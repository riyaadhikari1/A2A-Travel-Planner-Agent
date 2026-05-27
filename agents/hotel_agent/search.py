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

# Serper.dev Google Search API — used to find hotels
_SERPER_URL = "https://google.serper.dev/search"

hotel_agent_card = AgentCard(
    name="hotel",
    description="Searches for hotels using Serper (Google Search).",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            url="http://localhost:8004",
        )
    ],
    skills=[
        AgentSkill(
            id="hotel_search",
            name="Hotel Search",
            description="Returns hotels in a given city with names, ratings, and links.",
            tags=["hotels", "accommodation", "travel", "lodging"],
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
)


def _parse_hotels_from_serper(results: dict) -> list[dict]:
    """
    Extract hotel information from Serper organic search results.
    Returns a list of dicts with name, snippet, link, position.
    """
    hotels = []

    # organic results often contain hotel names + prices from booking sites
    for item in results.get("organic", []):
        name    = item.get("title", "").strip()
        snippet = item.get("snippet", "").strip()
        link    = item.get("link", "")

        # basic filter: skip results that don't look like hotel listings
        if not name:
            continue

        hotels.append({
            "name":     name,
            "snippet":  snippet,
            "link":     link,
            "position": item.get("position", 0),
        })

    # Also check places block if present (Google local results)
    for place in results.get("places", []):
        hotels.append({
            "name":    place.get("title", ""),
            "address": place.get("address", ""),
            "rating":  place.get("rating"),
            "reviews": place.get("ratingCount"),
            "link":    place.get("link", ""),
        })

    return hotels


class HotelExecutor(AgentExecutor):

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
            if not settings.serper_api_key:
                raise ValueError("SERPER_API_KEY not configured")

            instruction = context.get_user_input()
            lowered = instruction.lower()

            # parse city from "find hotels in <city>"
            if " in " not in lowered:
                raise ValueError(f"Cannot parse city from: {instruction!r}")

            city = instruction[lowered.index(" in ") + 4:].strip()

            # build a search query that targets hotel listing pages
            query = f"hotels in {city} booking"

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _SERPER_URL,
                    headers={
                        "X-API-KEY":    settings.serper_api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "q":   query,
                        "num": 10,
                        "gl":  "np",   # geo: Nepal perspective
                        "hl":  "en",
                    },
                )
                resp.raise_for_status()
                raw = resp.json()

            hotels = _parse_hotels_from_serper(raw)

            payload = {
                "city":         city,
                "query":        query,
                "hotels_found": len(hotels),
                "hotels":       hotels,
            }

            await event_queue.enqueue_event(
                new_data_artifact_update_event(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    name="hotel_result",
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
            logger.error("HotelExecutor failed: %s", e)
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
        "agent":  "Hotel Agent",
        "port":   8004,
    })


def create_hotel_app() -> Starlette:
    handler = DefaultRequestHandlerV2(
        agent_executor=HotelExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=hotel_agent_card,
    )
    routes = []
    routes.append(Route("/health", endpoint=health_handler, methods=["GET"]))
    routes.extend(create_agent_card_routes(hotel_agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)