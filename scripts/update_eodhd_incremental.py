#!/usr/bin/env python3
"""Incrementally fetch completed EODHD sessions into validated Parquet and DuckDB.

The source Parquet is treated as immutable.  A successful update publishes a new
validated Parquet file and then upserts only its fetched delta into DuckDB.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import polars as pl


REQUIRED_COLUMNS = (
    "Ticker", "Date", "Open", "High", "Low", "Close", "Volume",
    "RawOpen", "RawHigh", "RawLow", "RawClose", "AdjustedClose", "AdjustmentFactor",
)
DELTA_SCHEMA = {
    column: (pl.Utf8 if column in {"Ticker", "Date"} else pl.Int64 if column == "Volume" else pl.Float64)
    for column in REQUIRED_COLUMNS
}


def _fetch_json(provider_symbol: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch one bounded EODHD interval with retry, without logging a credential."""
    url = f"https://eodhd.com/api/eod/{provider_symbol}.US?{urlencode(params)}"
    for attempt in range(4):
        try:
            with urlopen(url, timeout=60) as response:  # noqa: S310 -- fixed HTTPS endpoint
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                raise ValueError(f"unexpected provider response: {payload.get('message', 'object')}")
            if not isinstance(payload, list):
                raise ValueError("unexpected provider response type")
            return payload
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == 3:
                raise RuntimeError(f"provider request failed: {type(error).__name__}") from error
            time.sleep(0.75 * (2**attempt))
    raise AssertionError("unreachable")


def _active_provider_symbols(
    intervals: Path, mappings: Path, as_of: date
) -> dict[str, str]:
    """Return provider symbol -> constituent symbol for active approved identities."""
    active: set[str] = set()
    with intervals.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            start = date.fromisoformat(row["effective_from"])
            end = date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None
            if start <= as_of and (end is None or as_of <= end):
                active.add(row["constituent_symbol"].strip().upper())
    approved: dict[str, tuple[date, str]] = {}
    with mappings.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["provider_id"].strip().upper() != "EODHD":
                continue
            if row["approval_status"].strip().lower() != "approved":
                continue
            constituent = row["constituent_symbol"].strip().upper()
            start = date.fromisoformat(row["effective_from"])
            end = date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None
            if constituent in active and start <= as_of and (end is None or as_of <= end):
                current = approved.get(constituent)
                if current is None or start > current[0]:
                    approved[constituent] = (start, row["provider_symbol"].strip().upper())
    result: dict[str, str] = {}
    for constituent in active:
        provider = approved.get(constituent, (date.min, constituent))[1]
        if provider in result and result[provider] != constituent:
            raise ValueError(f"Provider symbol collision: {provider}")
        result[provider] = constituent
    return result


def _latest_dates(parquet: Path) -> dict[str, date]:
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT UPPER(Ticker), MAX(CAST(Date AS DATE)) FROM read_parquet(?) GROUP BY 1",
            [str(parquet)],
        ).fetchall()
    finally:
        connection.close()
    return {str(ticker): observed for ticker, observed in rows}


def _normalize(provider_symbol: str, payload: list[dict[str, Any]]) -> pl.DataFrame:
    required = {"date", "open", "high", "low", "close", "adjusted_close", "volume"}
    rows: list[dict[str, object]] = []
    for item in payload:
        missing = required - set(item)
        if missing:
            raise ValueError(f"missing EODHD columns: {sorted(missing)}")
        try:
            observed = date.fromisoformat(str(item["date"]))
            raw_open, raw_high, raw_low, raw_close = (float(item[key]) for key in ("open", "high", "low", "close"))
            adjusted_close, volume = float(item["adjusted_close"]), float(item["volume"])
        except (TypeError, ValueError) as error:
            raise ValueError("provider returned non-numeric EOD value") from error
        if not (raw_open > 0 and raw_high > 0 and raw_low > 0 and raw_close > 0 and adjusted_close > 0 and volume >= 0):
            continue
        if raw_high < max(raw_open, raw_low, raw_close) or raw_low > min(raw_open, raw_high, raw_close):
            continue
        factor = adjusted_close / raw_close
        rows.append({"Ticker": provider_symbol, "Date": observed.isoformat(), "Open": raw_open * factor, "High": raw_high * factor, "Low": raw_low * factor, "Close": adjusted_close, "Volume": int(volume), "RawOpen": raw_open, "RawHigh": raw_high, "RawLow": raw_low, "RawClose": raw_close, "AdjustedClose": adjusted_close, "AdjustmentFactor": factor})
    return pl.DataFrame(rows, schema=DELTA_SCHEMA, strict=False).unique(subset=["Ticker", "Date"], keep="last")


def _sql_path(path: Path) -> str:
    """Return a safely quoted DuckDB string literal for a local file path."""
    return "'" + str(path).replace("'", "''") + "'"


def _publish_parquet(source: Path, delta_path: Path, output: Path) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "COPY ("
            "SELECT * EXCLUDE (priority, row_number) FROM ("
            " SELECT 0 AS priority, *, ROW_NUMBER() OVER (PARTITION BY Ticker, Date ORDER BY priority DESC) AS row_number"
            f" FROM (SELECT * FROM read_parquet({_sql_path(source)}) UNION ALL SELECT * FROM read_parquet({_sql_path(delta_path)}))"
            ") WHERE row_number=1 ORDER BY Ticker, Date"
            f") TO {_sql_path(temporary)} (FORMAT PARQUET)"
        )
    finally:
        connection.close()
    temporary.replace(output)


def _upsert_database(database: Path, output_parquet: Path, delta_path: Path, delta_rows: int, manifest: dict[str, Any]) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        connection.execute("BEGIN")
        exists = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='daily_adjusted_bars'"
        ).fetchone()[0]
        if not exists:
            connection.execute("CREATE TABLE daily_adjusted_bars AS SELECT * FROM read_parquet(?)", [str(output_parquet)])
        else:
            if delta_rows:
                connection.execute(
                    "DELETE FROM daily_adjusted_bars USING read_parquet(?) delta "
                    "WHERE daily_adjusted_bars.Ticker=delta.Ticker AND daily_adjusted_bars.Date=delta.Date",
                    [str(delta_path)],
                )
                connection.execute("INSERT INTO daily_adjusted_bars SELECT * FROM read_parquet(?)", [str(delta_path)])
        connection.execute(
            "CREATE TABLE IF NOT EXISTS market_data_update_runs (run_id VARCHAR, completed_at TIMESTAMP, manifest_json VARCHAR)"
        )
        connection.execute(
            "INSERT INTO market_data_update_runs VALUES (?, ?, ?)",
            [manifest["run_id"], datetime.now(timezone.utc), json.dumps(manifest, sort_keys=True)],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="Last completed provider EOD date")
    parser.add_argument("--source-parquet", type=Path)
    parser.add_argument("--output-parquet", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--request-delay-seconds", type=float, default=0.05)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print completed provider-request progress after this many symbols",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.request_delay_seconds < 0:
        parser.error("request-delay-seconds cannot be negative")
    if args.progress_every < 1:
        parser.error("progress-every must be positive")
    api_key = os.getenv("EODHD_API_KEY")
    if not args.dry_run and not api_key:
        parser.error("EODHD_API_KEY must be set in the environment")
    root = args.project_root.expanduser().resolve()
    source = (args.source_parquet or root / "data/raw/sp500/eod_final_1996-01-01_to_2026-07-12.parquet").resolve()
    output = (args.output_parquet or root / "data/validated/sp500/eod_adjusted_current.parquet").resolve()
    database = (args.database or root / "data/validated/sp500/market_data.duckdb").resolve()
    intervals = root / "data/validated/sp500/eligible_membership_intervals.csv"
    mappings = root / "data/validated/sp500/mapping_decisions_operator.csv"
    if not source.is_file() or not intervals.is_file() or not mappings.is_file():
        raise FileNotFoundError("source Parquet, membership intervals, and mapping decisions are required")
    symbols = _active_provider_symbols(intervals, mappings, args.as_of)
    # Once an incremental file has been published, it—not the immutable raw
    # seed—is the authoritative record of which sessions are already present.
    # Reading only ``source`` here made every later run re-fetch all sessions
    # added by previous incremental updates.
    planning_parquet = output if output.is_file() else source
    latest = _latest_dates(planning_parquet)
    plans = [
        {"provider_symbol": symbol, "constituent_symbol": constituent, "from": (latest.get(symbol, date.min) + timedelta(days=1)).isoformat(), "to": args.as_of.isoformat(), "latest": latest.get(symbol).isoformat() if latest.get(symbol) else None}
        for symbol, constituent in sorted(symbols.items())
        if latest.get(symbol) is None or latest[symbol] < args.as_of
    ]
    if args.dry_run:
        print(json.dumps({"source": str(source), "as_of": args.as_of.isoformat(), "active_symbols": len(symbols), "fetch_plans": plans}, indent=2))
        return
    print(
        f"Incremental update: {len(plans)} symbol(s), "
        f"as-of {args.as_of.isoformat()}; no data is published until every fetch succeeds.",
        flush=True,
    )
    frames: list[pl.DataFrame] = []
    report: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        try:
            payload = _fetch_json(plan["provider_symbol"], {"from": plan["from"], "to": plan["to"], "period": "d", "order": "a", "api_token": api_key or "", "fmt": "json"})
            frame = _normalize(plan["provider_symbol"], payload)
            frame = frame.filter((pl.col("Date") >= plan["from"]) & (pl.col("Date") <= plan["to"]))
            if frame.height:
                frames.append(frame)
            report.append({**plan, "status": "fetched" if frame.height else "no_market_rows", "rows": frame.height, "error": ""})
        except (RuntimeError, ValueError) as error:
            report.append({**plan, "status": "failed", "rows": 0, "error": str(error)})
            print(
                f"[{index}/{len(plans)}] FAILED {plan['provider_symbol']}: {type(error).__name__}",
                flush=True,
            )
        else:
            if index % args.progress_every == 0 or index == len(plans):
                latest_report = report[-1]
                print(
                    f"[{index}/{len(plans)}] fetched through {plan['provider_symbol']}; "
                    f"latest rows={latest_report['rows']}",
                    flush=True,
                )
        time.sleep(args.request_delay_seconds)
    failures = [row for row in report if row["status"] == "failed"]
    if failures:
        raise RuntimeError(f"{len(failures)} provider fetches failed; no data was published")
    delta = pl.concat(frames) if frames else pl.DataFrame(schema=DELTA_SCHEMA)
    output.parent.mkdir(parents=True, exist_ok=True)
    delta_path = output.with_suffix(output.suffix + ".delta.tmp.parquet")
    delta.write_parquet(delta_path)
    _publish_parquet(source if not output.exists() else output, delta_path, output)
    run_id = datetime.now(timezone.utc).strftime("eodhd_incremental_%Y%m%dT%H%M%SZ")
    manifest = {"run_id": run_id, "as_of": args.as_of.isoformat(), "source_parquet": str(source), "planning_parquet": str(planning_parquet), "output_parquet": str(output), "database": str(database), "active_symbols": len(symbols), "planned_symbols": len(plans), "rows_added": delta.height, "min_added_date": delta.get_column("Date").min() if delta.height else None, "max_added_date": delta.get_column("Date").max() if delta.height else None, "report": report}
    _upsert_database(database, output, delta_path, delta.height, manifest)
    delta_path.unlink(missing_ok=True)
    report_path = output.parent / f"{run_id}_report.json"
    report_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("All fetches succeeded; publishing validated Parquet and DuckDB update completed.", flush=True)
    print(json.dumps({**manifest, "report_path": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
