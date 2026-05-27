from collections.abc import AsyncIterator

from shared.logging import get_logger
from state.base import Store

logger = get_logger(__name__)


async def event_stream(task_id: str, store: Store) -> AsyncIterator[bytes]:
    logger.debug("Stream opened for task %s", task_id)
    event_count = 0
    async for item in store.stream_events(task_id):
        event_count += 1
        logger.debug("Task %s — event %d: %.60s", task_id, event_count, item.strip())
        yield item.encode("utf-8")
    logger.debug("Stream closed for task %s — %d events sent", task_id, event_count)