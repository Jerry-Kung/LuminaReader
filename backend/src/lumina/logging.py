import logging
import sys
from typing import Any


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        parts = [
            f"level={record.levelname}",
            f"logger={record.name}",
            f"message={record.getMessage()}",
        ]
        extras: dict[str, Any] = getattr(record, "extra_fields", {})
        for key, value in extras.items():
            parts.append(f"{key}={value}")
        return " ".join(parts)


def setup_logging(level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    record = logger.makeRecord(logger.name, level, "", 0, message, (), None)
    record.extra_fields = fields
    logger.handle(record)
