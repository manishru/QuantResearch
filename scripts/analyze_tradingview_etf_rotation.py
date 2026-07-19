#!/usr/bin/env python3
"""Build a price/volume rotation proxy for top-AUM TradingView ETFs using EODHD.

This measures price and volume leadership, not actual institutional flows.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import time
from datetime import date
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen


def value(text: str | None) -> float:
    return float(text) if text not in (None, '') else 0.0


def etf_description(row: dict[str, str]) -> str:
    """Return TradingView's ETF name from its serialized ticker-view field."""
    raw = row.get('ticker-view') or ''
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw
    return str(parsed.get('name') or parsed.get('description') or raw)


def exposure_type(description: str) -> str:
    """Classify ETF direction conservatively from the issuer product name."""
    name = description.lower()
    inverse_words = (' short ', ' bear ', ' inverse ', ' -1x', ' -2x', ' -3x')
    leverage_words = ('2x', '3x', ' leveraged', ' ultra', ' daily')
    padded = f' {name} '
    inverse = any(word in padded for word in inverse_words)
    leveraged = any(word in padded for word in leverage_words)
    if inverse:
        return 'inverse_leveraged' if leveraged else 'inverse'
    return 'long_leveraged' if leveraged else 'long'


def fetch(symbol: str, start: date | None, end: date | None, token: str) -> list[dict]:
    parameters = {'api_token': token, 'fmt': 'json'}
    if start:
        parameters['from'] = start.isoformat()
    if end:
        parameters['to'] = end.isoformat()
    query = urlencode(parameters)
    with urlopen(f'https://eodhd.com/api/eod/{symbol}?{query}', timeout=60) as response:
        data = json.loads(response.read())
    if isinstance(data, dict):
        raise RuntimeError(data.get('message') or str(data))
    return data


def load_or_fetch(symbol: str, cache: Path, start: date | None, end: date | None, refresh: bool, token: str | None, pause: float) -> tuple[list[dict], str]:
    file = cache / f'{symbol.replace(".", "_")}_{start or "all"}_{end or "latest"}.json'
    if file.exists() and not refresh:
        return json.loads(file.read_text()), 'cache'
    if not token:
        return [], 'missing_token'
    try:
        data = fetch(symbol, start, end, token)
        file.write_text(json.dumps(data))
        time.sleep(pause)
        return data, 'fetched'
    except Exception as error:
        return [], f'error: {error}'


def features(rows: list[dict], spy: dict[str, float], lookback: int) -> dict | None:
    rows = sorted((row for row in rows if row.get('adjusted_close') is not None), key=lambda row: row['date'])
    for i in range(len(rows) - 1, lookback - 1, -1):
        row = rows[i]; prior = rows[i - lookback]
        if row['date'] not in spy or prior['date'] not in spy:
            continue
        close, old_close = float(row['adjusted_close']), float(prior['adjusted_close'])
        volume_window = [float(item.get('volume') or 0) for item in rows[i - lookback:i] if float(item.get('volume') or 0) > 0]
        if not volume_window:
            continue
        etf_return = close / old_close - 1
        spy_return = spy[row['date']] / spy[prior['date']] - 1
        return {'date': row['date'], 'close': close, 'return': etf_return, 'spy_return': spy_return,
                'return_vs_spy': etf_return - spy_return, 'relative_volume': float(row.get('volume') or 0) / fmean(volume_window)}
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True, help='TradingView ETF snapshot CSV.')
    parser.add_argument('--from', dest='start', type=date.fromisoformat, help='Optional; omit to request all available EODHD history.')
    parser.add_argument('--to', type=date.fromisoformat, default=date.today(), help='Optional; defaults to today.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--top', type=int, default=50)
    parser.add_argument('--lookback-sessions', type=int, default=21)
    parser.add_argument('--min-relative-volume', type=float, default=1.2)
    parser.add_argument('--refresh', action='store_true', help='Download EODHD data even when a cache exists.')
    parser.add_argument('--token-env', default='EODHD_API_TOKEN')
    parser.add_argument('--pause-seconds', type=float, default=0.25)
    args = parser.parse_args()
    with args.snapshot.open(newline='', encoding='utf-8') as handle:
        input_rows = list(csv.DictReader(handle))
    selected = sorted(input_rows, key=lambda row: value(row.get('aum')), reverse=True)[:args.top]
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / 'raw_eodhd'; cache.mkdir(exist_ok=True)
    token = os.environ.get(args.token_env)
    # Keep the benchmark under a dedicated key.  SPY can also be one of the
    # selected ETFs; using "SPY" for both caused the benchmark and ETF row to
    # overwrite each other and could falsely report SPY.US as unavailable.
    benchmark_key = '__benchmark_spy__'
    symbols = [(benchmark_key, 'SPY.US')] + [
        (row['ticker'], f"{row['ticker'].replace('.', '-')}.US") for row in selected
    ]
    data: dict[str, list[dict]] = {}; status: dict[str, str] = {}
    for ticker, symbol in symbols:
        rows, source = load_or_fetch(symbol, cache, args.start, args.to, args.refresh, token, args.pause_seconds)
        data[ticker], status[ticker] = rows, source
    spy = {
        row['date']: float(row['adjusted_close'])
        for row in data[benchmark_key]
        if row.get('adjusted_close') is not None
    }
    report: list[dict] = []
    for row in selected:
        ticker = row['ticker']; result = features(data[ticker], spy, args.lookback_sessions)
        description = etf_description(row)
        report.append({'ticker': ticker, 'tv_symbol': row.get('tv_symbol'), 'etf_name': description,
                       'exposure_type': exposure_type(description), 'aum': value(row.get('aum')),
                       'focus': row.get('focus.tr'), 'expense_ratio': row.get('expense_ratio'),
                       'eodhd_symbol': f"{ticker.replace('.', '-')}.US", 'eodhd_status': status[ticker],
                       **(result or {})})
    valid = [row for row in report if row.get('return_vs_spy') is not None]
    for rank, row in enumerate(sorted(valid, key=lambda row: (row['return_vs_spy'], row['relative_volume']), reverse=True), 1):
        row['rotation_rank'] = rank
        leading = row['return_vs_spy'] > 0 and row['relative_volume'] >= args.min_relative_volume
        row['rotation_proxy'] = row['exposure_type'] == 'long' and leading
        # A rising inverse ETF is a bearish/risk-off proxy for its underlying
        # exposure. It must never be included among long rotation candidates.
        row['risk_off_proxy'] = row['exposure_type'].startswith('inverse') and leading
    fields = ['rotation_rank', 'rotation_proxy', 'risk_off_proxy', 'ticker', 'tv_symbol', 'etf_name', 'exposure_type', 'aum', 'focus', 'expense_ratio', 'eodhd_symbol', 'eodhd_status', 'date', 'close', 'return', 'spy_return', 'return_vs_spy', 'relative_volume']
    with (args.output / 'etf_rotation.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(sorted(report, key=lambda row: row.get('rotation_rank', 999999)))
    # A return relative to SPY of exactly 0.0 is valid (SPY itself has this
    # value).  Only a missing calculation belongs in this diagnostic list.
    missing = [row for row in report if row.get('return_vs_spy') is None]
    metadata = {'top_requested': args.top, 'etfs_selected': len(selected), 'lookback_sessions': args.lookback_sessions, 'min_relative_volume': args.min_relative_volume, 'valid_rotation_rows': len(valid), 'missing_or_unavailable': [{'ticker': row['ticker'], 'eodhd_symbol': row['eodhd_symbol'], 'status': row['eodhd_status']} for row in missing], 'limitation': 'Price/volume leadership is a rotation proxy, not confirmed institutional capital flow.'}
    (args.output / 'summary.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
