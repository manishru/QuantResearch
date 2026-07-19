import csv
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from quantresearch.domain.membership import MembershipHistory, MembershipSnapshot
from quantresearch.ingestion.component_csv import ComponentCsvError, load_component_snapshots


class MembershipHistoryTests(TestCase):
    def setUp(self) -> None:
        self.history = MembershipHistory(
            index_id="TEST_INDEX",
            snapshots=(
                MembershipSnapshot(
                    index_id="TEST_INDEX",
                    effective_date=date(2020, 1, 1),
                    symbols=frozenset({"AAA", "BBB"}),
                    source_row=2,
                ),
                MembershipSnapshot(
                    index_id="TEST_INDEX",
                    effective_date=date(2020, 2, 1),
                    symbols=frozenset({"BBB", "CCC"}),
                    source_row=3,
                ),
                MembershipSnapshot(
                    index_id="TEST_INDEX",
                    effective_date=date(2020, 3, 1),
                    symbols=frozenset({"AAA", "CCC"}),
                    source_row=4,
                ),
            ),
            source_path=Path("fixture.csv"),
            source_sha256="a" * 64,
        )

    def test_query_uses_latest_snapshot_not_future_membership(self) -> None:
        result = self.history.as_of(date(2020, 1, 20))
        self.assertEqual(result.symbols, frozenset({"AAA", "BBB"}))
        self.assertEqual(result.source_snapshot_date, date(2020, 1, 1))

    def test_query_boundary_applies_new_snapshot_on_effective_date(self) -> None:
        result = self.history.as_of(date(2020, 2, 1))
        self.assertEqual(result.symbols, frozenset({"BBB", "CCC"}))

    def test_query_after_last_snapshot_is_explicit_carry_forward(self) -> None:
        result = self.history.as_of(date(2020, 7, 13))
        self.assertEqual(result.symbols, frozenset({"AAA", "CCC"}))
        self.assertEqual(result.source_snapshot_date, date(2020, 3, 1))
        self.assertTrue(result.carried_forward)

    def test_query_before_first_snapshot_fails(self) -> None:
        with self.assertRaises(LookupError):
            self.history.as_of(date(2019, 12, 31))

    def test_intervals_handle_removal_and_reentry(self) -> None:
        aaa = [item for item in self.history.intervals() if item.constituent_symbol == "AAA"]
        self.assertEqual(len(aaa), 2)
        self.assertEqual(aaa[0].effective_from, date(2020, 1, 1))
        self.assertEqual(aaa[0].effective_to, date(2020, 1, 31))
        self.assertEqual(aaa[1].effective_from, date(2020, 3, 1))
        self.assertIsNone(aaa[1].effective_to)

    def test_acquisition_union_is_not_as_of_universe(self) -> None:
        self.assertEqual(self.history.acquisition_union(), frozenset({"AAA", "BBB", "CCC"}))
        self.assertNotEqual(
            self.history.acquisition_union(), self.history.as_of(date(2020, 2, 15)).symbols
        )

    def test_multiple_indexes_cannot_be_mixed(self) -> None:
        snapshots = list(self.history.snapshots)
        snapshots.append(
            MembershipSnapshot(
                index_id="OTHER",
                effective_date=date(2020, 4, 1),
                symbols=frozenset({"ZZZ"}),
                source_row=5,
            )
        )
        with self.assertRaises(ValueError):
            MembershipHistory(
                index_id="TEST_INDEX",
                snapshots=tuple(snapshots),
                source_path=Path("fixture.csv"),
                source_sha256="a" * 64,
            )


class ComponentCsvTests(TestCase):
    def _write(self, directory: str, rows: list[tuple[str, str]]) -> Path:
        path = Path(directory) / "components.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "tickers"])
            writer.writerows(rows)
        return path

    def test_loader_normalizes_and_deduplicates_symbols(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(directory, [("2020-01-01", " aaa,BBB, aaa , bf.b ")])
            history = load_component_snapshots(path, index_id="TEST")
            self.assertEqual(history.snapshots[0].symbols, frozenset({"AAA", "BBB", "BF.B"}))
            self.assertEqual(len(history.source_sha256), 64)

    def test_loader_rejects_out_of_order_dates(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(
                directory,
                [("2020-02-01", "AAA"), ("2020-01-01", "AAA")],
            )
            with self.assertRaises(ComponentCsvError):
                load_component_snapshots(path, index_id="TEST")

    def test_loader_rejects_conflicting_duplicate_date(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(
                directory,
                [("2020-01-01", "AAA"), ("2020-01-01", "BBB")],
            )
            with self.assertRaises(ComponentCsvError):
                load_component_snapshots(path, index_id="TEST")

    def test_loader_rejects_missing_columns_and_empty_membership(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.csv"
            missing.write_text("when,symbols\n2020-01-01,AAA\n", encoding="utf-8")
            with self.assertRaises(ComponentCsvError):
                load_component_snapshots(missing, index_id="TEST")

            empty = self._write(directory, [("2020-01-01", "")])
            with self.assertRaises(ComponentCsvError):
                load_component_snapshots(empty, index_id="TEST")
