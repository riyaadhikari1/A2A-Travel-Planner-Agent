from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from pathlib import Path
from fastapi.responses import FileResponse

from gateway import task_manager
from gateway.stream import event_stream
from shared.logging import get_logger
from shared.schemas.exceptions import TaskNotFoundException
from state.postgres_store import PostgresStore

router = APIRouter()
logger = get_logger(__name__)


class TaskRequest(BaseModel):
    input: str


class ChatRequest(BaseModel):
    message: str


@router.get("/health")
async def gateway_health():
    return {"status": "healthy", "service": "Gateway", "port": 8000}


@router.get("/agents")
async def list_agents(request: Request):
    return request.app.state.registry.get_all()


@router.get("/ui")
async def serve_ui():
    ui_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if not ui_path.exists():
        return JSONResponse(status_code=404, content={"detail": "UI not found"})
    return FileResponse(ui_path, media_type="text/html")


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
):
    logger.info("POST /chat — message: %.80s", body.message)
    store          = request.app.state.store
    postgres_store = request.app.state.postgres_store
    planner        = request.app.state.planner

    record = await task_manager.create_task(
        user_input=body.message,
        store=store,
        postgres_store=postgres_store,
        planner=planner,
    )

    return StreamingResponse(
        event_stream(record.task_id, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/send")
async def send_task(
    body: TaskRequest,
    request: Request,
):
    logger.info("POST /tasks/send — input: %.80s", body.input)
    store          = request.app.state.store
    postgres_store = request.app.state.postgres_store
    planner        = request.app.state.planner

    record = await task_manager.create_task(
        user_input=body.input,
        store=store,
        postgres_store=postgres_store,
        planner=planner,
    )

    return {
        "task_id": record.task_id,
        "status":  record.status,
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
):
    store          = request.app.state.store
    postgres_store: PostgresStore = request.app.state.postgres_store

    try:
        record = await store.get(task_id)

    except TaskNotFoundException:
        try:
            record = await postgres_store.get(task_id)

        except TaskNotFoundException:
            return JSONResponse(
                status_code=404,
                content={"detail": "Task not found"},
            )

    return record.model_dump()


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    request: Request,
):
    store = request.app.state.store

    return StreamingResponse(
        event_stream(task_id, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )