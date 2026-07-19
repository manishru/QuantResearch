"""Timing utilities for pipeline stages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from types import TracebackType


@dataclass(slots=True)
class Timer:
    """Context manager that records and logs elapsed wall-clock time."""

    label: str
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("quantresearch.timer"))
    elapsed_seconds: float | None = field(default=None, init=False)
    _started_at: float | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> Timer:
        self._started_at = perf_counter()
        self.logger.info("Started: %s", self.label)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._started_at is None:
            raise RuntimeError("Timer exited before it was started")
        self.elapsed_seconds = perf_counter() - self._started_at
        if exc_type is None:
            self.logger.info("Finished: %s (%.3f seconds)", self.label, self.elapsed_seconds)
        else:
            self.logger.exception("Failed: %s (%.3f seconds)", self.label, self.elapsed_seconds)
        return False
