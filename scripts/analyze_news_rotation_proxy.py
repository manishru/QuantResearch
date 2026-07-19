#!/usr/bin/env python3
"""Compare memory versus Mag-7 news sentiment, attention, price, and volume.

This is a research-only rotation proxy.  It cannot identify real-time
institutional trading. EODHD credentials are read only from an environment
variable and are never written to reports or logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb

from quantresearch.research.news_rotation import aggregate_basket_observations

# SNDK is deliberately omitted from the default historical basket because it
# lacks a continuous 2010 history. Keeping MU/WDC/STX fixed avoids silently
# changing the basket partway through a rotation study.
MEMORY = ("MU", "WDC", "STX")
MAG7 = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA")


def fetch_json(url: str) -> object:
    with urlopen(url, timeout=60) as response:  # noqa: S310 -- fixed HTTPS host
        return json.loads(response.read().decode("utf-8"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--memory-ticker", action="append", default=[], help="Repeat to override the default historical memory basket")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--news-limit", type=int, default=0, help="Optional latest news articles per ticker to archive")
    args = parser.parse_args()
    if args.to < args.start or args.news_limit < 0:
        parser.error("invalid date range or news limit")
    memory_tickers = tuple(sorted({ticker.upper().strip() for ticker in (args.memory_ticker or MEMORY) if ticker.strip()}))
    if not memory_tickers:
        parser.error("at least one memory ticker is required")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; the token is not accepted as a command-line argument")
    root, output = args.project_root.expanduser().resolve(), args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "raw_eodhd"
    raw.mkdir(exist_ok=True)
    observations: list[tuple[str, str, float, int]] = []
    for ticker in memory_tickers + MAG7:
        sentiment_path = raw / f"sentiment_{ticker}_{args.start}_{args.to}.json"
        if args.refresh or not sentiment_path.exists():
            query = urlencode({"s": ticker.lower(), "from": args.start.isoformat(), "to": args.to.isoformat(), "api_token": token, "fmt": "json"})
            payload = fetch_json(f"https://eodhd.com/api/sentiments?{query}")
            sentiment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        else:
            payload = json.loads(sentiment_path.read_text(encoding="utf-8"))
        for row in payload.get(f"{ticker}.US", payload.get(ticker, [])) if isinstance(payload, dict) else []:
            observations.append((ticker, str(row["date"]), float(row["normalized"]), int(row["count"])))
        if args.news_limit:
            news_path = raw / f"latest_news_{ticker}.json"
            if args.refresh or not news_path.exists():
                query = urlencode({"s": f"{ticker}.US", "limit": args.news_limit, "offset": 0, "api_token": token, "fmt": "json"})
                payload = fetch_json(f"https://eodhd.com/api/news?{query}")
                news_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    memory = aggregate_basket_observations(observations, set(memory_tickers))
    mag7 = aggregate_basket_observations(observations, set(MAG7))
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    if not parquet.exists():
        raise FileNotFoundError(f"missing validated prices: {parquet}")
    con = duckdb.connect(":memory:")
    try:
        symbols = memory_tickers + MAG7
        placeholders = ",".join("?" for _ in symbols)
        price_rows = con.execute(f"""
          WITH p AS (
            SELECT UPPER(Ticker) ticker, CAST(Date AS DATE) observed, Close close_price, Volume volume
            FROM read_parquet(?) WHERE UPPER(Ticker) IN ({placeholders})
          ), f AS (
            SELECT *, close_price/LAG(close_price,21) OVER w-1 return_21d,
              volume/NULLIF(AVG(volume) OVER (PARTITION BY ticker ORDER BY observed ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),0) relative_volume,
              LEAD(close_price,21) OVER w/close_price-1 forward_return_21d
            FROM p WINDOW w AS (PARTITION BY ticker ORDER BY observed)
          )
          SELECT observed, ticker, return_21d, relative_volume, forward_return_21d FROM f
          WHERE observed BETWEEN ? AND ? ORDER BY observed, ticker
        """, [str(parquet), *symbols, args.start, args.to]).fetchall()
    finally:
        con.close()
    daily: dict[str, dict[str, list[float]]] = {}
    for observed, ticker, ret, rvol, forward in price_rows:
        day = str(observed)
        group = "memory" if ticker in memory_tickers else "mag7"
        daily.setdefault(day, {}).setdefault(group, []).append((ret, rvol, forward))
    rows: list[dict[str, object]] = []
    for day in sorted(set(daily) | set(memory) | set(mag7)):
        groups = daily.get(day, {})
        mem_values, m7_values = groups.get("memory", []), groups.get("mag7", [])
        mean = lambda values, index: sum(x[index] for x in values if x[index] is not None) / len([x for x in values if x[index] is not None]) if any(x[index] is not None for x in values) else None
        mem_sent, mem_count = memory.get(day, (None, 0))
        m7_sent, m7_count = mag7.get(day, (None, 0))
        mem_ret, m7_ret = mean(mem_values, 0), mean(m7_values, 0)
        rows.append({"date": day, "memory_sentiment": mem_sent, "memory_article_count": mem_count, "mag7_sentiment": m7_sent, "mag7_article_count": m7_count,
                     "memory_return_21d": mem_ret, "mag7_return_21d": m7_ret, "memory_minus_mag7_21d": (mem_ret-m7_ret if mem_ret is not None and m7_ret is not None else None),
                     "memory_relative_volume": mean(mem_values, 1), "mag7_relative_volume": mean(m7_values, 1),
                     "memory_forward_return_21d": mean(mem_values, 2), "mag7_forward_return_21d": mean(m7_values, 2),
                     "rotation_proxy_event": bool(mem_ret is not None and m7_ret is not None and mem_ret <= -.10 and m7_ret >= .05 and (mem_count or 0) >= 10)})
    write_csv(output / "daily_rotation_proxy.csv", rows)
    run = {"output": str(output), "from": str(args.start), "to": str(args.to), "memory": memory_tickers, "mag7": MAG7,
           "proxy_limitation": "News/sentiment and price/volume are attention/rotation proxies, not real-time institutional holdings or flows.",
           "raw_cache": str(raw), "daily_report": str(output / "daily_rotation_proxy.csv")}
    (output / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
