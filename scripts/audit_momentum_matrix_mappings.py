#!/usr/bin/env python3
"""Audit reviewed ETF coverage for momentum candidates before a sector test.

Writes only the candidates needing operator mapping review; it never guesses a
broad ETF proxy.  Static mappings are supplemented by approved dated mappings.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mapping_resolver(static_path: Path, interval_path: Path):
    static = {row["ticker"]: row for row in read_rows(static_path)}
    intervals: dict[str, list[dict[str, str]]] = defaultdict(list)
    if interval_path.is_file():
        for row in read_rows(interval_path):
            if row.get("status", "").lower() in {"approved", "excluded"}:
                intervals[row["ticker"]].append(row)
    for rows in intervals.values():
        rows.sort(key=lambda row: row.get("effective_from") or "0001-01-01")

    def resolve(ticker: str, observed: date) -> dict[str, str] | None:
        for row in intervals.get(ticker, []):
            start = date.fromisoformat(row["effective_from"]) if row.get("effective_from") else date.min
            end = date.fromisoformat(row["effective_to"]) if row.get("effective_to") else date.max
            if start <= observed <= end:
                return row
        return static.get(ticker)

    return resolve


def write_csv(path: Path, values: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, action="append", required=True, help="Repeat for each ranking-metric candidate CSV.")
    parser.add_argument("--mapping", type=Path, default=Path("config/etf_confirmed_momentum_mapping.csv"))
    parser.add_argument("--mapping-intervals", type=Path, default=Path("config/etf_confirmed_momentum_mapping_intervals.csv"))
    parser.add_argument("--max-rank", type=int, default=10, choices=range(1, 11), help="Audit only candidates through this rank.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    resolve = mapping_resolver(args.mapping, args.mapping_intervals)
    missing: dict[tuple[str, int], dict[str, object]] = {}
    total = mapped = 0
    for candidate_path in args.candidates:
        for row in read_rows(candidate_path):
            if int(row["rank"]) > args.max_rank:
                continue
            total += 1
            observed = date.fromisoformat(row["execution_date"])
            if resolve(row["ticker"], observed):
                mapped += 1
                continue
            key = (row["ticker"], observed.year)
            item = missing.setdefault(key, {
                "ticker": row["ticker"], "year": observed.year,
                "first_execution_date": row["execution_date"],
                "last_execution_date": row["execution_date"],
                "candidate_occurrences": 0, "rules": set(), "ranks": set(),
                "nominal_days": set(), "source_files": set(),
            })
            item["first_execution_date"] = min(str(item["first_execution_date"]), row["execution_date"])
            item["last_execution_date"] = max(str(item["last_execution_date"]), row["execution_date"])
            item["candidate_occurrences"] = int(item["candidate_occurrences"]) + 1
            item["rules"].add(row["rule_name"])
            item["ranks"].add(row["rank"])
            item["nominal_days"].add(row["nominal_day"])
            item["source_files"].add(str(candidate_path))

    output_rows = []
    for item in missing.values():
        output_rows.append({
            **{key: value for key, value in item.items() if key not in {"rules", "ranks", "nominal_days", "source_files"}},
            "rules": ";".join(sorted(item["rules"])),
            "ranks": ";".join(sorted(item["ranks"], key=int)),
            "nominal_days": ";".join(sorted(item["nominal_days"], key=int)),
            "source_files": ";".join(sorted(item["source_files"])),
            "required_primary_etf": "",
            "operator_note": "",
        })
    output_rows.sort(key=lambda row: (int(row["year"]), str(row["ticker"])))
    args.output.mkdir(parents=True, exist_ok=True)
    fields = ["ticker", "year", "first_execution_date", "last_execution_date", "candidate_occurrences", "rules", "ranks", "nominal_days", "source_files", "required_primary_etf", "operator_note"]
    write_csv(args.output / "mapping_review_required.csv", output_rows, fields)
    result = {"candidate_rows": total, "max_rank": args.max_rank, "mapped_rows": mapped, "unmapped_rows": total - mapped, "unmapped_ticker_years": len(output_rows), "review_file": str(args.output / "mapping_review_required.csv"), "rule": "unmapped candidates are not assigned a guessed ETF"}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
