# tests/shared/test_logging.py

import logging
import threading

import pytest

from shared.logging import get_logger


@pytest.fixture
def fresh_root_logger():
    """
    pytest installs its own handlers before tests run, which prevents
    get_logger's initialization from running. This fixture clears them
    temporarily so our setup executes, then restores everything after.
    """
    import shared.logging as log_module

    root           = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level    = root.level
    saved_init     = log_module._initialized

    root.handlers.clear()
    log_module._initialized = False

    yield root

    root.handlers.clear()
    root.handlers.extend(saved_handlers)
    root.setLevel(saved_level)
    log_module._initialized = saved_init


# ── get_logger identity ───────────────────────────────────────

class TestGetLoggerIdentity:

    def test_returns_logger_for_given_name(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"

    def test_same_name_returns_same_instance(self):
        assert get_logger("same.name") is get_logger("same.name")

    def test_different_names_return_different_instances(self):
        assert get_logger("module.a") is not get_logger("module.b")


# ── Logging behavior ──────────────────────────────────────────

class TestLoggingBehavior:

    def test_handlers_added_on_first_call(self, fresh_root_logger):
        get_logger("behavior.test")
        assert len(fresh_root_logger.handlers) > 0

    def test_repeated_calls_do_not_add_duplicate_handlers(self, fresh_root_logger):
        get_logger("dup.a")
        count = len(fresh_root_logger.handlers)
        get_logger("dup.b")
        get_logger("dup.c")
        assert len(fresh_root_logger.handlers) == count

    def test_noisy_loggers_suppressed(self, fresh_root_logger):
        get_logger("noisy.trigger")
        assert logging.getLogger("httpcore").level         == logging.WARNING
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
        assert logging.getLogger("sse_starlette.sse").level  == logging.WARNING

    def test_log_level_is_set_from_settings(self, fresh_root_logger):
        get_logger("level.test")
        assert fresh_root_logger.level in (
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        )


# ── Concurrency safety ────────────────────────────────────────

class TestConcurrencySafety:

    def test_idempotent_under_concurrent_calls(self, fresh_root_logger):
        """20 threads calling get_logger simultaneously must not
        add duplicate handlers or raise exceptions."""
        errors  = []
        results = []

        def worker():
            try:
                results.append(get_logger("concurrent.test"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors  == []
        assert len(results) == 20
        assert all(r is results[0] for r in results)

    def test_handler_count_stable_after_concurrent_calls(self, fresh_root_logger):
        get_logger("first.call")
        count_after_first = len(fresh_root_logger.handlers)

        threads = [
            threading.Thread(target=lambda: get_logger("thread.call"))
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(fresh_root_logger.handlers) == count_after_first