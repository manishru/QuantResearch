from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from unittest import TestCase


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "report_golden_rotation_constituent_decision.py"
    sys.path.insert(0, str(path.parent))
    spec = spec_from_file_location("golden_rotation_current_decision", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bars(start: float, end: float, volume: float) -> list[dict]:
    result = []
    for index in range(51):
        price = start + (end - start) * index / 50
        result.append({"date": f"2026-01-{index + 1:02d}" if index < 31 else f"2026-02-{index - 30:02d}", "adjusted_close": price, "volume": volume})
    return result


class GoldenRotationCurrentDecisionTests(TestCase):
    def test_strict_volume_choice_does_not_relax_to_lower_volume_leader(self) -> None:
        script = load_script()
        spy = bars(100, 101, 100)
        price_leader = bars(100, 120, 120)
        volume_leader = bars(100, 118, 320)
        decision = script.screen_leaders(
            universe=["PRICE.US", "VOLUME.US"],
            history={"SPY.US": spy, "PRICE.US": price_leader, "VOLUME.US": volume_leader},
            signal_date=date(2026, 1, 20),
            as_of=date(2026, 2, 20),
            top_n=2,
            minimum_relative_volume=1.0,
            selected_minimum_relative_volume=3.5,
        )
        self.assertEqual([row["etf"] for row in decision["price_leaders"]], ["PRICE.US", "VOLUME.US"])
        self.assertEqual(decision["selected"], [])
        self.assertEqual(decision["reason"], "highest_volume_price_leader_below_strict_floor")
