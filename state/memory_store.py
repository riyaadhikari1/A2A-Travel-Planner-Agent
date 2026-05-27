import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from shared.config import config_manager
from shared.logging import get_logger
from shared.schemas.exceptions import (
    InvalidTaskStateException,
    TaskNotFoundException,
)
from shared.schemas.task import TaskRecord, TaskStatus
from state.transitions import VALID_TRANSITIONS

logger = get_logger(__name__)


class MemoryStore:

    def __init__(self) -> None:
        self._tasks:  dict[str, TaskRecord]        = {}
        self._queues: dict[str, asyncio.Queue[str]] = {}

    async def create(self, task_id: str, user_input: str) -> TaskRecord:
        record = TaskRecord(
            task_id=task_id,
            input=user_input,
            status=TaskStatus.QUEUED,
        )
        self._tasks[task_id]  = record
        self._queues[task_id] = asyncio.Queue()
        logger.info("Created task %s", task_id)
        return record

    async def get(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise TaskNotFoundException(task_id)
        return record

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
        logger.info(
            "Task %s transitioned from %s to %s",
            task_id, old_status, status,
        )
        return record

    async def push_event(self, task_id: str, event: str, data: str) -> None:
        queue = self._queues.get(task_id)
        if queue is None:
            raise TaskNotFoundException(task_id)
        await queue.put(f"event:{event}\ndata:{data}\n\n")
        logger.debug("Task %s — pushed event '%s'", task_id, event)

    async def stream_events(self, task_id: str) -> AsyncIterator[str]:
        queue = self._queues.get(task_id)
        if queue is None:
            raise TaskNotFoundException(task_id)
        terminal_events = set(
            config_manager.load("events").get("terminal_events", [])
        )
        while True:
            item = await queue.get()
            yield item
            for line in item.split("\n"):
                if line.startswith("data:"):
                    data_value = line.removeprefix("data:").strip()
                    if data_value in terminal_events:
                        return