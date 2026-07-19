from datetime import date
from unittest import TestCase

from quantresearch.research.short_proxy import (
    ShortBar, apply_asymmetric_pnl_haircut, select_short_exit,
    select_short_target_exit, short_net_return,
)


class ShortProxyTests(TestCase):
    def test_close_stop_covers_at_next_open(self) -> None:
        result = select_short_exit(
            100,
            (ShortBar(date(2026, 1, 5), 105, 111), ShortBar(date(2026, 1, 6), 120, 118)),
            date(2026, 1, 12),
            0.10,
        )
        self.assertEqual(result.reason, "stop_close_next_open")
        self.assertEqual(result.observed, date(2026, 1, 6))
        self.assertEqual(result.price, 120)

    def test_short_return_includes_borrow_and_both_transaction_costs(self) -> None:
        self.assertAlmostEqual(short_net_return(100, 90, 10, 0.03, 0.001), 100 / 90 - 1 - .03 * 10 / 365.2425 - .002)

    def test_target_is_confirmed_at_close_and_covered_next_open(self) -> None:
        result = select_short_target_exit(100, (
            ShortBar(date(2026, 1, 5), 94, 91), ShortBar(date(2026, 1, 6), 89, 88),
        ), .04, 2)
        self.assertEqual(result.reason, "target_close_next_open")
        self.assertEqual(result.price, 89)

    def test_asymmetric_haircut_reduces_gains_and_enlarges_losses(self) -> None:
        self.assertEqual(apply_asymmetric_pnl_haircut(100), 90)
        self.assertAlmostEqual(apply_asymmetric_pnl_haircut(-100), -110)
