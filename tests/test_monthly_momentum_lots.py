from datetime import date
from unittest import TestCase

from quantresearch.research.monthly_momentum_lots import (
    LotBar,
    scheduled_calendar_date,
    select_lot_exit,
)


class MonthlyMomentumLotTests(TestCase):
    def test_day_31_clamps_to_month_end(self) -> None:
        self.assertEqual(scheduled_calendar_date(2021, 2, 31), date(2021, 2, 28))
        self.assertEqual(scheduled_calendar_date(2020, 2, 31), date(2020, 2, 29))

    def test_gap_through_stop_fills_at_open(self) -> None:
        bars = (LotBar(date(2020, 2, 3), 50, 60, 45, 55),)
        result = select_lot_exit(date(2020, 1, 2), 100, bars, stop_fraction=0.45)
        self.assertEqual(result.reason, "stop_gap")
        self.assertEqual(result.price, 50)

    def test_intraday_stop_precedes_one_year_and_fills_at_stop(self) -> None:
        bars = (
            LotBar(date(2020, 6, 1), 70, 75, 54, 60),
            LotBar(date(2021, 1, 4), 80, 82, 79, 81),
        )
        result = select_lot_exit(date(2020, 1, 2), 100, bars, stop_fraction=0.45)
        self.assertEqual(result.reason, "stop_intraday")
        self.assertAlmostEqual(result.price, 55)

    def test_one_year_exit_uses_first_open_on_or_after_anniversary(self) -> None:
        bars = (
            LotBar(date(2020, 12, 31), 120, 125, 119, 124),
            LotBar(date(2021, 1, 4), 130, 132, 128, 131),
        )
        result = select_lot_exit(date(2020, 1, 3), 100, bars, stop_fraction=0.45)
        self.assertEqual(result.reason, "one_year")
        self.assertEqual(result.date, date(2021, 1, 4))
        self.assertEqual(result.price, 130)

    def test_twelfth_monthly_cycle_can_exit_and_reinvest_before_365_days(self) -> None:
        bars = (
            LotBar(date(2021, 5, 30), 125, 127, 123, 126),
            LotBar(date(2021, 5, 31), 130, 132, 128, 131),
        )
        result = select_lot_exit(
            date(2020, 5, 31),
            100,
            bars,
            stop_fraction=0.45,
            scheduled_maturity_date=date(2021, 5, 30),
        )
        self.assertEqual(result.reason, "one_year")
        self.assertEqual(result.date, date(2021, 5, 30))
        self.assertEqual(result.price, 125)

    def test_monthly_cycle_maturity_must_follow_entry(self) -> None:
        with self.assertRaises(ValueError):
            select_lot_exit(
                date(2020, 5, 31),
                100,
                (),
                stop_fraction=0.45,
                scheduled_maturity_date=date(2020, 5, 31),
            )

    def test_stepwise_profit_trailing_exits_next_open_after_close_breach(self) -> None:
        bars = (
            LotBar(date(2020, 2, 3), 205, 212, 200, 210),
            LotBar(date(2020, 2, 4), 175, 180, 163, 164),
            LotBar(date(2020, 2, 5), 155, 160, 150, 152),
        )
        result = select_lot_exit(
            date(2020, 1, 2),
            100,
            bars,
            stop_fraction=0.45,
            trailing_activation=1.0,
            trailing_initial_floor=0.60,
            trailing_peak_step=0.10,
            trailing_floor_step=0.05,
        )
        self.assertEqual(result.reason, "stepwise_profit_trailing")
        self.assertEqual(result.date, date(2020, 2, 5))
        self.assertEqual(result.price, 155)

    def test_stepwise_trailing_requires_completed_close_at_activation(self) -> None:
        bars = (
            LotBar(date(2020, 2, 3), 190, 205, 180, 195),
            LotBar(date(2020, 2, 4), 170, 175, 158, 159),
            LotBar(date(2021, 1, 4), 165, 170, 160, 168),
        )
        result = select_lot_exit(
            date(2020, 1, 2),
            100,
            bars,
            stop_fraction=0.45,
            trailing_activation=1.0,
            trailing_initial_floor=0.60,
            trailing_peak_step=0.10,
            trailing_floor_step=0.05,
        )
        self.assertEqual(result.reason, "one_year")

    def test_stepwise_trailing_parameters_must_be_ordered(self) -> None:
        with self.assertRaises(ValueError):
            select_lot_exit(
                date(2020, 1, 2),
                100,
                (),
                stop_fraction=0.45,
                trailing_activation=0.60,
                trailing_initial_floor=1.0,
                trailing_peak_step=0.10,
                trailing_floor_step=0.05,
            )
