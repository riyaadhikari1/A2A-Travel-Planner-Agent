from collections.abc import AsyncIterator
from datetime import UTC, datetime

import redis.asyncio as aioredis

from shared.config import config_manager, settings
from shared.logging import get_logger
from shared.schemas.exceptions import (
    InvalidTaskStateException,
    TaskNotFoundException,
)
from shared.schemas.task import TaskRecord, TaskStatus
from state.transitions import VALID_TRANSITIONS

logger = get_logger(__name__)


class RedisStore:

    def __init__(self, client: aioredis.Redis) -> None:
        self.client = client
        self.ttl    = settings.redis_ttl

    async def create(self, task_id: str, user_input: str) -> TaskRecord:
        record = TaskRecord(
            task_id=task_id,
            input=user_input,
            status=TaskStatus.QUEUED,
        )
        await self.client.setex(
            f"task:{task_id}", self.ttl, record.model_dump_json()
        )
        logger.info("Created task %s", task_id)
        return record

    async def get(self, task_id: str) -> TaskRecord:
        raw = await self.client.get(f"task:{task_id}")
        if raw is None:
            raise TaskNotFoundException(task_id)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return TaskRecord.model_validate_json(raw)

    async def transition(self, task_id: str, status: TaskStatus) -> TaskRecord:
        record     = await self.get(task_id)
        valid_next = VALID_TRANSITIONS.get(record.status, set())
        if status not in valid_next:
            raise InvalidTaskStateException(
                task_id=task_id,
                current_status=record.status,
                attempted_status=status,
            )
        old_status        = record.status
        record.status     = status
        record.updated_at = datetime.now(UTC)
        await self.client.setex(
            f"task:{task_id}", self.ttl, record.model_dump_json()
        )
        logger.info(
            "Task %s transitioned from %s to %s",
            task_id, old_status, status,
        )
        return record

    async def push_event(self, task_id: str, event: str, data: str) -> None:
        queue_key = f"queue:{task_id}"
        await self.client.rpush(queue_key, f"event:{event}\ndata:{data}\n\n")
        await self.client.expire(queue_key, self.ttl)
        logger.debug("Task %s — pushed event '%s'", task_id, event)

    async def stream_events(self, task_id: str) -> AsyncIterator[str]:
        queue_key       = f"queue:{task_id}"
        terminal_events = set(
            config_manager.load("events").get("terminal_events", [])
        )
        while True:
            result = await self.client.blpop(queue_key, timeout=1)
            if result is None:
                continue
            item = result[1]
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            yield item
            for line in item.split("\n"):
                if line.startswith("data:"):
                    data_value = line.removeprefix("data:").strip()
                    if data_value in terminal_events:
                        return