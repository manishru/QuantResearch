#!/usr/bin/env python3
"""Join completed-session semiconductor price/volume and memory news reports.

This is a research dashboard, not a trading recommendation or proof of
institutional flow. It does not use Fundamentals or ETF holdings data.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return {row["date"]: row for row in csv.DictReader(file)}


def number(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "")
    return float(value) if value not in ("", None) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sector-summary", type=Path, required=True)
    parser.add_argument("--news-proxy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sector = read_rows(args.sector_summary.expanduser().resolve())
    news = read_rows(args.news_proxy.expanduser().resolve())
    shared_dates = sorted(set(sector) & set(news), reverse=True)
    if not shared_dates:
        parser.error("the reports have no dates in common")

    rows: list[dict[str, object]] = []
    for observed in shared_dates:
        semi, memory = sector[observed], news[observed]
        semi_return = number(semi, "semiconductor_avg_return_vs_spy_21d")
        memory_return = number(memory, "memory_return_21d")
        if semi_return is not None and memory_return is not None and semi_return > 0 and memory_return > 0:
            regime = "risk_on_confirmation"
        elif semi_return is not None and memory_return is not None and semi_return < 0 and memory_return < 0:
            regime = "risk_off_warning"
        else:
            regime = "mixed"
        sentiment = number(memory, "memory_sentiment")
        sentiment_context = "positive" if sentiment is not None and sentiment >= 0.55 else "negative" if sentiment is not None and sentiment <= 0.45 else "neutral"
        rows.append(
            {
                "date": observed,
                "regime": regime,
                "semiconductor_return_vs_spy_21d": semi_return,
                "semiconductor_relative_volume": number(semi, "semiconductor_avg_relative_volume"),
                "semiconductor_state": semi["semiconductor_state"],
                "leading_sector": semi["leading_sector"],
                "leading_sector_return_vs_spy_21d": number(semi, "leading_return_vs_spy_21d"),
                "leading_sector_relative_volume": number(semi, "leading_relative_volume"),
                "memory_return_21d": memory_return,
                "memory_relative_volume": number(memory, "memory_relative_volume"),
                "memory_sentiment": sentiment,
                "memory_article_count": memory.get("memory_article_count", ""),
                "sentiment_context": sentiment_context,
            }
        )
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "daily_memory_semiconductor_regime.csv"
    with report.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    run = {
        "output": str(output),
        "report": str(report),
        "latest": rows[0],
        "limitation": "Price/volume and news sentiment are proxies. They do not identify institutional orders and are not a standalone buy, sell, or short signal.",
    }
    (output / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
