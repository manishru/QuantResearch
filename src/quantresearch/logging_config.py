"""Idempotent application logging configuration."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def configure_logging(
    log_dir: Path,
    level: str = "INFO",
    *,
    console: bool = True,
) -> Path:
    """Configure the root logger and return the active log-file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"quantresearch_{datetime.now():%Y-%m-%d}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    return log_file
