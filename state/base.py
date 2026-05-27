from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from shared.schemas.task import TaskRecord, TaskStatus


@runtime_checkable
class Store(Protocol):

    async def create(self, task_id: str, user_input: str) -> TaskRecord:
        ...

    async def get(self, task_id: str) -> TaskRecord:
        ...

    async def transition(
        self,
        task_id: str,
        status: TaskStatus,
    ) -> TaskRecord:
        ...

    async def push_event(
        self,
        task_id: str,
        event: str,
        data: str,
    ) -> None:
        ...

    async def stream_events(
        self,
        task_id: str,
    ) -> AsyncIterator[str]:
        ...