import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shared.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = _PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"

_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

_NOISY_LOGGERS = (
    "a2a.server.events.event_queue_v2",
    "a2a.server.agent_execution.active_task",
    "a2a.server.agent_execution.active_task_registry",
    "a2a.server.tasks.task_manager",
    "a2a.server.tasks.inmemory_task_store",
    "a2a.server.routes.jsonrpc_dispatcher",
    "a2a.utils.telemetry",
    "sse_starlette.sse",
    "httpcore",
    "grpc._cython.cygrpc",
    "a2a.client.card_resolver",
    "sqlalchemy.engine",
    "google_genai.models",
    "openai._base_client",
)

_FORMATTER = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

_init_lock = threading.Lock()
_initialized = False


def _is_console_handler(handler: logging.Handler) -> bool:
    return (
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stdout
    )


def _has_console_handler(root: logging.Logger) -> bool:
    return any(_is_console_handler(h) for h in root.handlers)


def _has_rotating_file_handler(root: logging.Logger) -> bool:
    return any(isinstance(h, RotatingFileHandler) for h in root.handlers)


def _configure_root_logger() -> None:
    global _initialized

    if _initialized:
        return

    with _init_lock:
        if _initialized:
            return

        root = logging.getLogger()

        if not _has_console_handler(root):
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(_FORMATTER)
            root.addHandler(console)

        if not _has_rotating_file_handler(root):
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(_FORMATTER)
            root.addHandler(file_handler)

        root.setLevel(settings.log_level.upper())

        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

        _initialized = True


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)