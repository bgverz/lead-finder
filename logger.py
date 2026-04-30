"""Structured logging setup for the pipeline."""

import logging
import sys
from datetime import datetime


def setup_logger(name: str = "pipeline", level: str = "INFO") -> logging.Logger:
    """Create a structured logger with console output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))

        fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    return logger