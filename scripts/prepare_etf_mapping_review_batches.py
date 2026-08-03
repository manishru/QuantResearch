#!/usr/bin/env python3
"""Turn an ETF-mapping review CSV into dated, copy-ready research batches.

Input is the output of ``audit_momentum_matrix_mappings.py``.  Every row stays
dated: a mapping returned for one interval cannot silently be reused for a
different historical period.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    with args.review.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: (-int(row["candidate_occurrences"]), row["ticker"], row["first_execution_date"]))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for first in range(0, len(rows), args.batch_size):
        batch = rows[first:first + args.batch_size]
        number = first // args.batch_size + 1
        path = args.output / f"batch_{number:03d}.md"
        lines = [
            "Use the most specific non-leveraged industry ETF valid for each exact historical interval.",
            "Return one line per item as `TICKER, YYYY-MM-DD to YYYY-MM-DD → ETF` or `→ EXCLUDE`.",
            "Do not use a broad sector ETF unless no valid focused industry ETF exists.",
            "",
            "```text",
        ]
        for row in batch:
            period = row["first_execution_date"] if row["first_execution_date"] == row["last_execution_date"] else f"{row['first_execution_date']} to {row['last_execution_date']}"
            lines.append(f"{row['ticker']}, {period} → ?")
        lines.extend(["```", "", "Research context: these are point-in-time S&P 500 momentum candidates. ETF mappings are sector-risk proxies, not claims of archived daily ETF holdings."])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest.append({"batch": number, "records": len(batch), "first_ticker": batch[0]["ticker"], "last_ticker": batch[-1]["ticker"], "file": str(path)})
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=["batch", "records", "first_ticker", "last_ticker", "file"])
        out.writeheader(); out.writerows(manifest)
    print({"records": len(rows), "batches": len(manifest), "manifest": str(args.output / "manifest.csv")})


if __name__ == "__main__":
    main()
