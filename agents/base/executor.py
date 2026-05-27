from abc import abstractmethod

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import TaskState, TaskStatus, TaskStatusUpdateEvent

from shared.config import config_manager
from shared.logging import get_logger


class BaseExecutor(AgentExecutor):

    PROMPT_KEY: str | None = None

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__module__)
        self.prompt: dict = {}

        if self.PROMPT_KEY is not None:
            self.prompt = config_manager.load(self.PROMPT_KEY)

        self.logger.info(
            "Initialized %s with prompt_key=%s",
            self.__class__.__name__,
            self.PROMPT_KEY,
        )

    @abstractmethod
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None: ...

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        self.logger.warning(
            "Cancel requested for task %s — not supported.",
            context.task_id,
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )
        self.logger.info(
            "Task %s marked as canceled.",
            context.task_id,
        )