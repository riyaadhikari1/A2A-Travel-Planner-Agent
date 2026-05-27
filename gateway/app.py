from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database.connection import create_engine, create_session_factory
from database.models import Base
from gateway.router import router
from orchestrator.client import OrchestratorClient
from orchestrator.planner import Planner
from orchestrator.registry import AgentRegistry
from shared.config import settings
from shared.logging import get_logger
from shared.schemas.exceptions import (
    AgentExecutionException,
    AgentUnavailableException,
    CORSViolationException,
    InvalidTaskStateException,
    OrchestratorException,
    TaskNotFoundException,
)
from state.memory_store import MemoryStore
from state.postgres_store import PostgresStore
from state.redis_store import RedisStore


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger = get_logger("gateway")

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured in .env")

    redis_client = None

    if settings.redis_url:
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.ping()
        store = RedisStore(redis_client)
        logger.info("Using RedisStore.")
    else:
        store = MemoryStore()
        logger.info("Using MemoryStore.")

    engine          = create_engine()
    session_factory = create_session_factory(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    postgres_store = PostgresStore(session_factory)

    registry            = AgentRegistry()
    orchestrator_client = OrchestratorClient()
    planner             = Planner(orchestrator_client, registry)

    await registry.resolve_all()

    app.state.store          = store
    app.state.postgres_store = postgres_store
    app.state.registry       = registry
    app.state.planner        = planner

    logger.info("Gateway started.")

    yield

    await registry.close()

    if redis_client:
        await redis_client.aclose()

    await engine.dispose()

    logger.info("Gateway shut down.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(TaskNotFoundException)
async def task_not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": exc.detail},
    )


@app.exception_handler(AgentUnavailableException)
async def agent_unavailable_handler(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": exc.detail},
    )


@app.exception_handler(AgentExecutionException)
async def agent_execution_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": exc.detail},
    )


@app.exception_handler(InvalidTaskStateException)
async def invalid_state_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": exc.detail},
    )


@app.exception_handler(OrchestratorException)
async def orchestrator_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": exc.detail},
    )


@app.exception_handler(CORSViolationException)
async def cors_handler(request, exc):
    return JSONResponse(
        status_code=403,
        content={"detail": exc.detail},
    )


app.include_router(router)