"""Logging helpers shared by the collector and the dashboard."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(
    logger_name: str,
    *,
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> logging.Logger:
    """Set up console + rotating file logging and return a named logger.

    Safe to call more than once: existing handlers are reused, not duplicated.
    """
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(fmt)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if log_file:
        path = Path(log_file).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        already_added = any(
            isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", None) == str(path)
            for h in root.handlers
        )
        if not already_added:
            file_handler = RotatingFileHandler(path, maxBytes=1_048_576, backupCount=5)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

    return logging.getLogger(logger_name)


class EventLog:
    """Writes diagnostic events to both the log file and the database.

    The database copy is what the dashboard's "Events" panel shows.
    """

    def __init__(self, logger: logging.Logger, database):
        self.logger = logger
        self.database = database

    def log(
        self,
        level: int,
        source: str,
        event_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.logger.log(level, "%s [%s] %s", source, event_type, message)
        try:
            self.database.insert_event(
                logging.getLevelName(level).lower(), source, event_type, message, details or {}
            )
        except Exception:
            self.logger.exception("Failed to persist event log")
