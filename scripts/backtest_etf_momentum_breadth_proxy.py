#!/usr/bin/env python3
"""Research-only ETF momentum/breadth event study using dated or static baskets.

The study detects an ETF's 21-session relative-strength regime versus SPY,
requires above-average ETF volume and positive constituent breadth, then measures
the following 21 sessions. Current constituent lists are a static-basket proxy;
they must not be interpreted as historical ETF holdings or historical weights.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb


@dataclass(frozen=True)
class Basket:
    name: str
    etf: str
    constituents: str | None
    method: str


BASKETS = (
    Basket("nasdaq_100", "QQQ.US", None, "etf_price_volume_only"),
    Basket("dow_jones", "DIA.US", None, "etf_price_volume_only"),
    Basket("russell_2000", "IWM.US", None, "etf_price_volume_only"),
    Basket("sp_midcap_400", "MDY.US", None, "etf_price_volume_only"),
    Basket("sp500_equal_weight", "RSP.US", None, "etf_price_volume_only"),
    Basket("us_total_market", "VTI.US", None, "etf_price_volume_only"),
    Basket("health_care", "XLV.US", "xlv_health_care_2026-07-16.csv", "static_current_holding_proxy"),
    Basket("financials", "XLF.US", "xlf_financials_2026-07-16.csv", "static_current_holding_proxy"),
    Basket("semiconductors_smh", "SMH.US", "smh_soxx_semiconductors_2026-07-16.csv", "static_current_holding_proxy"),
    Basket("semiconductors_soxx", "SOXX.US", "smh_soxx_semiconductors_2026-07-16.csv", "static_current_holding_proxy"),
    Basket("memory_dram", "DRAM.US", "dram_memory_sp500_2026-04-02.csv", "static_sp500_subset_proxy"),
)


def fetch(symbol: str, start: date, end: date, token: str) -> list[dict[str, object]]:
    query = urlencode({"from": start.isoformat(), "to": end.isoformat(), "api_token": token, "fmt": "json"})
    with urlopen(f"https://eodhd.com/api/eod/{symbol}?{query}", timeout=60) as response:  # noqa: S310
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"unexpected response for {symbol}: {rows}")
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def constituent_tickers(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["ticker"].upper().strip().replace(".", "-") for row in csv.DictReader(handle) if row.get("ticker", "").strip()}


def build_etf_features(rows: list[dict[str, object]], benchmark: dict[str, float]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index in range(21, len(rows)):
        item, prior = rows[index], rows[index - 21]
        recent_volumes = [float(value["volume"]) for value in rows[index - 21:index] if float(value["volume"]) > 0]
        if not recent_volumes:
            continue
        observed = str(item["date"])
        close, prior_close = float(item["adjusted_close"]), float(prior["adjusted_close"])
        if not close or not prior_close or observed not in benchmark:
            continue
        result.append({
            "date": observed,
            "close": close,
            "return_21d": close / prior_close - 1,
            "relative_volume": float(item["volume"]) / fmean(recent_volumes),
            "spy_return_21d": benchmark[observed],
        })
    return result


def local_component_prices(parquet: Path, tickers: set[str], start: date, end: date) -> dict[str, list[dict[str, object]]]:
    con = duckdb.connect(":memory:")
    try:
        placeholders = ",".join("?" for _ in tickers)
        query = f"""
            SELECT UPPER(Ticker) AS ticker, CAST(Date AS DATE) AS observed, AdjustedClose AS close_price
            FROM read_parquet(?)
            WHERE UPPER(Ticker) IN ({placeholders})
              AND CAST(Date AS DATE)>=? AND CAST(Date AS DATE)<=? AND AdjustedClose>0
            ORDER BY ticker, observed
        """
        values = [str(parquet), *sorted(tickers), start, end]
        rows = con.execute(query, values).fetchall()
    finally:
        con.close()
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for ticker, observed, close_price in rows:
        grouped[ticker].append({"date": observed.isoformat(), "close": float(close_price)})
    return grouped


def breadth_by_date(prices: dict[str, list[dict[str, object]]]) -> dict[str, dict[str, object]]:
    daily: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ticker, rows in prices.items():
        for index in range(21, len(rows)):
            daily[str(rows[index]["date"])].append((ticker, float(rows[index]["close"]) / float(rows[index - 21]["close"]) - 1))
    result: dict[str, dict[str, object]] = {}
    for observed, values in daily.items():
        positive = [ticker for ticker, value in values if value > 0]
        result[observed] = {
            "breadth": len(positive) / len(values),
            "available_constituents": len(values),
            "positive_tickers": positive,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--holding-sessions", type=int, default=21)
    parser.add_argument("--minimum-breadth", type=float, default=0.55)
    parser.add_argument("--minimum-relative-volume", type=float, default=1.0)
    args = parser.parse_args()
    if args.start >= args.to:
        parser.error("--from must be before --to")
    if args.holding_sessions < 1:
        parser.error("--holding-sessions must be positive")
    if not 0 < args.minimum_breadth <= 1:
        parser.error("--minimum-breadth must be in (0, 1]")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; the token is not accepted as a command-line argument")
    root, output = args.project_root.expanduser().resolve(), args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "raw_eodhd"
    raw.mkdir(exist_ok=True)
    lists = root / "data/features/current_sector_lists"
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    if not parquet.is_file():
        raise FileNotFoundError(parquet)

    def cached(symbol: str) -> list[dict[str, object]]:
        path = raw / f"{symbol.replace('.', '_')}_{args.start}_{args.to}.json"
        if args.refresh or not path.exists():
            path.write_text(json.dumps(fetch(symbol, args.start, args.to, token)) + "\n", encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8"))

    spy_rows = cached("SPY.US")
    spy_features = build_etf_features(spy_rows, {str(row["date"]): 0 for row in spy_rows})
    spy_returns = {str(row["date"]): float(row["return_21d"]) for row in spy_features}
    summaries: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    breadth_rows: list[dict[str, object]] = []
    constituents_at_entry: list[dict[str, object]] = []

    for basket in BASKETS:
        try:
            etf_rows = cached(basket.etf)
        except Exception as error:
            summaries.append({"basket": basket.name, "etf": basket.etf, "status": "unavailable", "reason": str(error)})
            continue
        if len(etf_rows) < 43:
            summaries.append({"basket": basket.name, "etf": basket.etf, "status": "unavailable", "reason": "insufficient history in requested window"})
            continue
        tickers = constituent_tickers(lists / basket.constituents) if basket.constituents else set()
        components = local_component_prices(parquet, tickers, args.start, args.to) if tickers else {}
        breadth = breadth_by_date(components) if components else {}
        features = build_etf_features(etf_rows, spy_returns)
        feature_by_date = {str(row["date"]): row for row in features}
        ordered_dates = [str(row["date"]) for row in features]
        active_previous = False
        basket_events: list[dict[str, object]] = []
        for i, observed in enumerate(ordered_dates):
            feature, component_state = feature_by_date[observed], breadth.get(observed)
            relative_strength = float(feature["return_21d"]) - float(feature["spy_return_21d"])
            breadth_pass = bool(component_state) and float(component_state["breadth"]) >= args.minimum_breadth if basket.constituents else True
            is_active = relative_strength > 0 and float(feature["relative_volume"]) >= args.minimum_relative_volume and breadth_pass
            breadth_rows.append({
                "basket": basket.name, "etf": basket.etf, "date": observed,
                "etf_return_21d": feature["return_21d"], "spy_return_21d": feature["spy_return_21d"],
                "relative_strength_21d": relative_strength, "etf_relative_volume": feature["relative_volume"],
                "constituent_breadth_21d": component_state["breadth"] if component_state else "",
                "available_constituents": component_state["available_constituents"] if component_state else 0,
                "signal_active": is_active, "signal_start": is_active and not active_previous,
                "constituent_method": basket.method,
            })
            if is_active and not active_previous and i + 1 + args.holding_sessions < len(ordered_dates):
                entry_date, exit_date = ordered_dates[i + 1], ordered_dates[i + 1 + args.holding_sessions]
                etf_return = float(feature_by_date[exit_date]["close"]) / float(feature_by_date[entry_date]["close"]) - 1
                component_returns: list[float] = []
                for ticker in component_state["positive_tickers"] if component_state else []:
                    rows = {str(row["date"]): float(row["close"]) for row in components[ticker]}
                    if entry_date in rows and exit_date in rows:
                        component_returns.append(rows[exit_date] / rows[entry_date] - 1)
                        constituents_at_entry.append({"basket": basket.name, "signal_date": observed, "entry_date": entry_date, "exit_date": exit_date, "ticker": ticker, "weight": 1 / len(component_state["positive_tickers"]), "return": component_returns[-1], "weight_method": "equal_weight_positive_breadth_proxy"})
                event = {"basket": basket.name, "etf": basket.etf, "signal_date": observed, "entry_date": entry_date, "exit_date": exit_date, "holding_sessions": args.holding_sessions, "etf_return": etf_return, "constituent_equal_weight_return": fmean(component_returns) if component_returns else "", "constituent_count": len(component_returns), "signal_breadth": component_state["breadth"] if component_state else "", "signal_relative_strength_21d": relative_strength, "signal_relative_volume": feature["relative_volume"], "constituent_method": basket.method}
                events.append(event)
                basket_events.append(event)
            active_previous = is_active
        etf_returns = [float(row["etf_return"]) for row in basket_events]
        stock_returns = [float(row["constituent_equal_weight_return"]) for row in basket_events if row["constituent_equal_weight_return"] != ""]
        summaries.append({"basket": basket.name, "etf": basket.etf, "status": "ok", "signals": len(basket_events), "average_etf_return": fmean(etf_returns) if etf_returns else "", "etf_win_rate": sum(value > 0 for value in etf_returns) / len(etf_returns) if etf_returns else "", "average_constituent_equal_weight_return": fmean(stock_returns) if stock_returns else "", "constituent_win_rate": sum(value > 0 for value in stock_returns) / len(stock_returns) if stock_returns else "", "available_current_constituents": len(components), "constituent_method": basket.method})

    write_csv(output / "strategy_summary.csv", summaries, ["basket", "etf", "status", "reason", "signals", "average_etf_return", "etf_win_rate", "average_constituent_equal_weight_return", "constituent_win_rate", "available_current_constituents", "constituent_method"])
    write_csv(output / "signal_events.csv", events, ["basket", "etf", "signal_date", "entry_date", "exit_date", "holding_sessions", "etf_return", "constituent_equal_weight_return", "constituent_count", "signal_breadth", "signal_relative_strength_21d", "signal_relative_volume", "constituent_method"])
    write_csv(output / "daily_breadth_regimes.csv", breadth_rows, ["basket", "etf", "date", "etf_return_21d", "spy_return_21d", "relative_strength_21d", "etf_relative_volume", "constituent_breadth_21d", "available_constituents", "signal_active", "signal_start", "constituent_method"])
    write_csv(output / "constituents_at_signal_entries.csv", constituents_at_entry, ["basket", "signal_date", "entry_date", "exit_date", "ticker", "weight", "return", "weight_method"])
    print(json.dumps({"output": str(output), "summary": str(output / "strategy_summary.csv"), "events": str(output / "signal_events.csv"), "regimes": str(output / "daily_breadth_regimes.csv"), "constituents": str(output / "constituents_at_signal_entries.csv"), "limitations": "Static current constituent lists are a proxy except when separately replaced by dated issuer holdings. DRAM launched in 2026 and is unavailable in a 2010-2025 window. This is an event study, not a tradable strategy or investment advice."}, indent=2))


if __name__ == "__main__":
    main()
