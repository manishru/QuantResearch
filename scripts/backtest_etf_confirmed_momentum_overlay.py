#!/usr/bin/env python3
"""Compare baseline momentum lots with an ETF-confirmed entry/exit overlay.

Research only. Sector/theme mappings are current-category proxies; direct ETF
signals are ignored until an ETF has actual EOD history, preventing backfill.
Signals use completed closes and exits use the following stock-session open.
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

import duckdb


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch(symbol: str, start: date, end: date, token: str, cache: Path) -> list[dict]:
    file = cache / f"{symbol.replace('.', '_')}_{start}_{end}.json"
    if file.exists():
        return json.loads(file.read_text())
    query = urlencode({"api_token": token, "fmt": "json", "from": start.isoformat(), "to": end.isoformat()})
    with urlopen(f"https://eodhd.com/api/eod/{symbol}?{query}", timeout=60) as response:
        result = json.loads(response.read())
    if not isinstance(result, list):
        raise RuntimeError(f"{symbol}: {result}")
    file.write_text(json.dumps(result))
    return result


def state(data: list[dict], spy: dict[str, float], observed: str, lookback: int, peak_start: str | None = None) -> dict | None:
    indexed = {r["date"]: i for i, r in enumerate(data) if r.get("adjusted_close") is not None}
    i = indexed.get(observed)
    if i is None or i < lookback or observed not in spy or data[i - lookback]["date"] not in spy:
        return None
    close = float(data[i]["adjusted_close"]); prior = float(data[i - lookback]["adjusted_close"])
    volumes = [float(r.get("volume") or 0) for r in data[i - lookback:i] if float(r.get("volume") or 0) > 0]
    if not volumes:
        return None
    start_i = indexed.get(peak_start, i) if peak_start else 0
    peak = max(float(r["adjusted_close"]) for r in data[start_i:i + 1] if r.get("adjusted_close") is not None)
    return {"return": close / prior - 1, "vs_spy": close / prior - spy[observed] / spy[data[i - lookback]["date"]] + 1,
            "relative_volume": float(data[i].get("volume") or 0) / fmean(volumes), "drawdown": close / peak - 1}


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows): return None
    origin = min(d for d, _ in flows)
    def npv(rate: float) -> float: return sum(v / (1 + rate) ** ((d - origin).days / 365.2425) for d, v in flows)
    low, high = -.9999, 1000.; left, right = npv(low), npv(high)
    if left * right > 0: return None
    for _ in range(150):
        mid = (low + high) / 2; value = npv(mid)
        if left * value <= 0: high = mid
        else: low, left = mid, value
    return (low + high) / 2


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--trades", type=Path, required=True, help="All-trades CSV produced with --top-n 5.")
    p.add_argument("--mapping", type=Path, default=Path("config/etf_confirmed_momentum_mapping.csv"))
    p.add_argument("--parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    p.add_argument("--start", type=date.fromisoformat, required=True); p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--rule", default="12M>6M>3M>0"); p.add_argument("--nominal-day", type=int, default=26)
    p.add_argument("--lookback", type=int, default=21); p.add_argument("--min-relative-volume", type=float, default=1.2); p.add_argument("--drawdown", type=float, default=.10)
    p.add_argument("--monthly-budget", type=float, default=1000); p.add_argument("--cost", type=float, default=.001)
    p.add_argument("--token-env", default="EODHD_API_TOKEN"); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); token = os.environ.get(a.token_env)
    if not token: p.error(f"set {a.token_env}; tokens are not accepted on the command line")
    a.output.mkdir(parents=True, exist_ok=True); cache = a.output / "raw_eodhd"; cache.mkdir(exist_ok=True)
    mapping = {r["ticker"]: r for r in rows(a.mapping)}
    candidates = [r for r in rows(a.candidates) if r["rule_name"] == a.rule and int(r["nominal_day"]) == a.nominal_day]
    candidate_groups: dict[str, list[dict[str, str]]] = {}
    for r in candidates: candidate_groups.setdefault(r["execution_date"], []).append(r)
    for group in candidate_groups.values(): group.sort(key=lambda r: int(r["rank"]))
    base = [r for r in rows(a.trades) if r["rule"] == a.rule and int(r["nominal_day"]) == a.nominal_day and int(r["top_n"]) == 5]
    base_index = {(r["execution_date"], r["ticker"], r["rank"]): r for r in base}
    symbols = {"SPY.US"}
    for ticker in {r["ticker"] for r in candidates}:
        if ticker in mapping:
            symbols.update(v for v in (mapping[ticker]["primary_etf"], mapping[ticker]["direct_long_etf"], mapping[ticker]["direct_inverse_etf"]) if v)
    etf: dict[str, list[dict]] = {}; errors: dict[str, str] = {}
    for symbol in sorted(symbols):
        try: etf[symbol] = fetch(symbol, a.start, a.end, token, cache)
        except Exception as error: etf[symbol] = []; errors[symbol] = str(error)
    spy = {r["date"]: float(r["adjusted_close"]) for r in etf["SPY.US"] if r.get("adjusted_close") is not None}
    needed = sorted({r["ticker"] for r in base})
    con = duckdb.connect(); placeholders = ",".join("?" * len(needed))
    prices = con.execute(f"SELECT UPPER(Ticker),CAST(Date AS DATE),Open FROM read_parquet(?) WHERE UPPER(Ticker) IN ({placeholders}) ORDER BY 1,2", [str(a.parquet), *needed]).fetchall(); con.close()
    next_open: dict[tuple[str, date], tuple[date, float]] = {}
    by_stock: dict[str, list[tuple[date, float]]] = {}
    for ticker, observed, open_ in prices: by_stock.setdefault(ticker, []).append((observed, float(open_)))
    def after(ticker: str, signal: date, latest: date) -> tuple[date, float] | None:
        for observed, open_ in by_stock.get(ticker, []):
            if signal < observed <= latest: return observed, open_
        return None
    overlay: list[dict[str, object]] = []; skipped: list[dict[str, object]] = []
    baseline: list[dict[str, object]] = []
    for row in base:
        if row["rank"] != "1":
            continue
        allocation = a.monthly_budget
        shares = allocation * (1 - a.cost) / float(row["entry_price"])
        proceeds = shares * float(row["exit_price"]) * (1 - a.cost)
        baseline.append({"execution_date": row["execution_date"], "exit_date": row["exit_date"] or row["valuation_date"],
                         "allocation": allocation, "net_proceeds": proceeds, "exit_reason": row["exit_reason"]})
    for execution, group in sorted(candidate_groups.items()):
        selected = None
        for candidate in group:
            ticker = candidate["ticker"]; m = mapping.get(ticker)
            if not m: continue
            sector = state(etf.get(m["primary_etf"], []), spy, candidate["signal_date"], a.lookback)
            if not sector or not (sector["vs_spy"] > 0 and sector["relative_volume"] >= a.min_relative_volume): continue
            score = 2; inverse_state = state(etf.get(m["direct_inverse_etf"], []), spy, candidate["signal_date"], a.lookback) if m["direct_inverse_etf"] else None
            long_state = state(etf.get(m["direct_long_etf"], []), spy, candidate["signal_date"], a.lookback) if m["direct_long_etf"] else None
            if long_state and long_state["return"] > 0 and long_state["relative_volume"] >= a.min_relative_volume: score += 1
            if inverse_state and inverse_state["return"] > 0 and inverse_state["relative_volume"] >= a.min_relative_volume: score -= 1
            if score >= 2 and (execution, ticker, candidate["rank"]) in base_index: selected = (candidate, m, score); break
        if not selected:
            skipped.append({"execution_date": execution, "reason": "no_etf_confirmed_candidate"}); continue
        candidate, m, score = selected; original = base_index[(execution, candidate["ticker"], candidate["rank"])]
        original_exit = date.fromisoformat(original["exit_date"] or original["valuation_date"]); exit_date = original_exit; exit_price = float(original["exit_price"]); exit_reason = original["exit_reason"]; exit_signal = ""
        history = etf.get(m["primary_etf"], []); start = date.fromisoformat(execution)
        for row in history:
            observed = date.fromisoformat(row["date"])
            if observed <= start or observed >= original_exit: continue
            risk = state(history, spy, row["date"], a.lookback, execution)
            if risk and risk["vs_spy"] < 0 and risk["relative_volume"] >= a.min_relative_volume and risk["drawdown"] <= -a.drawdown:
                executable = after(candidate["ticker"], observed, original_exit)
                if executable: exit_date, exit_price = executable; exit_reason = "etf_rotation_risk_off"; exit_signal = observed.isoformat()
                break
        shares = a.monthly_budget * (1 - a.cost) / float(candidate["entry_price"]); proceeds = shares * exit_price * (1 - a.cost)
        overlay.append({"execution_date": execution, "signal_date": candidate["signal_date"], "ticker": candidate["ticker"], "rank_selected": candidate["rank"], "entry_price": candidate["entry_price"], "primary_etf": m["primary_etf"], "direct_long_etf": m["direct_long_etf"], "direct_inverse_etf": m["direct_inverse_etf"], "entry_score": score, "exit_date": exit_date.isoformat(), "exit_price": exit_price, "exit_reason": exit_reason, "overlay_signal_date": exit_signal, "allocation": a.monthly_budget, "net_proceeds": proceeds, "net_profit": proceeds - a.monthly_budget, "return_pct": proceeds / a.monthly_budget - 1})
    def summary(items: list[dict[str, object]]) -> dict[str, object]:
        flows = [(date.fromisoformat(str(r["execution_date"])), -float(r["allocation"])) for r in items] + [(date.fromisoformat(str(r["exit_date"])), float(r["net_proceeds"])) for r in items]
        invested = sum(float(r["allocation"]) for r in items); proceeds = sum(float(r["net_proceeds"]) for r in items)
        return {"trade_count": len(items), "invested_capital": invested, "net_proceeds": proceeds, "net_profit": proceeds-invested, "roi": proceeds/invested-1 if invested else None, "xirr": xirr(flows), "early_etf_exits": sum(r["exit_reason"] == "etf_rotation_risk_off" for r in items)}
    with (a.output / "overlay_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(overlay[0]) if overlay else ["execution_date"]); w.writeheader(); w.writerows(overlay)
    with (a.output / "skipped_entries.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["execution_date", "reason"]); w.writeheader(); w.writerows(skipped)
    result = {"baseline_rank_1": summary(baseline), "overlay": summary(overlay), "skipped_months": len(skipped), "mapping_mode": "current_sector_theme_proxy; direct ETFs only after first available EOD observation", "errors": errors}
    (a.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n"); print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
