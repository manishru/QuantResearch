import csv
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from quantresearch.cli import main


class CliTests(TestCase):
    def test_review_validate_reports_pending_and_returns_nonzero(self) -> None:
        with TemporaryDirectory() as directory:
            decisions = Path(directory) / "exclusions.csv"
            with decisions.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "index_id", "constituent_symbol", "effective_from",
                        "effective_to", "reason", "rationale", "evidence_ref",
                        "status", "reviewer", "reviewed_at",
                    ]
                )
                writer.writerow(
                    ["SP500", "OLD", "1996-01-01", "", "provider_data_unavailable",
                     "Provider history missing", "", "pending", "", ""]
                )
            output = StringIO()
            with redirect_stdout(output):
                return_code = main(
                    ["review", "validate", "--exclusions", str(decisions), "--json"]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(return_code, 2)
            self.assertEqual(payload["exclusions"]["pending"], 1)
            self.assertFalse(payload["ready"])
    def test_doctor_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                "QUANTRESEARCH_DATA_DIR": str(root / "data"),
                "QUANTRESEARCH_LOGS_DIR": str(root / "logs"),
            }
            output = StringIO()
            with patch.dict("os.environ", environment, clear=True), redirect_stdout(output):
                return_code = main(["doctor", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(return_code, 0)
            self.assertTrue(payload["raw_data_dir_exists"])

    def test_universe_inspect_json_reports_point_in_time_membership(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "components.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["date", "tickers"])
                writer.writerow(["2020-01-01", "AAA,BBB"])
                writer.writerow(["2020-02-01", "BBB,CCC"])

            output = StringIO()
            with redirect_stdout(output):
                return_code = main(
                    [
                        "universe",
                        "inspect",
                        "--input",
                        str(source),
                        "--index-id",
                        "TEST",
                        "--as-of",
                        "2020-02-15",
                        "--json",
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(return_code, 0)
            self.assertEqual(payload["members"], ["BBB", "CCC"])
            self.assertEqual(payload["source_snapshot_date"], "2020-02-01")
            self.assertTrue(payload["carried_forward"])
            self.assertEqual(payload["acquisition_union_count"], 3)

    def test_research_database_init_and_inspect(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "research.duckdb"
            output = StringIO()
            with redirect_stdout(output):
                return_code = main(["research-db", "init", "--database", str(database), "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(return_code, 0)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["row_counts"]["strategy_definitions"], 0)

    def test_walk_forward_schedule_reports_live_window(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            return_code = main(
                [
                    "walk-forward",
                    "schedule",
                    "--start-year",
                    "1996",
                    "--last-completed-year",
                    "2025",
                    "--json",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(return_code, 0)
        self.assertEqual(payload["windows"][0]["train_start"], "1996-01-01")
        self.assertEqual(payload["windows"][-1]["forward_state"], "live_unobserved")
        self.assertEqual(payload["windows"][-1]["forward_start"], "2026-01-01")
