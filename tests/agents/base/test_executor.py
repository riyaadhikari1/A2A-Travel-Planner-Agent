import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.types import TaskState

from agents.base.executor import BaseExecutor


class ConcreteExecutor(BaseExecutor):
    async def execute(self, context, event_queue):
        pass


class ConcreteExecutorWithPrompt(BaseExecutor):
    PROMPT_KEY = "agents"
    async def execute(self, context, event_queue):
        pass


def make_context(task_id="t-001", context_id="ctx-001"):
    ctx            = MagicMock()
    ctx.task_id    = task_id
    ctx.context_id = context_id
    return ctx


def make_event_queue():
    q = MagicMock()
    q.enqueue_event = AsyncMock()
    return q


# ── Initialization ────────────────────────────────────────────

class TestBaseExecutorInit:

    def test_initializes_without_prompt_key(self):
        executor = ConcreteExecutor()
        assert executor.prompt == {}
        assert executor.PROMPT_KEY is None

    def test_logger_is_set(self):
        import logging
        executor = ConcreteExecutor()
        assert isinstance(executor.logger, logging.Logger)

    def test_initializes_with_prompt_key(self):
        executor = ConcreteExecutorWithPrompt()
        assert isinstance(executor.prompt, dict)
        assert executor.prompt != {}

    def test_prompt_key_none_does_not_load_config(self):
        with patch("agents.base.executor.config_manager") as mock_cm:
            ConcreteExecutor()
            mock_cm.load.assert_not_called()

    def test_prompt_key_set_loads_config(self):
        with patch("agents.base.executor.config_manager") as mock_cm:
            mock_cm.load.return_value = {"key": "value"}

            class WithKey(BaseExecutor):
                PROMPT_KEY = "agents"
                async def execute(self, ctx, eq): pass

            executor = WithKey()
            mock_cm.load.assert_called_once_with("agents")
            assert executor.prompt == {"key": "value"}


# ── Cancel behavior ───────────────────────────────────────────

@pytest.mark.asyncio
class TestBaseExecutorCancel:

    async def test_cancel_enqueues_canceled_status(self):
        executor    = ConcreteExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        await executor.cancel(context, event_queue)

        event_queue.enqueue_event.assert_called_once()
        event = event_queue.enqueue_event.call_args[0][0]
        assert event.status.state == TaskState.TASK_STATE_CANCELED

    async def test_cancel_uses_correct_task_id(self):
        executor    = ConcreteExecutor()
        context     = make_context(task_id="specific-task-id")
        event_queue = make_event_queue()

        await executor.cancel(context, event_queue)

        event = event_queue.enqueue_event.call_args[0][0]
        assert event.task_id == "specific-task-id"

    async def test_cancel_uses_correct_context_id(self):
        executor    = ConcreteExecutor()
        context     = make_context(context_id="specific-ctx-id")
        event_queue = make_event_queue()

        await executor.cancel(context, event_queue)

        event = event_queue.enqueue_event.call_args[0][0]
        assert event.context_id == "specific-ctx-id"

    async def test_cancel_does_not_raise(self):
        executor    = ConcreteExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        await executor.cancel(context, event_queue)

    async def test_cancel_enqueues_exactly_one_event(self):
        executor    = ConcreteExecutor()
        context     = make_context()
        event_queue = make_event_queue()

        await executor.cancel(context, event_queue)

        assert event_queue.enqueue_event.call_count == 1


# ── Abstract contract ─────────────────────────────────────────

class TestBaseExecutorAbstractContract:

    def test_cannot_instantiate_without_execute(self):
        with pytest.raises(TypeError):
            BaseExecutor()

    def test_concrete_subclass_is_instantiable(self):
        executor = ConcreteExecutor()
        assert isinstance(executor, BaseExecutor)

    def test_task_updater_not_present(self):
        executor = ConcreteExecutor()
        assert not hasattr(executor, "_make_updater")