from datetime import date
from unittest import TestCase

from quantresearch.updates.planner import (
    PlanState,
    RefreshMode,
    UpdateTarget,
    plan_updates,
)


def target(
    symbol: str = "AAPL",
    *,
    eligible_from: date = date(1996, 1, 1),
    eligible_to: date | None = None,
    allowed: bool = True,
) -> UpdateTarget:
    return UpdateTarget(
        security_id=f"SEC:{symbol}",
        constituent_symbol=symbol,
        provider_id="TEST_PROVIDER",
        provider_symbol=symbol,
        exchange_code="US",
        eligible_from=eligible_from,
        eligible_to=eligible_to,
        automatic_download_allowed=allowed,
        block_reason=None if allowed else "Pending mapping review",
    )


class UpdatePlannerTests(TestCase):
    def test_incremental_starts_day_after_latest_stored_date(self) -> None:
        plans = plan_updates(
            (target(),),
            latest_stored_dates={("TEST_PROVIDER", "AAPL"): date(2026, 7, 10)},
            as_of=date(2026, 7, 17),
            research_start=date(1996, 1, 1),
        )
        self.assertEqual(plans[0].state, PlanState.FETCH)
        self.assertEqual(plans[0].from_date, date(2026, 7, 11))
        self.assertEqual(plans[0].to_date, date(2026, 7, 17))

    def test_same_as_of_rerun_is_up_to_date(self) -> None:
        plans = plan_updates(
            (target(),),
            latest_stored_dates={("TEST_PROVIDER", "AAPL"): date(2026, 7, 17)},
            as_of=date(2026, 7, 17),
            research_start=date(1996, 1, 1),
        )
        self.assertEqual(plans[0].state, PlanState.UP_TO_DATE)
        self.assertIsNone(plans[0].from_date)
        self.assertIsNone(plans[0].to_date)

    def test_new_symbol_starts_at_later_of_research_and_eligibility(self) -> None:
        plans = plan_updates(
            (target(eligible_from=date(2020, 5, 1)),),
            latest_stored_dates={},
            as_of=date(2020, 5, 31),
            research_start=date(2015, 1, 1),
        )
        self.assertEqual(plans[0].from_date, date(2020, 5, 1))

    def test_target_end_caps_fetch_range(self) -> None:
        plans = plan_updates(
            (target(eligible_to=date(2020, 12, 31)),),
            latest_stored_dates={},
            as_of=date(2021, 2, 1),
            research_start=date(2020, 1, 1),
        )
        self.assertEqual(plans[0].to_date, date(2020, 12, 31))

    def test_quarantined_target_never_fetches(self) -> None:
        plans = plan_updates(
            (target(allowed=False),),
            latest_stored_dates={},
            as_of=date(2026, 7, 17),
            research_start=date(1996, 1, 1),
        )
        self.assertEqual(plans[0].state, PlanState.QUARANTINED)
        self.assertIsNone(plans[0].from_date)

    def test_full_refresh_ignores_latest_date_only_when_explicit(self) -> None:
        plans = plan_updates(
            (target(),),
            latest_stored_dates={("TEST_PROVIDER", "AAPL"): date(2026, 7, 10)},
            as_of=date(2026, 7, 17),
            research_start=date(2000, 1, 1),
            mode=RefreshMode.FULL_REFRESH,
        )
        self.assertEqual(plans[0].from_date, date(2000, 1, 1))

    def test_duplicate_provider_targets_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_updates(
                (target(), target()),
                latest_stored_dates={},
                as_of=date(2026, 7, 17),
                research_start=date(1996, 1, 1),
            )

    def test_invalid_as_of_before_research_start_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_updates(
                (target(),),
                latest_stored_dates={},
                as_of=date(1995, 12, 31),
                research_start=date(1996, 1, 1),
            )
