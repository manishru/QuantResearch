from datetime import UTC, date, datetime
from unittest import TestCase

from quantresearch.domain.exclusions import (
    ExclusionReason,
    ExclusionRegistry,
    ExclusionStatus,
    UniverseExclusion,
)
from quantresearch.domain.membership import MembershipSnapshot
from quantresearch.validation.mapping_coverage import summarize_coverage
from quantresearch.validation.mapping_review import ResolutionReportRow, classify_resolution_rows


class MappingCoverageTests(TestCase):
    def test_approved_formatting_counts_but_pending_identity_does_not(self) -> None:
        review = classify_resolution_rows(
            (
                ResolutionReportRow("BF.B", "BF.B", "BF-B", "SUCCESS"),
                ResolutionReportRow("INFO", "SPGI", "SPGI", "SUCCESS"),
            ),
            effective_from=date(1996, 1, 1),
        )
        snapshots = (
            MembershipSnapshot("SP500", date(2000, 1, 3), frozenset({"BF.B", "INFO"}), 2),
        )
        result = summarize_coverage(
            snapshots,
            available_symbols=frozenset({"BF-B", "SPGI"}),
            registry=review.registry,
            provider_id="EODHD",
        )
        self.assertEqual(result.required_symbols, 2)
        self.assertEqual(result.covered_symbols, 1)
        self.assertEqual(result.mean_coverage, 0.5)
        self.assertEqual(result.excluded_symbols, 0)
        self.assertEqual(result.eligible_coverage, 0.5)

    def test_approved_exclusion_preserves_gross_and_reports_eligible_coverage(self) -> None:
        snapshot = MembershipSnapshot(
            "SP500", date(2000, 1, 3), frozenset({"GOOD", "MISSING"}), 2
        )
        exclusion = UniverseExclusion(
            "SP500", "MISSING", date(1996, 1, 1), None,
            ExclusionReason.PROVIDER_DATA_UNAVAILABLE, "Operator exclusion",
            "operator://decision/1", ExclusionStatus.APPROVED, "operator:test",
            datetime(2026, 7, 13, tzinfo=UTC),
        )
        result = summarize_coverage(
            (snapshot,),
            available_symbols=frozenset({"GOOD"}),
            registry=classify_resolution_rows((), effective_from=date(1996, 1, 1)).registry,
            provider_id="EODHD",
            exclusions=ExclusionRegistry((exclusion,)),
        )
        self.assertEqual(result.mean_coverage, 0.5)
        self.assertEqual(result.excluded_symbols, 1)
        self.assertEqual(result.eligible_coverage, 1.0)
