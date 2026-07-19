import unittest
from datetime import date

from quantresearch.features.models import FeatureRow
from quantresearch.simulation.models import Bar
from quantresearch.strategies.supply_demand import SupplyDemandParameters
from quantresearch.strategies.supply_demand_signals import (
    DemandEntryType,
    build_demand_trade_plans,
)


class SupplyDemandTradePlanTests(unittest.TestCase):
    def test_first_revisit_builds_zone_edge_limit_with_stop_and_three_r_target(self) -> None:
        plan = build_demand_trade_plans(
            [_feature()],
            [_bar()],
            SupplyDemandParameters(entry_type="zone_edge"),
        )[0]
        self.assertEqual(plan.entry_type, DemandEntryType.LIMIT)
        self.assertEqual(plan.entry_price, 10)
        self.assertEqual(plan.stop_price, 7.5)
        self.assertEqual(plan.target_price, 17.5)
        self.assertEqual(plan.zone_lower, 8)
        self.assertEqual(plan.zone_upper, 10)
        self.assertEqual(plan.retest_number, 1)
        self.assertEqual(plan.available_after, date(2020, 1, 10))
        self.assertGreater(plan.ranking_score, 0)

    def test_midpoint_and_confirmation_close_have_explicit_order_semantics(self) -> None:
        midpoint = build_demand_trade_plans(
            [_feature()], [_bar()], SupplyDemandParameters(entry_type="midpoint")
        )[0]
        confirmation = build_demand_trade_plans(
            [_feature()],
            [_bar()],
            SupplyDemandParameters(entry_type="confirmation_close"),
        )[0]
        self.assertEqual(midpoint.entry_type, DemandEntryType.LIMIT)
        self.assertEqual(midpoint.entry_price, 9)
        self.assertEqual(confirmation.entry_type, DemandEntryType.NEXT_OPEN_MARKET)
        self.assertEqual(confirmation.entry_price, 9.5)

    def test_supply_events_and_non_revisits_do_not_create_long_plans(self) -> None:
        supply = _feature(demand_revisited=False, supply_revisited=True)
        self.assertEqual(
            build_demand_trade_plans([supply], [_bar()], SupplyDemandParameters()), ()
        )
        self.assertEqual(
            build_demand_trade_plans(
                [_feature(demand_revisited=False)], [_bar()], SupplyDemandParameters()
            ),
            (),
        )

    def test_retest_limit_and_availability_are_enforced(self) -> None:
        second = _feature(demand_retest_count=2.0)
        self.assertEqual(
            build_demand_trade_plans([second], [_bar()], SupplyDemandParameters()), ()
        )
        allowed = build_demand_trade_plans(
            [second], [_bar()], SupplyDemandParameters(maximum_retests=1)
        )
        self.assertEqual(len(allowed), 1)

        future_available = FeatureRow(
            "AAA", date(2020, 1, 10), date(2020, 1, 11), _values()
        )
        self.assertEqual(
            build_demand_trade_plans(
                [future_available], [_bar()], SupplyDemandParameters()
            ),
            (),
        )

    def test_missing_atr_or_bar_is_rejected_not_guessed(self) -> None:
        missing_atr = _feature(atr=None)
        with self.assertRaisesRegex(ValueError, "ATR"):
            build_demand_trade_plans([missing_atr], [_bar()], SupplyDemandParameters())
        with self.assertRaisesRegex(ValueError, "matching bar"):
            build_demand_trade_plans([_feature()], [], SupplyDemandParameters())

    def test_nonpositive_atr_buffer_stop_is_untradable_and_skipped(self) -> None:
        plans = build_demand_trade_plans(
            [_feature()], [_bar()], SupplyDemandParameters(stop_atr_buffer=5.0)
        )
        self.assertEqual(plans, ())


def _feature(**changes: object) -> FeatureRow:
    return FeatureRow("AAA", date(2020, 1, 10), date(2020, 1, 10), _values(**changes))


def _values(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "demand_revisited": True,
        "supply_revisited": False,
        "demand_lower": 8.0,
        "demand_upper": 10.0,
        "demand_base_date": "2020-01-05",
        "demand_retest_count": 1.0,
        "atr": 2.0,
    }
    values.update(changes)
    return values


def _bar() -> Bar:
    return Bar("AAA", date(2020, 1, 10), 10.5, 11, 8.5, 9.5, 1_000)


if __name__ == "__main__":
    unittest.main()
