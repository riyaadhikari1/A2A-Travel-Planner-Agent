import asyncio
from uuid import uuid4

from orchestrator.planner import CLARIFICATION_NEEDED, Planner
from shared.logging import get_logger
from shared.schemas.task import TaskRecord, TaskStatus
from state.base import Store
from state.postgres_store import PostgresStore

logger = get_logger(__name__)


async def create_task(
    user_input: str,
    store: Store,
    postgres_store: PostgresStore,
    planner: Planner,
) -> TaskRecord:
    task_id = str(uuid4())
    logger.info("Creating task %s — input: %.80s", task_id, user_input)
    record  = await store.create(task_id, user_input)
    asyncio.create_task(_run(task_id, store, postgres_store, planner))
    return record


async def _run(
    task_id: str,
    store: Store,
    postgres_store: PostgresStore,
    planner: Planner,
) -> None:
    record = None
    try:
        record = await store.transition(task_id, TaskStatus.RUNNING)
        await store.push_event(task_id, "status", "running")

        result = await planner.plan(record)

        if result == CLARIFICATION_NEEDED:
            logger.info(
                "Task %s — clarification needed.",
                task_id,
            )
            await store.transition(task_id, TaskStatus.FAILED)
            record.status = TaskStatus.FAILED
            await store.push_event(task_id, "status", "clarification_needed")
            await postgres_store.save_completed(record)
            return

        responses = result

        for response in responses:
            await store.push_event(
                task_id,
                "artifact",
                response.artifact.model_dump_json(),
            )
            record.artifacts.append(response.artifact)

        await store.transition(task_id, TaskStatus.COMPLETED)
        record.status = TaskStatus.COMPLETED
        await store.push_event(task_id, "status", "completed")
        await postgres_store.save_completed(record)
        logger.info(
            "Task %s completed — %d artifacts.",
            task_id, len(record.artifacts),
        )

    except Exception as e:
        logger.error("Task %s failed: %s", task_id, e)
        try:
            await store.transition(task_id, TaskStatus.FAILED)
            await store.push_event(task_id, "status", "failed")
            if record is not None:
                record.status = TaskStatus.FAILED
        except Exception as inner:
            logger.error(
                "Failed to mark task %s as failed: %s",
                task_id, inner,
            )