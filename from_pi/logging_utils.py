import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def configure_logging(
    logger_name: str,
    *,
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(fmt)
    has_stream = any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers)
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
        has_same_file = False
        for handler in root_logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                existing = getattr(handler, "baseFilename", None)
                if existing and Path(existing).resolve() == resolved:
                    has_same_file = True
                    handler.setFormatter(formatter)
                    handler.setLevel(level)
                    break
        if not has_same_file:
            file_handler = RotatingFileHandler(resolved, maxBytes=1_048_576, backupCount=5)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

    return logging.getLogger(logger_name)
