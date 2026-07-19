from datetime import UTC, date, datetime
from unittest import TestCase

from quantresearch.domain.mappings import (
    ApprovalStatus,
    MappingRegistry,
    MappingType,
    ProviderSymbolMapping,
)
from quantresearch.ingestion.parquet_bars import approved_provider_to_constituent


class ParquetBarIdentityTests(TestCase):
    def test_only_approved_mapping_reverses_provider_symbol(self) -> None:
        approved = ProviderSymbolMapping(
            "SEC:BF.B", "BF.B", "EODHD", "BF-B", "US", date(1996, 1, 1), None,
            MappingType.FORMATTING_ALIAS, "Punctuation alias", "rule://alias-v1",
            ApprovalStatus.APPROVED, "system:test", datetime(2026, 7, 13, tzinfo=UTC),
        )
        self.assertEqual(
            approved_provider_to_constituent(MappingRegistry((approved,)), "EODHD"),
            {"BF-B": "BF.B"},
        )

    def test_duplicate_provider_targets_are_rejected(self) -> None:
        def item(source: str) -> ProviderSymbolMapping:
            return ProviderSymbolMapping(
                f"SEC:{source}", source, "EODHD", "SAME", "US", date(1996, 1, 1), None,
                MappingType.FORMATTING_ALIAS, "Alias", "rule://alias-v1",
                ApprovalStatus.APPROVED, "system:test", datetime(2026, 7, 13, tzinfo=UTC),
            )
        with self.assertRaises(ValueError):
            approved_provider_to_constituent(MappingRegistry((item("A"), item("B"))), "EODHD")
