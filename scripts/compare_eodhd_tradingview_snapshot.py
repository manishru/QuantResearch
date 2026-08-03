#!/usr/bin/env python3
"""Compare a TradingView S&P 500 screener snapshot with EODHD EOD data."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import duckdb


def normalize(symbol: str) -> str:
    return symbol.upper().replace('-', '.').strip()


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


def pct_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or right == 0:
        return None
    return left / right - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tradingview-csv', type=Path, required=True)
    parser.add_argument('--date', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--price-tolerance-pct', type=float, default=0.005)
    parser.add_argument('--volume-tolerance-pct', type=float, default=0.10)
    args = parser.parse_args()

    with args.tradingview_csv.open(newline='', encoding='utf-8') as handle:
        tv_rows = [row for row in csv.DictReader(handle) if row.get('sp500_member_as_of', '').lower() == 'true']
    tv = {normalize(row['ticker']): row for row in tv_rows}
    connection = duckdb.connect()
    try:
        raw = connection.execute(
            '''SELECT UPPER(Ticker), Close, AdjustedClose, Volume
               FROM read_parquet(?) WHERE Date = ?''',
            [str(args.project_root.resolve() / 'data/validated/sp500/eod_adjusted_current.parquet'), args.date.isoformat()],
        ).fetchall()
    finally:
        connection.close()
    eodhd = {normalize(ticker): {'close': float(close), 'adjusted_close': float(adjusted), 'volume': float(volume)} for ticker, close, adjusted, volume in raw}

    compared: list[dict] = []
    for ticker in sorted(set(tv) | set(eodhd)):
        tv_row, eodhd_row = tv.get(ticker), eodhd.get(ticker)
        tv_close = number(tv_row.get('close')) if tv_row else None
        tv_volume = number(tv_row.get('volume')) if tv_row else None
        raw_close = eodhd_row['close'] if eodhd_row else None
        eodhd_volume = eodhd_row['volume'] if eodhd_row else None
        close_difference = pct_difference(tv_close, raw_close)
        volume_difference = pct_difference(tv_volume, eodhd_volume)
        if tv_row is None:
            status = 'missing_tradingview'
        elif eodhd_row is None:
            status = 'missing_eodhd'
        elif close_difference is not None and abs(close_difference) > args.price_tolerance_pct:
            status = 'price_difference_above_tolerance'
        elif volume_difference is not None and abs(volume_difference) > args.volume_tolerance_pct:
            status = 'volume_difference_above_tolerance'
        else:
            status = 'match_within_tolerance'
        compared.append({
            'ticker': ticker, 'status': status, 'tv_close': tv_close, 'eodhd_close': raw_close,
            'eodhd_adjusted_close': eodhd_row['adjusted_close'] if eodhd_row else None,
            'close_difference_pct': close_difference, 'tv_volume': tv_volume,
            'eodhd_volume': eodhd_volume, 'volume_difference_pct': volume_difference,
            'tv_symbol': tv_row.get('tv_symbol') if tv_row else '',
        })
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / 'tradingview_vs_eodhd.csv'
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(compared[0])); writer.writeheader(); writer.writerows(compared)
    counts: dict[str, int] = {}
    for row in compared:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    summary = {'date': args.date.isoformat(), 'tradingview_sp500_rows': len(tv), 'eodhd_rows': len(eodhd), 'comparison_rows': len(compared), 'status_counts': counts, 'price_tolerance_pct': args.price_tolerance_pct, 'volume_tolerance_pct': args.volume_tolerance_pct, 'comparison_csv': str(path), 'note': 'Raw EODHD Close is used for price comparison. AdjustedClose is retained for reference and should not be compared directly with TradingView close.'}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
