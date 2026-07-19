"""Read adjusted daily bars while preserving constituent identity."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import duckdb

from quantresearch.domain.mappings import ApprovalStatus, MappingRegistry
from quantresearch.simulation.models import Bar


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def approved_provider_to_constituent(
    registry: MappingRegistry, provider_id: str
) -> dict[str, str]:
    provider = provider_id.strip().upper()
    reverse: dict[str, str] = {}
    for mapping in registry.mappings:
        if (
            mapping.provider_id != provider
            or mapping.approval_status is not ApprovalStatus.APPROVED
        ):
            continue
        existing = reverse.get(mapping.provider_symbol)
        if existing is not None and existing != mapping.constituent_symbol:
            raise ValueError(
                f"Provider symbol {mapping.provider_symbol} maps to multiple constituents"
            )
        reverse[mapping.provider_symbol] = mapping.constituent_symbol
    return reverse


def load_adjusted_bars(
    parquet_path: Path,
    *,
    start: date,
    end: date,
    provider_to_constituent: dict[str, str] | None = None,
    included_provider_symbols: frozenset[str] | None = None,
) -> tuple[Bar, ...]:
    source = parquet_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Parquet file does not exist: {source}")
    if end < start:
        raise ValueError("end cannot precede start")
    connection = duckdb.connect(":memory:")
    try:
        if included_provider_symbols is not None:
            if not included_provider_symbols:
                return ()
            connection.execute("CREATE TEMP TABLE included_symbols(symbol VARCHAR PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO included_symbols VALUES (?)",
                [(symbol,) for symbol in sorted(included_provider_symbols)],
            )
            ticker_filter = "AND Ticker IN (SELECT symbol FROM included_symbols) "
        else:
            ticker_filter = ""
        rows = connection.execute(
            "SELECT Ticker, Date, Open, High, Low, Close, Volume "
            "FROM read_parquet(?) WHERE CAST(Date AS DATE) BETWEEN ? AND ? "
            + ticker_filter
            + "ORDER BY Ticker, CAST(Date AS DATE)",
            [str(source), start, end],
        ).fetchall()
    finally:
        connection.close()
    aliases = provider_to_constituent or {}
    return tuple(
        Bar(
            aliases.get(str(ticker).upper(), str(ticker).upper()),
            _as_date(observed),
            float(open_),
            float(high),
            float(low),
            float(close),
            float(volume),
        )
        for ticker, observed, open_, high, low, close, volume in rows
    )
