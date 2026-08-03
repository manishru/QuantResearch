#!/usr/bin/env python3
"""Store EODHD intraday bars for a point-in-time S&P 500 universe in DuckDB.

The script deliberately writes to a separate database from the validated daily
bars.  EODHD timestamps are normalised to UTC and classified using the New York
session clock, so pre-market, regular-market, and after-hours rows remain
separately queryable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import duckdb


NY = ZoneInfo("America/New_York")
UTC = timezone.utc
MAX_1M_DAYS = 120
MAX_5M_DAYS = 600
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS intraday_bars (
    constituent_symbol VARCHAR NOT NULL,
    provider_symbol VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    provider_timestamp BIGINT NOT NULL,
    observed_at_utc TIMESTAMPTZ NOT NULL,
    observed_at_ny TIMESTAMPTZ NOT NULL,
    trade_date DATE NOT NULL,
    session VARCHAR NOT NULL CHECK (session IN ('pre_market', 'regular', 'after_hours', 'off_session')),
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT,
    gmtoffset_seconds INTEGER,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    source_window_from_utc TIMESTAMPTZ NOT NULL,
    source_window_to_utc TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (provider_symbol, interval, provider_timestamp)
);

CREATE TABLE IF NOT EXISTS intraday_fetch_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at_utc TIMESTAMPTZ NOT NULL,
    completed_at_utc TIMESTAMPTZ,
    universe_date DATE NOT NULL,
    requested_start_utc TIMESTAMPTZ NOT NULL,
    requested_end_utc TIMESTAMPTZ NOT NULL,
    interval VARCHAR NOT NULL,
    symbols_requested INTEGER NOT NULL,
    symbols_succeeded INTEGER NOT NULL DEFAULT 0,
    rows_written BIGINT NOT NULL DEFAULT 0,
    errors_json VARCHAR NOT NULL DEFAULT '[]'
);

-- A successful request is recorded even when EODHD returned no executable
-- bars, which makes a later --resume run safe and cheap.
CREATE TABLE IF NOT EXISTS intraday_fetch_windows (
    provider_symbol VARCHAR NOT NULL,
    constituent_symbol VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    session_scope VARCHAR NOT NULL,
    window_start_utc TIMESTAMPTZ NOT NULL,
    window_end_utc TIMESTAMPTZ NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    rows_written BIGINT NOT NULL,
    PRIMARY KEY (provider_symbol, interval, session_scope, window_start_utc, window_end_utc)
);

CREATE OR REPLACE VIEW intraday_pre_market AS
SELECT * FROM intraday_bars WHERE session = 'pre_market';
CREATE OR REPLACE VIEW intraday_regular_market AS
SELECT * FROM intraday_bars WHERE session = 'regular';
CREATE OR REPLACE VIEW intraday_after_hours AS
SELECT * FROM intraday_bars WHERE session = 'after_hours';

CREATE OR REPLACE VIEW intraday_hybrid_5m_regular_1m_extended AS
SELECT * FROM intraday_bars
WHERE (session = 'regular' AND interval = '5m')
   OR (session IN ('pre_market', 'after_hours') AND interval = '1m');
"""


def parse_utc_day(value: str, *, end: bool = False) -> datetime:
    """Parse YYYY-MM-DD as a UTC boundary; end is the beginning of next day."""
    parsed = date.fromisoformat(value)
    return datetime.combine(parsed + (timedelta(days=1) if end else timedelta()), clock_time.min, tzinfo=UTC)


def classify_session(observed_at_utc: datetime) -> tuple[datetime, str]:
    """Return New York timestamp and the session for a one-minute bar start."""
    observed_at_ny = observed_at_utc.astimezone(NY)
    local_time = observed_at_ny.timetz().replace(tzinfo=None)
    if clock_time(4, 0) <= local_time < clock_time(9, 30):
        return observed_at_ny, "pre_market"
    if clock_time(9, 30) <= local_time < clock_time(16, 0):
        return observed_at_ny, "regular"
    if clock_time(16, 0) <= local_time < clock_time(20, 0):
        return observed_at_ny, "after_hours"
    return observed_at_ny, "off_session"


def active_provider_symbols(intervals: Path, mappings: Path, universe_date: date) -> list[tuple[str, str]]:
    """Resolve the approved EODHD symbol for every constituent active that day."""
    active: set[str] = set()
    with intervals.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            start = date.fromisoformat(row["effective_from"])
            end = date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None
            if start <= universe_date and (end is None or universe_date <= end):
                active.add(row["constituent_symbol"].strip().upper())
    approved: dict[str, tuple[date, str]] = {}
    with mappings.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["provider_id"].strip().upper() != "EODHD" or row["approval_status"].strip().lower() != "approved":
                continue
            constituent = row["constituent_symbol"].strip().upper()
            start = date.fromisoformat(row["effective_from"])
            end = date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None
            if constituent in active and start <= universe_date and (end is None or universe_date <= end):
                previous = approved.get(constituent)
                if previous is None or start > previous[0]:
                    approved[constituent] = (start, row["provider_symbol"].strip().upper())
    return sorted((approved.get(symbol, (date.min, symbol))[1], symbol) for symbol in active)


def historical_provider_segments(
    intervals: Path, mappings: Path, start: datetime, end: datetime
) -> list[tuple[str, str, datetime, datetime]]:
    """Return only periods where both S&P membership and an EODHD alias were valid.

    Membership and mapping end dates are inclusive.  Internally we convert them
    to exclusive UTC boundaries, which avoids duplicate bars at an interval
    change or a symbol rename.
    """
    membership_rows: list[tuple[str, date, date | None]] = []
    with intervals.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            membership_rows.append((
                row["constituent_symbol"].strip().upper(),
                date.fromisoformat(row["effective_from"]),
                date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None,
            ))
    mapping_rows: dict[str, list[tuple[str, date, date | None]]] = {}
    with mappings.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["provider_id"].strip().upper() != "EODHD" or row["approval_status"].strip().lower() != "approved":
                continue
            mapping_rows.setdefault(row["constituent_symbol"].strip().upper(), []).append((
                row["provider_symbol"].strip().upper(),
                date.fromisoformat(row["effective_from"]),
                date.fromisoformat(row["effective_to"]) if row["effective_to"].strip() else None,
            ))
    segments: list[tuple[str, str, datetime, datetime]] = []
    for constituent, member_start, member_end in membership_rows:
        member_stop_date = (member_end + timedelta(days=1)) if member_end else date.max
        relevant_mappings = mapping_rows.get(constituent, [])
        # A mapping-decision file normally records only exceptional aliases.
        # Therefore the default is the constituent symbol itself; a dated
        # approved mapping overrides it only within its own effective range.
        boundaries = {member_start, member_stop_date}
        for _, map_start, map_end in relevant_mappings:
            if member_start < map_start < member_stop_date:
                boundaries.add(map_start)
            map_stop_date = (map_end + timedelta(days=1)) if map_end else date.max
            if member_start < map_stop_date < member_stop_date:
                boundaries.add(map_stop_date)
        ordered = sorted(boundaries)
        for period_start_date, period_end_date in zip(ordered, ordered[1:]):
            matching = [mapping for mapping in relevant_mappings if mapping[1] <= period_start_date and (mapping[2] is None or period_start_date <= mapping[2])]
            provider = max(matching, key=lambda mapping: mapping[1])[0] if matching else constituent
            period_start = max(start, datetime.combine(period_start_date, clock_time.min, tzinfo=UTC))
            period_end = min(end, datetime.combine(period_end_date, clock_time.min, tzinfo=UTC))
            if period_start < period_end:
                segments.append((provider, constituent, period_start, period_end))
    return sorted(segments)


def worker_for(constituent_symbol: str, partition_count: int) -> int:
    """Return a stable worker number; never use Python's randomized hash()."""
    return int.from_bytes(hashlib.sha256(constituent_symbol.encode("utf-8")).digest()[:8], "big") % partition_count


def windows(start: datetime, end: datetime, interval: str, five_minute_days: int = MAX_5M_DAYS) -> list[tuple[datetime, datetime]]:
    """Split the requested range into API-safe, non-overlapping UTC windows."""
    # EODHD permits 120 days for 1m and 600 days for 5m requests.  Using the
    # documented 5m maximum reduces request count and API quota consumption.
    max_days = MAX_1M_DAYS if interval == "1m" else five_minute_days if interval == "5m" else 7200
    result: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=max_days), end)
        result.append((cursor, window_end))
        cursor = window_end
    return result


def fetch(provider_symbol: str, interval: str, start: datetime, end: datetime, token: str) -> list[dict[str, Any]]:
    params = {
        "api_token": token,
        "interval": interval,
        "from": str(int(start.timestamp())),
        "to": str(int(end.timestamp())),
        "fmt": "json",
    }
    url = f"https://eodhd.com/api/intraday/{provider_symbol}.US?{urlencode(params)}"
    for attempt in range(4):
        try:
            with urlopen(url, timeout=90) as response:  # noqa: S310: fixed HTTPS provider endpoint
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                raise ValueError(payload.get("message", "unexpected EODHD object response"))
            if not isinstance(payload, list):
                raise ValueError("unexpected EODHD response type")
            return payload
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == 3:
                raise RuntimeError(f"{provider_symbol}: {type(error).__name__}") from error
            time.sleep(1.0 * (2**attempt))
    raise AssertionError("unreachable")


def normalise(payload: list[dict[str, Any]], provider_symbol: str, constituent_symbol: str, interval: str, start: datetime, end: datetime, fetched_at: datetime, allowed_sessions: set[str] | None = None) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in payload:
        try:
            timestamp = int(item["timestamp"])
            observed_at_utc = datetime.fromtimestamp(timestamp, tz=UTC)
            if not start <= observed_at_utc < end:
                continue
            values = tuple(float(item[field]) for field in ("open", "high", "low", "close"))
            volume = int(float(item.get("volume") or 0))
            if min(values) <= 0 or volume < 0:
                continue
        except (KeyError, TypeError, ValueError, OSError):
            continue
        observed_at_ny, session = classify_session(observed_at_utc)
        if allowed_sessions is not None and session not in allowed_sessions:
            continue
        rows.append((constituent_symbol, provider_symbol, interval, timestamp, observed_at_utc, observed_at_ny,
                     observed_at_ny.date(), session, *values, volume, int(item.get("gmtoffset") or 0),
                     fetched_at, start, end))
    return rows


def session_scope(allowed_sessions: set[str] | None) -> str:
    """Stable identifier for a request's session filter."""
    return "all" if allowed_sessions is None else ",".join(sorted(allowed_sessions))


def request_key(request: tuple[str, str, datetime, datetime, str, set[str] | None]) -> tuple[str, str, str, datetime, datetime]:
    """Key used to identify a completed provider request window."""
    provider, _, window_start, window_end, interval, allowed_sessions = request
    return provider, interval, session_scope(allowed_sessions), window_start, window_end


def duckdb_configuration(memory_limit: str, threads: int, temp_directory: Path) -> dict[str, str]:
    """Return safe bounded-memory settings for a long-running single writer."""
    if not re.fullmatch(r"\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB)", memory_limit.strip(), flags=re.IGNORECASE):
        raise ValueError("duckdb memory limit must look like 2GB or 512MB")
    if threads < 1:
        raise ValueError("duckdb threads must be positive")
    temp_directory.mkdir(parents=True, exist_ok=True)
    return {
        "memory_limit": memory_limit,
        "threads": str(threads),
        "temp_directory": str(temp_directory),
        "preserve_insertion_order": "false",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--membership", type=Path)
    parser.add_argument("--mappings", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--universe-date", type=date.fromisoformat, required=True, help="Point-in-time S&P 500 membership date")
    parser.add_argument("--start", required=True, help="UTC start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="UTC end date, YYYY-MM-DD (inclusive)")
    parser.add_argument("--interval", choices=("1m", "5m", "1h"), default="1m")
    parser.add_argument("--five-minute-window-days", type=int, default=MAX_5M_DAYS, help="EODHD 5m request window size (maximum 600). Use 365 when resuming a legacy worker run.")
    parser.add_argument("--hybrid-5m-regular-1m-extended", action="store_true", help="Store 5m regular bars and 1m pre-market/after-hours bars only.")
    parser.add_argument(
        "--historical-membership",
        action="store_true",
        help="Use every eligible point-in-time membership and EODHD alias period overlapping start/end."
    )
    parser.add_argument("--symbols", nargs="*", help="Optional constituent ticker subset, e.g. NVDA MSFT")
    parser.add_argument("--max-symbols", type=int, help="Safety cap for a pilot run")
    parser.add_argument("--partition-count", type=int, default=1, help="Number of disjoint worker partitions")
    parser.add_argument("--partition-index", type=int, default=0, help="Zero-based worker number")
    parser.add_argument("--request-delay-seconds", type=float, default=0.25)
    parser.add_argument("--fetch-workers", type=int, default=1, help="Concurrent EODHD requests within this database writer; use 2 for a repair/resume run.")
    parser.add_argument("--write-batch-requests", type=int, default=1, help="Successful API windows to commit in one DuckDB transaction.")
    parser.add_argument("--duckdb-memory-limit", default="2GB", help="Bound DuckDB working memory; larger state spills to --duckdb-temp-directory.")
    parser.add_argument("--duckdb-threads", type=int, default=1, help="DuckDB execution threads for this one-writer process.")
    parser.add_argument("--duckdb-temp-directory", type=Path, help="Disk workspace for DuckDB spill files; defaults beside --database.")
    parser.add_argument("--resume", action="store_true", help="Skip request windows already recorded or already present in this database.")
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--token-env", default="EODHD_API_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.request_delay_seconds < 0 or args.progress_every < 1 or args.fetch_workers < 1 or args.write_batch_requests < 1 or not 1 <= args.five_minute_window_days <= MAX_5M_DAYS:
        parser.error("invalid runtime option; five-minute-window-days must be between 1 and 600")
    if args.partition_count < 1 or not 0 <= args.partition_index < args.partition_count:
        parser.error("partition-index must be between 0 and partition-count - 1")
    if args.hybrid_5m_regular_1m_extended and args.interval != "5m":
        parser.error("hybrid mode requires --interval 5m because regular-session bars are five-minute")
    start, end = parse_utc_day(args.start), parse_utc_day(args.end, end=True)
    if start >= end:
        parser.error("end must be on or after start")
    root = args.project_root.expanduser().resolve()
    membership = (args.membership or root / "data/validated/sp500/eligible_membership_intervals.csv").resolve()
    mappings = (args.mappings or root / "data/validated/sp500/mapping_decisions_operator.csv").resolve()
    database = (args.database or root / "data/validated/sp500/intraday.duckdb").resolve()
    temp_directory = (args.duckdb_temp_directory or database.parent / f"{database.stem}_tmp").expanduser().resolve()
    if not membership.is_file() or not mappings.is_file():
        raise FileNotFoundError("membership intervals and approved EODHD mapping decisions are required")
    symbols = active_provider_symbols(membership, mappings, args.universe_date)
    wanted = {symbol.upper() for symbol in args.symbols} if args.symbols else None
    if wanted is not None:
        symbols = [pair for pair in symbols if pair[1] in wanted]
        missing = sorted(wanted - {constituent for _, constituent in symbols})
        if missing:
            parser.error(f"not active in the selected universe: {', '.join(missing)}")
    if args.historical_membership:
        segments = historical_provider_segments(membership, mappings, start, end)
        if wanted is not None:
            segments = [segment for segment in segments if segment[1] in wanted]
        if args.max_symbols is not None:
            permitted = {constituent for _, constituent in sorted({(provider, constituent) for provider, constituent, _, _ in segments})[:args.max_symbols]}
            segments = [segment for segment in segments if segment[1] in permitted]
    else:
        if args.max_symbols is not None:
            symbols = symbols[:args.max_symbols]
        segments = [(provider, constituent, start, end) for provider, constituent in symbols]
    if args.partition_count > 1:
        segments = [segment for segment in segments if worker_for(segment[1], args.partition_count) == args.partition_index]
    if args.hybrid_5m_regular_1m_extended:
        requests = [
            (provider, constituent, window_start, window_end, source_interval, allowed_sessions)
            for provider, constituent, segment_start, segment_end in segments
            for source_interval, allowed_sessions in (("5m", {"regular"}), ("1m", {"pre_market", "after_hours"}))
            for window_start, window_end in windows(segment_start, segment_end, source_interval, args.five_minute_window_days)
        ]
        run_interval = "hybrid_5m_regular_1m_extended"
    else:
        requests = [
            (provider, constituent, window_start, window_end, args.interval, None)
            for provider, constituent, segment_start, segment_end in segments
            for window_start, window_end in windows(segment_start, segment_end, args.interval, args.five_minute_window_days)
        ]
        run_interval = args.interval
    if args.dry_run:
        print(json.dumps({"symbols": len({constituent for _, constituent, _, _ in segments}), "membership_segments": len(segments), "api_requests": len(requests), "partition": f"{args.partition_index}/{args.partition_count}", "five_minute_window_days": args.five_minute_window_days, "fetch_workers": args.fetch_workers, "write_batch_requests": args.write_batch_requests, "resume": args.resume, "sample_requests": [(provider, constituent, interval, sorted(sessions) if sessions else "all", a.isoformat(), b.isoformat()) for provider, constituent, a, b, interval, sessions in requests[:5]], "database": str(database)}, indent=2))
        return
    token = os.getenv(args.token_env) or os.getenv("EODHD_API_KEY")
    if not token:
        parser.error(f"set {args.token_env} (or EODHD_API_KEY); do not put credentials on the command line")
    database.parent.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("intraday-%Y%m%dT%H%M%SZ")
    started = datetime.now(UTC)
    errors: list[dict[str, str]] = []
    succeeded = rows_written = 0
    connection = duckdb.connect(str(database), config=duckdb_configuration(args.duckdb_memory_limit, args.duckdb_threads, temp_directory))
    try:
        connection.execute(SCHEMA_SQL)
        skipped_windows = 0
        if args.resume:
            completed = set(connection.execute(
                "SELECT provider_symbol, interval, session_scope, window_start_utc, window_end_utc FROM intraday_fetch_windows"
            ).fetchall())
            # Databases written before intraday_fetch_windows existed are still
            # resumable when a stored bar proves that its request succeeded.
            completed.update(connection.execute(
                "SELECT DISTINCT provider_symbol, interval, 'all', source_window_from_utc, source_window_to_utc FROM intraday_bars"
            ).fetchall())
            completed.update(connection.execute(
                "SELECT DISTINCT provider_symbol, interval, CASE WHEN interval='5m' THEN 'regular' ELSE 'after_hours,pre_market' END, source_window_from_utc, source_window_to_utc FROM intraday_bars"
            ).fetchall())
            pending_requests = [request for request in requests if request_key(request) not in completed]
            skipped_windows = len(requests) - len(pending_requests)
        else:
            pending_requests = requests
        connection.execute("INSERT INTO intraday_fetch_runs (run_id, started_at_utc, universe_date, requested_start_utc, requested_end_utc, interval, symbols_requested) VALUES (?, ?, ?, ?, ?, ?, ?)", [run_id, started, args.universe_date, start, end, run_interval, len({constituent for _, constituent, _, _ in segments})])
        succeeded_symbols: set[str] = set()
        def retrieve(request: tuple[str, str, datetime, datetime, str, set[str] | None]) -> tuple[tuple[str, str, datetime, datetime, str, set[str] | None], list[tuple[Any, ...]], datetime]:
            provider_symbol, constituent_symbol, window_start, window_end, source_interval, allowed_sessions = request
            fetched_at = datetime.now(UTC)
            payload = fetch(provider_symbol, source_interval, window_start, window_end, token)
            rows = normalise(payload, provider_symbol, constituent_symbol, source_interval, window_start, window_end, fetched_at, allowed_sessions)
            time.sleep(args.request_delay_seconds)
            return request, rows, fetched_at

        total = len(pending_requests)
        if args.resume:
            print(f"resume: skipped_windows={skipped_windows} pending_windows={total}", flush=True)
        with ThreadPoolExecutor(max_workers=args.fetch_workers) as pool:
            for batch_start in range(0, total, args.write_batch_requests):
                batch = pending_requests[batch_start:batch_start + args.write_batch_requests]
                futures = {pool.submit(retrieve, request): request for request in batch}
                successful: list[tuple[tuple[str, str, datetime, datetime, str, set[str] | None], list[tuple[Any, ...]], datetime]] = []
                for future in as_completed(futures):
                    request = futures[future]
                    provider_symbol, constituent_symbol, window_start, window_end, source_interval, _ = request
                    try:
                        successful.append(future.result())
                    except Exception as error:  # Keep the remaining universe resumable.
                        detail = {"provider_symbol": provider_symbol, "constituent_symbol": constituent_symbol, "interval": source_interval, "window_start": window_start.isoformat(), "window_end": window_end.isoformat(), "error": f"{type(error).__name__}: {error}"}
                        errors.append(detail)
                        print(f"REQUEST ERROR [{batch_start + len(successful) + len(errors)}/{total}] {json.dumps(detail)}", flush=True)
                if successful:
                    connection.execute("BEGIN")
                    try:
                        for request, symbol_rows, fetched_at in successful:
                            provider_symbol, constituent_symbol, window_start, window_end, source_interval, allowed_sessions = request
                            if symbol_rows:
                                connection.executemany("INSERT OR REPLACE INTO intraday_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", symbol_rows)
                            connection.execute(
                                "INSERT OR REPLACE INTO intraday_fetch_windows VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                [provider_symbol, constituent_symbol, source_interval, session_scope(allowed_sessions), window_start, window_end, fetched_at, len(symbol_rows)],
                            )
                            succeeded_symbols.add(constituent_symbol)
                            rows_written += len(symbol_rows)
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
                completed_count = min(batch_start + len(batch), total)
                if completed_count % args.progress_every == 0 or completed_count == total:
                    print(f"[{completed_count}/{total}] succeeded_symbols={len(succeeded_symbols)} rows_written={rows_written} errors={len(errors)}", flush=True)
        succeeded = len(succeeded_symbols)
        connection.execute("UPDATE intraday_fetch_runs SET completed_at_utc=?, symbols_succeeded=?, rows_written=?, errors_json=? WHERE run_id=?", [datetime.now(UTC), succeeded, rows_written, json.dumps(errors), run_id])
    finally:
        connection.close()
    print(json.dumps({"run_id": run_id, "database": str(database), "symbols_requested": len({constituent for _, constituent, _, _ in segments}), "windows_skipped": skipped_windows if args.resume else 0, "windows_attempted": len(pending_requests), "symbols_succeeded": succeeded, "rows_written": rows_written, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
