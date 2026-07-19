#!/usr/bin/env python3
"""Fetch the TradingView America ETF screener with optional AUM/index filters.

The scanner endpoint is undocumented and can change. This is a rate-limited
personal-research importer; it does not bypass authentication or controls.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_COLUMNS = [
    'ticker-view', 'close', 'type', 'typespecs', 'pricescale', 'minmov',
    'fractional', 'minmove2', 'currency', 'change', 'Value.Traded',
    'fundamental_currency_code', 'relative_volume_10d_calc', 'aum',
    'nav_total_return.3Y', 'etf_holdings_count', 'expense_ratio',
    'asset_class.tr', 'focus.tr',
]


def scanner_filter(aum_min: float | None, aum_max: float | None, index: str | None, asset_class: str | None, country: str | None, management_style: str | None) -> list[dict]:
    filters: list[dict] = []
    if aum_min is not None and aum_max is not None:
        filters.append({'left': 'aum', 'operation': 'in_range', 'right': [aum_min, aum_max]})
    elif aum_min is not None:
        filters.append({'left': 'aum', 'operation': 'greater', 'right': aum_min})
    elif aum_max is not None:
        filters.append({'left': 'aum', 'operation': 'less', 'right': aum_max})
    if index:
        filters.append({'left': 'index', 'operation': 'equal', 'right': index})
    if asset_class:
        filters.append({'left': 'asset_class', 'operation': 'equal', 'right': asset_class})
    if country:
        filters.append({'left': 'country', 'operation': 'equal', 'right': country})
    if management_style:
        filters.append({'left': 'management_style', 'operation': 'equal', 'right': management_style})
    return filters


def payload(columns: list[str], start: int, size: int, filters: list[dict]) -> dict:
    return {
        'columns': columns,
        'filter': filters,
        'ignore_unknown_fields': False,
        'options': {'lang': 'en'},
        'range': [start, start + size],
        'sort': {'sortBy': 'aum', 'sortOrder': 'desc'},
        'markets': ['america'],
        'filter2': {'operator': 'and', 'operands': [
            {'operation': {'operator': 'or', 'operands': [
                {'operation': {'operator': 'and', 'operands': [
                    {'expression': {'left': 'typespecs', 'operation': 'has', 'right': ['etf']}},
                ]}},
                {'operation': {'operator': 'and', 'operands': [
                    {'expression': {'left': 'type', 'operation': 'equal', 'right': 'structured'}},
                ]}},
            ]}},
        ]},
    }


def fetch(body: dict, timeout: int) -> dict:
    request = Request(
        'https://scanner.tradingview.com/america/scan', data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'QuantResearch personal research'}, method='POST',
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aum-min', type=float, help='Minimum AUM in USD; e.g. 1e9.')
    parser.add_argument('--aum-max', type=float, help='Maximum AUM in USD; e.g. 10e9.')
    parser.add_argument('--index', help='TradingView index field, e.g. SPX. Omit for all ETFs.')
    parser.add_argument('--asset-class', help='TradingView asset class code, e.g. equity.')
    parser.add_argument('--country', help='TradingView country code, e.g. US.')
    parser.add_argument('--management-style', help='TradingView management style code, e.g. active.')
    parser.add_argument('--page-size', type=int, default=500)
    parser.add_argument('--max-rows', type=int, default=10000)
    parser.add_argument('--pause-seconds', type=float, default=0.5)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--column', action='append', dest='columns')
    parser.add_argument('--columns-file', type=Path)
    args = parser.parse_args()
    if args.aum_min is not None and args.aum_max is not None and args.aum_min > args.aum_max:
        parser.error('--aum-min cannot exceed --aum-max')
    requested = list(args.columns or [])
    if args.columns_file:
        requested += [line.strip() for line in args.columns_file.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    columns = DEFAULT_COLUMNS + [column for column in requested if column not in DEFAULT_COLUMNS]
    filters = scanner_filter(args.aum_min, args.aum_max, args.index, args.asset_class, args.country, args.management_style)
    records: list[dict] = []; total_count = None
    for start in range(0, args.max_rows, args.page_size):
        response = fetch(payload(columns, start, args.page_size, filters), args.timeout)
        total_count = response.get('totalCount', total_count); page = response.get('data') or []
        for item in page:
            values = item.get('d', []); first = values[0] if values and isinstance(values[0], dict) else {}
            row = {'tv_symbol': item.get('s', ''), 'ticker': first.get('name') or item.get('s', '').split(':')[-1]}
            row.update({column: values[index] if index < len(values) else None for index, column in enumerate(columns)})
            records.append(row)
        if not page or len(page) < args.page_size or (total_count is not None and start + args.page_size >= total_count):
            break
        time.sleep(args.pause_seconds)
    args.output.mkdir(parents=True, exist_ok=True)
    fields = ['tv_symbol', 'ticker', *columns]
    with (args.output / 'tradingview_etf_snapshot.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    metadata = {'endpoint': 'https://scanner.tradingview.com/america/scan', 'rows': len(records), 'reported_total_count': total_count, 'filters': filters, 'columns': columns, 'limitation': 'TradingView scanner endpoint is undocumented; fields and filter values may change.'}
    (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
