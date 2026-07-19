from datetime import UTC, date, datetime
from unittest import TestCase

from quantresearch.domain.mappings import (
    ApprovalStatus,
    MappingRegistry,
    MappingType,
    ProviderSymbolMapping,
    ResolutionState,
    migrate_legacy_mapping,
)
from quantresearch.validation.mapping_review import (
    MappingDisposition,
    ResolutionReportRow,
    classify_resolution_rows,
)


def mapping(
    *,
    source: str = "OLD",
    target: str = "NEW",
    start: date = date(2020, 1, 1),
    end: date | None = None,
    status: ApprovalStatus = ApprovalStatus.PENDING,
    mapping_type: MappingType = MappingType.UNKNOWN,
) -> ProviderSymbolMapping:
    reviewed = status is not ApprovalStatus.PENDING
    return ProviderSymbolMapping(
        security_id=f"SEC:{source}",
        constituent_symbol=source,
        provider_id="TEST_PROVIDER",
        provider_symbol=target,
        exchange_code="TEST_EXCHANGE",
        effective_from=start,
        effective_to=end,
        mapping_type=mapping_type,
        reason="Verified corporate record" if reviewed else "Legacy import pending review",
        evidence_ref="evidence://record/1" if reviewed else None,
        approval_status=status,
        reviewer="reviewer@example.com" if reviewed else None,
        reviewed_at=datetime(2026, 7, 13, tzinfo=UTC) if reviewed else None,
    )


class ProviderSymbolMappingTests(TestCase):
    def test_approved_mapping_requires_review_metadata(self) -> None:
        with self.assertRaises(ValueError):
            ProviderSymbolMapping(
                security_id="SEC:OLD",
                constituent_symbol="OLD",
                provider_id="PROVIDER",
                provider_symbol="NEW",
                exchange_code="US",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                mapping_type=MappingType.RENAME,
                reason="",
                evidence_ref=None,
                approval_status=ApprovalStatus.APPROVED,
                reviewer=None,
                reviewed_at=None,
            )

    def test_unknown_mapping_cannot_be_approved(self) -> None:
        with self.assertRaises(ValueError):
            mapping(status=ApprovalStatus.APPROVED, mapping_type=MappingType.UNKNOWN)

    def test_invalid_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            mapping(start=date(2020, 2, 1), end=date(2020, 1, 31))


class MappingRegistryTests(TestCase):
    def test_no_mapping_resolves_direct_symbol_without_identity_change(self) -> None:
        result = MappingRegistry(()).resolve(
            constituent_symbol="aapl",
            provider_id="TEST_PROVIDER",
            as_of=date(2024, 1, 1),
        )
        self.assertEqual(result.state, ResolutionState.DIRECT)
        self.assertEqual(result.provider_symbol, "AAPL")
        self.assertTrue(result.automatic_download_allowed)

    def test_approved_effective_mapping_resolves(self) -> None:
        registry = MappingRegistry(
            (
                mapping(
                    status=ApprovalStatus.APPROVED,
                    mapping_type=MappingType.RENAME,
                ),
            )
        )
        result = registry.resolve("OLD", "TEST_PROVIDER", date(2021, 1, 1))
        self.assertEqual(result.state, ResolutionState.MAPPED)
        self.assertEqual(result.provider_symbol, "NEW")
        self.assertTrue(result.automatic_download_allowed)

    def test_pending_and_rejected_mappings_are_quarantined(self) -> None:
        for status in (ApprovalStatus.PENDING, ApprovalStatus.REJECTED):
            registry = MappingRegistry((mapping(status=status),))
            result = registry.resolve("OLD", "TEST_PROVIDER", date(2021, 1, 1))
            self.assertEqual(result.state, ResolutionState.QUARANTINED)
            self.assertIsNone(result.provider_symbol)
            self.assertFalse(result.automatic_download_allowed)

    def test_mapping_outside_effective_date_is_not_applied(self) -> None:
        registry = MappingRegistry((mapping(end=date(2020, 12, 31)),))
        result = registry.resolve("OLD", "TEST_PROVIDER", date(2021, 1, 1))
        self.assertEqual(result.state, ResolutionState.DIRECT)
        self.assertEqual(result.provider_symbol, "OLD")

    def test_overlapping_intervals_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MappingRegistry(
                (
                    mapping(start=date(2020, 1, 1), end=date(2020, 12, 31)),
                    mapping(start=date(2020, 6, 1), end=None),
                )
            )

    def test_adjacent_intervals_are_allowed(self) -> None:
        registry = MappingRegistry(
            (
                mapping(start=date(2020, 1, 1), end=date(2020, 12, 31)),
                mapping(source="OLD", target="NEW2", start=date(2021, 1, 1)),
            )
        )
        self.assertEqual(len(registry.mappings), 2)

    def test_registry_keeps_providers_independent(self) -> None:
        first = mapping()
        second = ProviderSymbolMapping(
            security_id="SEC:OLD",
            constituent_symbol="OLD",
            provider_id="OTHER_PROVIDER",
            provider_symbol="OTHER",
            exchange_code="US",
            effective_from=date(2020, 1, 1),
            effective_to=None,
            mapping_type=MappingType.UNKNOWN,
            reason="Pending",
            evidence_ref=None,
            approval_status=ApprovalStatus.PENDING,
            reviewer=None,
            reviewed_at=None,
        )
        registry = MappingRegistry((first, second))
        self.assertEqual(len(registry.mappings), 2)


class LegacyMigrationTests(TestCase):
    def test_legacy_mappings_are_pending_and_identity_entries_are_omitted(self) -> None:
        result = migrate_legacy_mapping(
            {"INFO": "SPGI", "INGR": "INGR", " rds-a ": " shel "},
            provider_id="TEST_PROVIDER",
            exchange_code="US",
            effective_from=date(1996, 1, 1),
        )
        self.assertEqual(result.imported_count, 2)
        self.assertEqual(result.omitted_identity_count, 1)
        self.assertEqual(result.invalid_count, 0)
        self.assertTrue(
            all(
                item.approval_status is ApprovalStatus.PENDING
                and item.mapping_type is MappingType.UNKNOWN
                for item in result.registry.mappings
            )
        )

    def test_invalid_legacy_entries_are_reported_not_activated(self) -> None:
        result = migrate_legacy_mapping(
            {"": "SPGI", "OLD": ""},
            provider_id="TEST_PROVIDER",
            exchange_code="US",
            effective_from=date(1996, 1, 1),
        )
        self.assertEqual(result.invalid_count, 2)
        self.assertEqual(len(result.registry.mappings), 0)


class MappingReviewTests(TestCase):
    def test_only_punctuation_equivalence_is_system_approved(self) -> None:
        rows = (
            ResolutionReportRow("BF.B", "BF.B", "BF-B", "SUCCESS"),
            ResolutionReportRow("INFO", "SPGI", "SPGI", "SUCCESS"),
            ResolutionReportRow("GFS.A", "GFS.A", "GFS_OLD", "SUCCESS"),
            ResolutionReportRow("AAPL", "AAPL", "AAPL", "SUCCESS"),
            ResolutionReportRow("MISSING", "MISSING", "", "FAILED"),
        )
        review = classify_resolution_rows(rows, effective_from=date(1996, 1, 1))
        dispositions = {item.input_symbol: item.disposition for item in review.records}
        self.assertEqual(dispositions["BF.B"], MappingDisposition.APPROVED_FORMATTING)
        self.assertEqual(dispositions["INFO"], MappingDisposition.PENDING_IDENTITY)
        self.assertEqual(dispositions["GFS.A"], MappingDisposition.PENDING_FALLBACK)
        self.assertEqual(dispositions["AAPL"], MappingDisposition.DIRECT)
        self.assertEqual(dispositions["MISSING"], MappingDisposition.UNRESOLVED)
        self.assertEqual(len(review.registry.mappings), 3)
        approved = [
            item
            for item in review.registry.mappings
            if item.approval_status is ApprovalStatus.APPROVED
        ]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].mapping_type, MappingType.FORMATTING_ALIAS)

    def test_old_suffix_is_never_formatting_equivalence(self) -> None:
        rows = (ResolutionReportRow("ABC", "ABC", "ABC_OLD", "SUCCESS"),)
        review = classify_resolution_rows(rows, effective_from=date(1996, 1, 1))
        self.assertEqual(review.records[0].disposition, MappingDisposition.PENDING_FALLBACK)
        self.assertEqual(
            review.registry.mappings[0].approval_status,
            ApprovalStatus.PENDING,
        )
