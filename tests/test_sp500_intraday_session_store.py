"""Unit tests for intraday session classification boundaries."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts/update_eodhd_sp500_intraday.py"
SPEC = importlib.util.spec_from_file_location("sp500_intraday", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SessionClassificationTest(unittest.TestCase):
    def test_worker_partition_is_stable_and_disjoint(self) -> None:
        symbols = ("NVDA", "SNDK", "MSFT", "AAPL", "SOXX")
        assigned = [MODULE.worker_for(symbol, 3) for symbol in symbols]
        self.assertEqual(assigned, [MODULE.worker_for(symbol, 3) for symbol in symbols])
        self.assertTrue(all(0 <= worker < 3 for worker in assigned))

    def test_duckdb_configuration_bounds_memory_and_disables_order_preservation(self) -> None:
        with TemporaryDirectory() as temporary:
            with self.subTest("valid"):
                configuration = MODULE.duckdb_configuration("2GB", 1, Path(temporary))
                self.assertEqual(configuration["memory_limit"], "2GB")
                self.assertEqual(configuration["threads"], "1")
                self.assertEqual(configuration["preserve_insertion_order"], "false")
        with self.subTest("invalid"):
            with TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    MODULE.duckdb_configuration("unlimited", 1, Path(temporary))
    def test_new_york_session_boundaries(self) -> None:
        cases = {
            "2026-07-31T07:59:00+00:00": "off_session",  # 03:59 ET, deliberately outside
            "2026-07-31T08:00:00+00:00": "pre_market",   # 04:00 ET
            "2026-07-31T13:29:00+00:00": "pre_market",   # 09:29 ET
            "2026-07-31T13:30:00+00:00": "regular",      # 09:30 ET
            "2026-07-31T20:00:00+00:00": "after_hours",  # 16:00 ET
            "2026-08-01T00:00:00+00:00": "off_session",  # 20:00 ET
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                _, actual = MODULE.classify_session(datetime.fromisoformat(value).astimezone(timezone.utc))
                self.assertEqual(actual, expected)

    def test_sndk_extended_hours_examples_are_separated(self) -> None:
        # Examples returned by EODHD for SNDK on 2026-07-30.  The UTC offset is
        # EDT (-04:00), so the classification must not depend on the user's
        # Central-time clock.
        cases = {
            "2026-07-30T09:05:00-04:00": "pre_market",
            "2026-07-30T09:30:00-04:00": "regular",
            "2026-07-30T19:59:00-04:00": "after_hours",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                _, actual = MODULE.classify_session(datetime.fromisoformat(value).astimezone(timezone.utc))
                self.assertEqual(actual, expected)
