#!/usr/bin/env python3
"""Compare the DRAM risk-off rule with SNDK/MU inverse-ETF confirmation.

This is a research timeline.  It identifies completed-close signals only; a
modelled action, if any, would occur at the following session's open.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen


SYMBOLS = ("DRAM.US", "SPY.US", "SNDK.US", "SNXX.US", "SNDQ.US", "MUD.US", "MUZ.US")


def fetch(symbol: str, token: str, start: date, end: date) -> list[dict]:
    query = urlencode({"api_token": token, "fmt": "json", "from": start.isoformat(), "to": end.isoformat()})
    with urlopen(f"https://eodhd.com/api/eod/{symbol}?{query}", timeout=60) as response:
        rows = json.loads(response.read())
    if not isinstance(rows, list):
        raise RuntimeError(f"{symbol}: {rows}")
    return sorted(rows, key=lambda row: row["date"])


def aligned(rows: list[dict]) -> dict[str, dict]:
    return {row["date"]: row for row in rows if row.get("adjusted_close") is not None}


def rolling_state(rows: list[dict], benchmark: dict[str, dict], lookback: int, drawdown: float, min_volume: float, inverse: bool) -> dict[str, dict]:
    result: dict[str, dict] = {}
    peak = 0.0
    for index, row in enumerate(rows):
        close = float(row.get("adjusted_close") or 0)
        peak = max(peak, close)
        if index < lookback or row["date"] not in benchmark or rows[index - lookback]["date"] not in benchmark:
            continue
        prior = rows[index - lookback]
        volumes = [float(item.get("volume") or 0) for item in rows[index - lookback:index] if float(item.get("volume") or 0) > 0]
        if not volumes:
            continue
        benchmark_return = float(benchmark[row["date"]]["adjusted_close"]) / float(benchmark[prior["date"]]["adjusted_close"]) - 1
        asset_return = close / float(prior["adjusted_close"]) - 1
        relative_volume = float(row.get("volume") or 0) / fmean(volumes)
        relative_return = asset_return - benchmark_return
        signal = (asset_return > 0 and relative_volume >= min_volume) if inverse else (
            relative_return < 0 and relative_volume >= min_volume and close / peak - 1 <= -drawdown
        )
        result[row["date"]] = {
            "return_lookback": asset_return,
            "return_vs_spy": relative_return,
            "relative_volume": relative_volume,
            "drawdown_from_peak": close / peak - 1,
            "signal": signal,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--to", type=date.fromisoformat, default=date.today())
    parser.add_argument("--lookback-sessions", type=int, default=21)
    parser.add_argument("--drawdown", type=float, default=0.10)
    parser.add_argument("--min-relative-volume", type=float, default=1.2)
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; tokens are intentionally not accepted on the command line")
    args.output.mkdir(parents=True, exist_ok=True)
    raw: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    for symbol in SYMBOLS:
        try:
            raw[symbol] = fetch(symbol, token, args.start, args.to)
        except Exception as error:
            errors[symbol] = str(error)
            raw[symbol] = []
    spy = aligned(raw["SPY.US"])
    states = {
        "dram": rolling_state(raw["DRAM.US"], spy, args.lookback_sessions, args.drawdown, args.min_relative_volume, inverse=False),
        "sndq": rolling_state(raw["SNDQ.US"], spy, args.lookback_sessions, args.drawdown, args.min_relative_volume, inverse=True),
        "mud": rolling_state(raw["MUD.US"], spy, args.lookback_sessions, args.drawdown, args.min_relative_volume, inverse=True),
        "muz": rolling_state(raw["MUZ.US"], spy, args.lookback_sessions, args.drawdown, args.min_relative_volume, inverse=True),
    }
    dates = sorted(set().union(*[set(state) for state in states.values()]))
    daily: list[dict] = []
    events: list[dict] = []
    previous = {name: False for name in states}
    for observed in dates:
        row: dict[str, object] = {"signal_date": observed}
        for name, state in states.items():
            values = state.get(observed, {})
            for field in ("return_lookback", "return_vs_spy", "relative_volume", "drawdown_from_peak", "signal"):
                row[f"{name}_{field}"] = values.get(field, "")
            now = bool(values.get("signal", False))
            if now and not previous[name]:
                event_values = {key: value for key, value in values.items() if key != "signal"}
                events.append({"signal_date": observed, "signal": name, **event_values,
                               "execution_assumption": "following_session_open"})
            previous[name] = now
        daily.append(row)
    daily_fields = list(daily[0]) if daily else ["signal_date"]
    with (args.output / "daily_memory_exit_signals.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=daily_fields); writer.writeheader(); writer.writerows(daily)
    event_fields = ["signal_date", "signal", "return_lookback", "return_vs_spy", "relative_volume", "drawdown_from_peak", "execution_assumption"]
    with (args.output / "signal_start_events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(events)
    summary = {"output": str(args.output.resolve()), "events": len(events), "errors": errors,
               "definition": "DRAM: underperforms SPY + relative volume threshold + drawdown; inverse ETFs: positive return + relative volume threshold",
               "event_report": str((args.output / "signal_start_events.csv").resolve())}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
