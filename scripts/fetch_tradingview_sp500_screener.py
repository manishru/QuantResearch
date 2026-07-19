#!/usr/bin/env python3
"""Fetch TradingView screener fields and retain point-in-time S&P 500 members.

TradingView's scanner endpoint is not a documented public API. This script is
for personal research, rate-limits requests, and saves an auditable snapshot.
It does not bypass login, paywalls, or access controls.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_COLUMNS = [
    'ticker-view', 'close', 'type', 'typespecs', 'pricescale', 'minmov',
    'fractional', 'minmove2', 'currency', 'change', 'Perf.W', 'Perf.1M',
    'Perf.3M', 'Perf.6M', 'Perf.YTD', 'Perf.Y', 'Perf.5Y', 'Perf.10Y',
    'Perf.All', 'Volatility.W', 'Volatility.M', 'sector.tr', 'market', 'sector',
]


def normalize(symbol: str) -> str:
    return symbol.upper().replace('-', '.').strip()


def sp500_members(path: Path, as_of: date) -> set[str]:
    members: set[str] = set()
    with path.open(newline='', encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle):
            if row['index_id'] != 'SP500':
                continue
            start = date.fromisoformat(row['effective_from'])
            end = date.fromisoformat(row['effective_to']) if row['effective_to'] else None
            if start <= as_of and (end is None or as_of <= end):
                members.add(normalize(row['constituent_symbol']))
    return members


def payload(columns: list[str], start: int, size: int) -> dict:
    return {
        'columns': columns,
        'filter': [{'left': 'is_primary', 'operation': 'equal', 'right': True}],
        'ignore_unknown_fields': False,
        'options': {'lang': 'en'},
        'range': [start, start + size],
        'sort': {'sortBy': 'Perf.Y', 'sortOrder': 'desc'},
        'markets': ['america'],
        'filter2': {
            'operator': 'and',
            'operands': [
                {'operation': {'operator': 'or', 'operands': [
                    {'operation': {'operator': 'and', 'operands': [
                        {'expression': {'left': 'type', 'operation': 'equal', 'right': 'stock'}},
                        {'expression': {'left': 'typespecs', 'operation': 'has', 'right': ['common']}},
                    ]}},
                    {'operation': {'operator': 'and', 'operands': [
                        {'expression': {'left': 'type', 'operation': 'equal', 'right': 'stock'}},
                        {'expression': {'left': 'typespecs', 'operation': 'has', 'right': ['preferred']}},
                    ]}},
                    {'operation': {'operator': 'and', 'operands': [
                        {'expression': {'left': 'type', 'operation': 'equal', 'right': 'dr'}},
                    ]}},
                    {'operation': {'operator': 'and', 'operands': [
                        {'expression': {'left': 'type', 'operation': 'equal', 'right': 'fund'}},
                        {'expression': {'left': 'typespecs', 'operation': 'has_none_of', 'right': ['etf', 'mutual']}},
                    ]}},
                ]}},
                {'expression': {'left': 'typespecs', 'operation': 'has_none_of', 'right': ['pre-ipo']}},
            ],
        },
    }


def fetch(body: dict, timeout: int) -> dict:
    request = Request(
        'https://scanner.tradingview.com/america/scan',
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'QuantResearch personal research'},
        method='POST',
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--membership-file', type=Path, default=Path('data/validated/sp500/eligible_membership_intervals.csv'))
    parser.add_argument('--page-size', type=int, default=500)
    parser.add_argument('--pause-seconds', type=float, default=0.5)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--max-rows', type=int, default=10000)
    parser.add_argument('--column', action='append', dest='columns', help='Add a TradingView field; repeatable.')
    args = parser.parse_args()
    if args.page_size < 1 or args.max_rows < 1:
        parser.error('page-size and max-rows must be positive')
    columns = DEFAULT_COLUMNS + [column for column in (args.columns or []) if column not in DEFAULT_COLUMNS]
    members = sp500_members(args.membership_file, args.as_of)
    records: list[dict] = []
    total_count = None
    for start in range(0, args.max_rows, args.page_size):
        response = fetch(payload(columns, start, args.page_size), args.timeout)
        total_count = response.get('totalCount', total_count)
        page = response.get('data') or []
        for item in page:
            values = item.get('d', [])
            row = {'tv_symbol': item.get('s', ''), 'ticker': '', 'sp500_member_as_of': False}
            row.update({column: values[index] if index < len(values) else None for index, column in enumerate(columns)})
            ticker_data = values[0] if values and isinstance(values[0], dict) else {}
            ticker = ticker_data.get('name') or item.get('s', '').split(':')[-1]
            row['ticker'] = normalize(ticker)
            row['sp500_member_as_of'] = row['ticker'] in members
            records.append(row)
        if not page or len(page) < args.page_size or (total_count is not None and start + args.page_size >= total_count):
            break
        time.sleep(args.pause_seconds)
    args.output.mkdir(parents=True, exist_ok=True)
    fields = ['tv_symbol', 'ticker', 'sp500_member_as_of', *columns]
    with (args.output / 'tradingview_america_snapshot.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    sp500_rows = [row for row in records if row['sp500_member_as_of']]
    with (args.output / 'tradingview_sp500_snapshot.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(sp500_rows)
    metadata = {'as_of': args.as_of.isoformat(), 'endpoint': 'https://scanner.tradingview.com/america/scan', 'columns': columns, 'market_rows': len(records), 'reported_total_count': total_count, 'sp500_rows': len(sp500_rows), 'membership_file': str(args.membership_file), 'limitation': 'TradingView scanner endpoint is undocumented and fields/availability may change.'}
    (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
