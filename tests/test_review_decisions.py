import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantresearch.ingestion.review_decisions import (
    load_exclusion_decisions,
    load_mapping_decisions,
)


class ReviewDecisionImportTests(TestCase):
    def test_approved_mapping_is_loaded_and_versioned(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mappings.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["security_id", "constituent_symbol", "provider_id",
                     "provider_symbol", "exchange_code", "effective_from",
                     "effective_to", "mapping_type", "reason", "evidence_ref",
                     "approval_status", "reviewer", "reviewed_at"]
                )
                writer.writerow(
                    ["SEC:BF.B", "BF.B", "EODHD", "BF-B", "US", "1996-01-01",
                     "", "formatting_alias", "Punctuation alias", "rule://alias-v1",
                     "approved", "system:alias-v1", "2026-07-13T00:00:00+00:00"]
                )
            result = load_mapping_decisions(path)
            self.assertEqual(len(result.registry.mappings), 1)
            self.assertEqual(result.counts["approved"], 1)
            self.assertTrue(result.ready)

    def test_approved_exclusion_is_loaded_and_content_versioned(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "index_id", "constituent_symbol", "effective_from",
                        "effective_to", "reason", "rationale", "evidence_ref",
                        "status", "reviewer", "reviewed_at",
                    ]
                )
                writer.writerow(
                    ["SP500", "OLD", "1996-01-01", "2000-01-01",
                     "provider_data_unavailable", "No licensed history",
                     "evidence://case/1", "approved", "analyst@example.com",
                     "2026-07-13T12:00:00+00:00"]
                )
            result = load_exclusion_decisions(path)
            self.assertEqual(len(result.registry.exclusions), 1)
            self.assertEqual(len(result.source_sha256), 64)
            self.assertEqual(result.counts["approved"], 1)

    def test_missing_approved_evidence_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.csv"
            path.write_text(
                "index_id,constituent_symbol,effective_from,effective_to,reason,"
                "rationale,evidence_ref,status,reviewer,reviewed_at\n"
                "SP500,OLD,1996-01-01,,provider_data_unavailable,Missing,,approved,,\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_exclusion_decisions(path)
