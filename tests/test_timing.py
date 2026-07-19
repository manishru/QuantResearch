import logging
from unittest import TestCase

from quantresearch.timing import Timer


class TimerTests(TestCase):
    def test_timer_records_elapsed_time(self) -> None:
        with Timer("test", logger=logging.getLogger("test.timer")) as timer:
            sum(range(100))
        self.assertIsNotNone(timer.elapsed_seconds)
        self.assertGreaterEqual(timer.elapsed_seconds or -1, 0)
