from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from unittest import TestCase


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "backtest_golden_sector_exit_rotation_reinvestment.py"
    sys.path.insert(0, str(path.parent))
    spec = spec_from_file_location("rotation_reinvestment", path)
    assert spec and spec.loader
    module = module_from_spec(spec); spec.loader.exec_module(module)
    return module


def bars(start: float, end: float, volume: float = 100) -> list[dict]:
    result = []
    for i in range(51):
        price = start + (end - start) * i / 50
        result.append({"date": f"2026-01-{i + 1:02d}" if i < 31 else f"2026-02-{i - 30:02d}", "adjusted_close": price, "open": price, "volume": volume})
    return result


class RotationReinvestmentTests(TestCase):
    def test_volume_leader_selects_one_only_when_strict_floor_is_met(self) -> None:
        script = load_script()
        leaders = [(0.08, 1.4, "PRICE.US"), (0.06, 3.2, "VOLUME.US"), (0.04, 2.4, "OTHER.US")]
        self.assertEqual(script.select_rotation_targets(leaders, selection="highest_volume_top_n", top_n=3, selected_minimum_relative_volume=3.0), ["VOLUME.US"])
        self.assertEqual(script.select_rotation_targets(leaders, selection="highest_volume_top_n", top_n=3, selected_minimum_relative_volume=3.5), [])

    def test_cash_maturity_control_never_screens_for_etf_leaders(self) -> None:
        script = load_script()
        item = {"confirmation_date": date(2026, 1, 3), "maturity_date": date(2026, 2, 1)}
        self.assertFalse(script.pending_is_screenable(item, date(2026, 1, 3), daily_until_maturity=False, cash_until_maturity=True))
        self.assertTrue(script.pending_is_screenable(item, date(2026, 1, 3), daily_until_maturity=True, cash_until_maturity=False))

    def test_rotation_leaders_excludes_trigger_and_allows_one(self) -> None:
        script = load_script(); signal, confirm = date(2026, 1, 20), date(2026, 2, 20)
        spy_bars = bars(100, 102); leaders = bars(100, 120, 200); trigger = bars(100, 130, 200); weak = bars(100, 101, 200)
        spy = {row["date"]: float(row["adjusted_close"]) for row in spy_bars}
        found = script.rotation_leaders(universe=["GOOD.US", "TRIGGER.US", "WEAK.US"], etf={"GOOD.US": leaders, "TRIGGER.US": trigger, "WEAK.US": weak}, spy=spy, signal_date=signal, confirmation_date=confirm, exclude_symbol="TRIGGER.US", top_n=3, minimum_relative_volume=1.0)
        self.assertEqual(found, ["GOOD.US"])

    def test_liquidate_overlays_closes_active_lot_once(self) -> None:
        script = load_script(); lots = [{"etf": "X.US", "shares": 10.0, "allocation": 100.0, "active": True}]
        cash, closed = script.liquidate_overlays(overlays=lots, etf={"X.US": [{"date": "2026-01-02", "open": 12.0}]}, observed=date(2026, 1, 2), cost=.0)
        self.assertEqual(cash, 120.0); self.assertEqual(len(closed), 1); self.assertFalse(lots[0]["active"])
        cash_again, closed_again = script.liquidate_overlays(overlays=lots, etf={"X.US": [{"date": "2026-01-02", "open": 12.0}]}, observed=date(2026, 1, 2), cost=.0)
        self.assertEqual((cash_again, closed_again), (0.0, []))
