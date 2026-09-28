"""Safe logging configuration for AURA.

CRITICAL MCP 2.0 REQUIREMENT:
Never write application logs to stdout when running over stdio transport,
as stdout carries JSON-RPC 2.0 protocol frames. All logs go to stderr and
a local log file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from aura.config import get_config

_LOGGING_INITIALIZED = False


def configure_logging(log_file: Path | None = None, level: str | None = None) -> logging.Logger:
    """Configure root and AURA loggers to write exclusively to stderr and file."""
    global _LOGGING_INITIALIZED
    cfg = get_config()
    target_file = log_file or cfg.log_file
    target_level_name = (level or cfg.log_level).upper()
    target_level = getattr(logging, target_level_name, logging.INFO)

    target_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("aura")
    logger.setLevel(target_level)
    logger.propagate = False

    if not _LOGGING_INITIALIZED or not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )

        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setLevel(target_level)
        stderr_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(target_file, encoding="utf-8")
        file_handler.setLevel(target_level)
        file_handler.setFormatter(formatter)

        logger.handlers.clear()
        logger.addHandler(stderr_handler)
        logger.addHandler(file_handler)
        _LOGGING_INITIALIZED = True

    return logger


def get_logger(name: str = "aura") -> logging.Logger:
    """Return a configured child logger under the 'aura' namespace."""
    configure_logging()
    if name == "aura":
        return logging.getLogger("aura")
    return logging.getLogger(f"aura.{name}")
