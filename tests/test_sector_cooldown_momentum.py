from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from unittest import TestCase


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "backtest_sector_cooldown_momentum.py"
    sys.path.insert(0, str(path.parent))
    spec = spec_from_file_location("sector_cooldown_script", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SectorCooldownMomentumTests(TestCase):
    def test_six_calendar_month_cooldown_preserves_signal_day(self) -> None:
        script = load_script()
        self.assertEqual(script.add_months(date(2026, 1, 20), 6), date(2026, 7, 20))
        self.assertEqual(script.add_months(date(2025, 8, 31), 6), date(2026, 2, 28))

    def test_trade_sort_key_orders_signal_then_execution_then_ticker(self) -> None:
        script = load_script()
        trades = [
            {"signal_date": "2026-02-01", "execution_date": "2026-02-02", "ticker": "ZZZ"},
            {"signal_date": "2026-01-01", "execution_date": "2026-01-03", "ticker": "BBB"},
            {"signal_date": "2026-01-01", "execution_date": "2026-01-03", "ticker": "AAA"},
        ]
        self.assertEqual([row["ticker"] for row in sorted(trades, key=script.trade_sort_key)], ["AAA", "BBB", "ZZZ"])

    def test_dated_mapping_overrides_static_mapping_only_inside_interval(self) -> None:
        script = load_script()
        root = Path(__file__).parents[1]
        resolve, _ = script.load_mapping_resolver(
            root / "config/etf_confirmed_momentum_mapping.csv",
            root / "config/etf_confirmed_momentum_mapping_intervals.csv",
        )
        self.assertEqual(resolve("ARNC", date(2020, 2, 26))["primary_etf"], "ITA.US")
        self.assertEqual(resolve("ARNC", date(2020, 4, 2))["primary_etf"], "XME.US")
        self.assertEqual(resolve("CPRI", date(2018, 7, 26))["status"], "excluded")
