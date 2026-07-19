from datetime import UTC, date, datetime
from pathlib import Path
from unittest import TestCase

from quantresearch.domain.exclusions import (
    ExclusionReason,
    ExclusionRegistry,
    ExclusionStatus,
    UniverseExclusion,
    apply_exclusions,
)
from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot


def exclusion(status: ExclusionStatus = ExclusionStatus.PENDING) -> UniverseExclusion:
    approved = status is ExclusionStatus.APPROVED
    return UniverseExclusion(
        index_id="SP500",
        constituent_symbol="MISSING",
        effective_from=date(1996, 1, 1),
        effective_to=None,
        reason=ExclusionReason.PROVIDER_DATA_UNAVAILABLE,
        rationale="No provider history was resolved; manual review required.",
        evidence_ref="review://ticket/1" if approved else None,
        status=status,
        reviewer="reviewer@example.com" if approved else None,
        reviewed_at=datetime(2026, 7, 13, tzinfo=UTC) if approved else None,
    )


class UniverseExclusionTests(TestCase):
    def test_pending_exclusion_is_not_active(self) -> None:
        registry = ExclusionRegistry((exclusion(),))
        self.assertFalse(registry.is_excluded("SP500", "MISSING", date(2000, 1, 1)))

    def test_approved_exclusion_requires_review_and_evidence(self) -> None:
        with self.assertRaises(ValueError):
            UniverseExclusion(
                index_id="SP500",
                constituent_symbol="MISSING",
                effective_from=date(1996, 1, 1),
                effective_to=None,
                reason=ExclusionReason.PROVIDER_DATA_UNAVAILABLE,
                rationale="Unavailable",
                evidence_ref=None,
                status=ExclusionStatus.APPROVED,
                reviewer=None,
                reviewed_at=None,
            )

    def test_approved_effective_exclusion_is_active(self) -> None:
        registry = ExclusionRegistry((exclusion(ExclusionStatus.APPROVED),))
        self.assertTrue(registry.is_excluded("SP500", "MISSING", date(2000, 1, 1)))

    def test_overlapping_records_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExclusionRegistry((exclusion(), exclusion()))

    def test_apply_exclusions_filters_only_effective_dates_and_versions_output(self) -> None:
        history = MembershipHistory(
            "SP500",
            (
                MembershipSnapshot("SP500", date(1995, 1, 1), frozenset({"MISSING", "OK"}), 2),
                MembershipSnapshot("SP500", date(2000, 1, 1), frozenset({"MISSING", "OK"}), 3),
            ),
            Path("fixture.csv"),
            "a" * 64,
        )
        filtered = apply_exclusions(
            history,
            ExclusionRegistry((exclusion(ExclusionStatus.APPROVED),)),
            decision_sha256="b" * 64,
        )
        self.assertEqual(filtered.snapshots[0].symbols, frozenset({"MISSING", "OK"}))
        self.assertEqual(filtered.snapshots[1].symbols, frozenset({"OK"}))
        self.assertNotEqual(filtered.source_sha256, history.source_sha256)
