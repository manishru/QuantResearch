from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import TestCase


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "run_golden_daily_monitor.py"
    spec = spec_from_file_location("golden_daily_monitor", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GoldenDailyMonitorTests(TestCase):
    def test_monthly_engine_runs_only_on_or_after_nominal_day(self) -> None:
        script = load_script()
        self.assertFalse(script.should_run_monthly_decision(date(2026, 8, 3), 26))
        self.assertTrue(script.should_run_monthly_decision(date(2026, 8, 26), 26))

    def test_rotation_decision_requires_an_actual_exit_signal_date(self) -> None:
        script = load_script()
        self.assertFalse(script.should_run_rotation_decision(None, date(2026, 8, 3)))
        self.assertTrue(script.should_run_rotation_decision(date(2026, 7, 2), date(2026, 8, 3)))
