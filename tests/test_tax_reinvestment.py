from __future__ import annotations

import unittest
from datetime import date

from quantresearch.research.tax_reinvestment import (
    TaxReinvestmentConfig,
    TradeTemplate,
    replay_tax_reinvestment,
)


class TaxReinvestmentTests(unittest.TestCase):
    def test_positive_exit_is_taxed_and_reinvested_at_next_purchase(self) -> None:
        result = replay_tax_reinvestment(
            [
                TradeTemplate("jan", "AAA", date(2016, 1, 4), date(2016, 1, 20), 0.50, "exit"),
                TradeTemplate("feb", "BBB", date(2016, 2, 4), date(2016, 2, 20), 0.00, "exit"),
            ],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 2, 29)),
        )

        self.assertAlmostEqual(result.trades[0].allocated_capital, 10_000.0)
        self.assertAlmostEqual(result.trades[0].tax_paid, 1_750.0)
        self.assertAlmostEqual(result.trades[0].after_tax_proceeds, 13_250.0)
        self.assertAlmostEqual(result.trades[1].allocated_capital, 23_250.0)
        self.assertAlmostEqual(result.ending_after_tax_wealth, 23_250.0)
        self.assertAlmostEqual(result.total_contributions, 20_000.0)

    def test_loss_gets_no_tax_credit(self) -> None:
        result = replay_tax_reinvestment(
            [TradeTemplate("loss", "AAA", date(2016, 1, 4), date(2016, 1, 20), -0.20, "stop")],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 1, 31)),
        )

        self.assertEqual(result.trades[0].tax_paid, 0.0)
        self.assertAlmostEqual(result.ending_after_tax_wealth, 8_000.0)

    def test_same_session_exit_is_reused_for_monthly_rollover(self) -> None:
        result = replay_tax_reinvestment(
            [
                TradeTemplate("jan", "AAA", date(2016, 1, 4), date(2016, 2, 4), 0.50, "exit"),
                TradeTemplate("feb", "BBB", date(2016, 2, 4), date(2016, 2, 20), 0.00, "exit"),
            ],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 2, 29)),
        )

        self.assertAlmostEqual(result.trades[1].allocated_capital, 23_250.0)
        self.assertAlmostEqual(result.ending_after_tax_wealth, 23_250.0)

    def test_batch_is_equal_weighted_and_open_gain_has_liquidation_tax(self) -> None:
        result = replay_tax_reinvestment(
            [
                TradeTemplate("a", "AAA", date(2016, 1, 4), None, 0.20, "open"),
                TradeTemplate("b", "BBB", date(2016, 1, 4), None, -0.10, "open"),
            ],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 1, 31)),
        )

        self.assertAlmostEqual(result.trades[0].allocated_capital, 5_000.0)
        self.assertAlmostEqual(result.trades[1].allocated_capital, 5_000.0)
        self.assertAlmostEqual(result.open_market_value, 10_500.0)
        self.assertAlmostEqual(result.hypothetical_liquidation_tax, 175.0)
        self.assertAlmostEqual(result.ending_after_tax_wealth, 10_500.0)
        self.assertAlmostEqual(result.ending_after_liquidation_tax, 10_325.0)

    def test_realized_loss_reduces_prior_tax_reserve(self) -> None:
        result = replay_tax_reinvestment(
            [
                TradeTemplate("gain", "AAA", date(2016, 1, 4), date(2016, 1, 20), 0.50, "exit"),
                TradeTemplate("loss", "BBB", date(2016, 2, 4), date(2016, 2, 20), -0.20, "stop"),
                TradeTemplate("roll", "CCC", date(2016, 3, 4), date(2016, 3, 20), 0.0, "exit"),
            ],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 3, 31)),
        )

        self.assertLess(result.ledger[2].tax_paid, 0.0)
        self.assertAlmostEqual(
            result.total_tax_paid,
            max(result.total_net_profit, 0.0) * 0.35,
        )

    def test_cash_ledger_reconciles(self) -> None:
        result = replay_tax_reinvestment(
            [TradeTemplate("only", "AAA", date(2016, 1, 4), date(2016, 1, 20), 0.10, "exit")],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 1, 31)),
        )

        self.assertAlmostEqual(result.total_tax_paid, 350.0)
        self.assertAlmostEqual(result.ending_cash, 10_650.0)
        self.assertAlmostEqual(result.ending_after_tax_wealth, result.ending_cash)
        self.assertAlmostEqual(
            result.ending_after_tax_wealth,
            result.total_contributions + result.total_net_profit - result.total_tax_paid,
        )

    def test_contributions_stop_and_empty_month_is_skipped(self) -> None:
        result = replay_tax_reinvestment(
            [
                TradeTemplate("jan", "AAA", date(2016, 1, 4), date(2016, 3, 20), 0.0, "exit"),
                TradeTemplate("feb", "BBB", date(2016, 2, 4), date(2016, 2, 20), 0.0, "exit"),
                TradeTemplate("mar", "CCC", date(2016, 3, 4), date(2016, 3, 20), 0.0, "exit"),
            ],
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 3, 31), contribution_months=1),
        )

        self.assertEqual(result.total_contributions, 10_000.0)
        self.assertEqual([trade.ticker for trade in result.trades], ["AAA"])
        self.assertEqual(result.ledger[1].invested, 0.0)
        self.assertEqual(result.ledger[2].invested, 0.0)

    def test_early_loss_proceeds_are_spread_over_remaining_maturity_months(self) -> None:
        monthly_dates = [
            date(2016, month, 4) for month in range(1, 13)
        ]
        templates = [
            TradeTemplate("jan", "AAA", monthly_dates[0], date(2016, 6, 15), -0.30, "stop")
        ] + [
            TradeTemplate(str(month), "BBB", day, None, 0.0, "open")
            for month, day in enumerate(monthly_dates[1:], start=2)
        ]
        result = replay_tax_reinvestment(
            templates,
            TaxReinvestmentConfig(
                10_000.0,
                0.35,
                date(2016, 12, 31),
                contribution_months=1,
                spread_early_exit_to_maturity=True,
            ),
        )

        invested_by_month = {row.event_date.month: row.invested for row in result.ledger[:-1]}
        for month in range(7, 13):
            self.assertAlmostEqual(invested_by_month[month], 7_000.0 / 6)

    def test_twelfth_cycle_maturity_is_reused_on_same_purchase_session(self) -> None:
        purchase_dates = [date(2016, month, 4) for month in range(1, 13)] + [
            date(2017, 1, 4)
        ]
        templates = [
            TradeTemplate("jan16", "AAA", purchase_dates[0], purchase_dates[12], 0.50, "one_year")
        ] + [
            TradeTemplate(str(index), "BBB", day, None, 0.0, "open")
            for index, day in enumerate(purchase_dates[1:], start=2)
        ]
        result = replay_tax_reinvestment(
            templates,
            TaxReinvestmentConfig(
                10_000.0,
                0.35,
                date(2017, 1, 31),
                contribution_months=1,
                spread_early_exit_to_maturity=True,
            ),
        )

        january_2017 = next(
            row for row in result.ledger if row.event_date == date(2017, 1, 4)
        )
        self.assertAlmostEqual(january_2017.exit_proceeds, 13_250.0)
        self.assertAlmostEqual(january_2017.invested, 13_250.0)

    def test_normal_maturity_can_be_smoothed_across_twelve_purchase_cycles(self) -> None:
        purchase_dates = [
            date(year, month, 4)
            for year in (2016, 2017)
            for month in range(1, 13)
        ]
        templates = [
            TradeTemplate("jan16", "AAA", purchase_dates[0], purchase_dates[12], 1.0, "one_year")
        ] + [
            TradeTemplate(str(index), "BBB", day, None, 0.0, "open")
            for index, day in enumerate(purchase_dates[1:], start=2)
        ]
        result = replay_tax_reinvestment(
            templates,
            TaxReinvestmentConfig(
                10_000.0,
                0.35,
                date(2017, 12, 31),
                contribution_months=1,
                spread_early_exit_to_maturity=True,
                maturity_reinvestment_spread_months=12,
            ),
        )

        expected_installment = 16_500.0 / 12
        ledger = {row.event_date: row for row in result.ledger}
        for day in purchase_dates[12:24]:
            self.assertAlmostEqual(ledger[day].invested, expected_installment)

    def test_weekly_holding_period_spreads_early_exit_until_calendar_maturity(self) -> None:
        purchase_dates = [date(2016, month, 4) for month in range(1, 5)]
        templates = [
            TradeTemplate("jan", "AAA", purchase_dates[0], date(2016, 1, 11), -0.30, "stop"),
            *[
                TradeTemplate(str(index), "BBB", day, None, 0.0, "open")
                for index, day in enumerate(purchase_dates[1:], start=2)
            ],
        ]
        result = replay_tax_reinvestment(
            templates,
            TaxReinvestmentConfig(
                10_000.0,
                0.35,
                date(2016, 4, 30),
                contribution_months=1,
                spread_early_exit_to_maturity=True,
                holding_months=None,
                holding_weeks=4,
            ),
        )
        invested = {row.event_date: row.invested for row in result.ledger}
        self.assertAlmostEqual(invested[date(2016, 2, 4)], 7_000.0)
        self.assertAlmostEqual(invested[date(2016, 3, 4)], 0.0)

    def test_holding_months_and_weeks_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            TaxReinvestmentConfig(10_000.0, 0.35, date(2016, 1, 31), holding_weeks=1)


if __name__ == "__main__":
    unittest.main()
