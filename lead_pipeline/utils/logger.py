"""Logging setup for the pipeline."""

from __future__ import annotations

import logging
import sys


def setup_logger(name: str = "pipeline", level: str = "INFO") -> logging.Logger:
    """Create a consistent console logger."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    for handler in logger.handlers:
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    return logger
