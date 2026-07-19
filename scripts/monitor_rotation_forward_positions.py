#!/usr/bin/env python3
"""Track research-only rotation candidates after entry using completed EOD data.

Stores the actual constituent entry open once the entry session is in the local
S&P 500 parquet. The parent ETF exit is the tested rule: ETF drawdown from its
post-entry peak >= threshold, negative 21-session return relative to SPY, and
relative volume >= threshold. An exit signal is actionable only at the next
market-session open; this script never submits orders.
"""
from __future__ import annotations

import argparse, csv, json, os
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb


def fetch(symbol: str, start: date, end: date, token: str) -> list[dict[str, object]]:
    query = urlencode({"from": start.isoformat(), "to": end.isoformat(), "api_token": token, "fmt": "json"})
    with urlopen(f"https://eodhd.com/api/eod/{symbol}?{query}", timeout=60) as response:  # noqa: S310
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"unexpected EODHD response for {symbol}")
    return value


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader(); writer.writerows(rows)


def next_weekday(value: date) -> date:
    value += timedelta(days=1)
    while value.weekday() > 4: value += timedelta(days=1)
    return value


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--entry-date", type=date.fromisoformat, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--rotation-drawdown", type=float, default=.10)
    p.add_argument("--min-relative-volume", type=float, default=1.0)
    p.add_argument("--token-env", default="EODHD_API_TOKEN")
    p.add_argument("--refresh-etfs", action="store_true")
    a = p.parse_args()
    if a.as_of < a.entry_date or not 0 < a.rotation_drawdown < 1 or a.min_relative_volume <= 0: p.error("invalid dates or exit thresholds")
    root, out = a.project_root.resolve(), a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    with a.candidates.open(newline="", encoding="utf-8") as f: candidates = list(csv.DictReader(f))
    if not candidates: p.error("candidate CSV is empty")
    parquet = root / "data/validated/sp500/eod_adjusted_current.parquet"
    if not parquet.is_file(): raise FileNotFoundError(parquet)
    token = os.environ.get(a.token_env)
    if not token: p.error(f"set {a.token_env}; it is not accepted as a command-line argument")

    etfs = sorted({row["etf"] for row in candidates} | {"SPY.US"})
    raw = out / "raw_eodhd"; raw.mkdir(exist_ok=True)
    market: dict[str, list[dict[str, object]]] = {}
    for symbol in etfs:
        path = raw / f"{symbol.replace('.', '_')}_{a.entry_date - timedelta(days=120)}_{a.as_of}.json"
        if a.refresh_etfs or not path.exists(): path.write_text(json.dumps(fetch(symbol, a.entry_date - timedelta(days=120), a.as_of, token)) + "\n")
        market[symbol] = json.loads(path.read_text())
    spy = {str(row["date"]): row for row in market["SPY.US"]}

    con = duckdb.connect(":memory:")
    try:
        tickers = sorted({row["ticker"] for row in candidates}); placeholders = ",".join("?" for _ in tickers)
        records = con.execute(f"""SELECT UPPER(Ticker), CAST(Date AS DATE), RawOpen, RawClose
          FROM read_parquet(?) WHERE UPPER(Ticker) IN ({placeholders}) AND CAST(Date AS DATE)<=? ORDER BY 1,2""",
          [str(parquet), *tickers, a.as_of]).fetchall()
    finally: con.close()
    prices = {(ticker, observed): (float(opening or 0), float(close or 0)) for ticker, observed, opening, close in records}
    result=[]
    for candidate in candidates:
        ticker, etf = candidate["ticker"], candidate["etf"]
        entry = prices.get((ticker, a.entry_date)); last_dates = sorted(d for t,d in prices if t == ticker and d <= a.as_of)
        last_day = last_dates[-1] if last_dates else None; last = prices.get((ticker,last_day)) if last_day else None
        etf_rows = market[etf]; index = next((i for i,row in enumerate(etf_rows) if row["date"] == a.entry_date.isoformat()), None)
        signal=False; dd=rel=rv=None; observed=None
        if index is not None and len(etf_rows) > index:
            current_index=len(etf_rows)-1; current=etf_rows[current_index]; observed=date.fromisoformat(str(current["date"]))
            peak=max(float(row["adjusted_close"]) for row in etf_rows[index:current_index+1])
            dd=float(current["adjusted_close"])/peak-1
            if current_index >= 21 and str(current["date"]) in spy and str(etf_rows[current_index-21]["date"]) in spy:
                rel=float(current["adjusted_close"])/float(etf_rows[current_index-21]["adjusted_close"])-float(spy[str(current["date"])]["adjusted_close"])/float(spy[str(etf_rows[current_index-21]["date"])]["adjusted_close"])
                vols=[float(row["volume"]) for row in etf_rows[current_index-21:current_index] if float(row["volume"])>0]
                rv=float(current["volume"])/fmean(vols) if vols else 0
                signal=rel < 0 and rv >= a.min_relative_volume and dd <= -a.rotation_drawdown
        result.append({**candidate, "entry_date":a.entry_date.isoformat(), "actual_entry_raw_open": entry[0] if entry else "pending_local_price_update", "latest_constituent_date":last_day.isoformat() if last_day else "", "latest_raw_close":last[1] if last else "", "constituent_return_since_entry":(last[1]/entry[0]-1) if entry and last else "", "etf_monitor_date":observed.isoformat() if observed else "", "etf_drawdown_from_peak":dd, "etf_relative_strength_21d":rel, "etf_relative_volume":rv, "exit_signal":signal, "exit_target":"next_market_session_open" if signal else "", "exit_target_date":next_weekday(observed).isoformat() if signal and observed else ""})
    headers=list(result[0]); write_csv(out/'positions.csv',result,headers)
    history=out/'monitor_history.csv'; existing=[]
    if history.exists():
        with history.open(newline="",encoding="utf-8") as f: existing=list(csv.DictReader(f))
    existing=[r for r in existing if not (r.get('monitor_as_of')==a.as_of.isoformat())]
    existing.extend({"monitor_as_of":a.as_of.isoformat(),**r} for r in result)
    write_csv(history,existing,["monitor_as_of",*headers])
    print(json.dumps({"as_of":a.as_of.isoformat(),"positions":result,"positions_csv":str(out/'positions.csv'),"history_csv":str(history),"research_only":True},indent=2,default=str))

if __name__=='__main__': main()
