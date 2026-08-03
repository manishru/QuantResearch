#!/usr/bin/env python3
"""Stateful ETF risk-regime gate for Golden 1 monthly lots.

For a run of repeated monthly selections, map the ticker to the sector ETF
with the highest pre-regime return correlation. A risk-off ETF state exits all
open lots in that run and blocks entries until the ETF recovers. EOD research
only; the ETF mapping is a price-exposure proxy, not historical membership.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path
from statistics import fmean

import duckdb

ETFS = ('XLK.US', 'XLC.US', 'XLY.US', 'XLF.US', 'XLI.US', 'XLV.US', 'XLE.US', 'XLB.US', 'XLU.US', 'XLRE.US', 'XLP.US')


def load(raw: Path, symbol: str) -> list[dict]:
    files = sorted(raw.glob(symbol.replace('.', '_') + '_*json'))
    if not files:
        raise SystemExit(f'missing cached {symbol} data in {raw}')
    return json.loads(files[-1].read_text())


def correlation(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2:
        return None
    xmean, ymean = fmean(x), fmean(y)
    dx, dy = [v - xmean for v in x], [v - ymean for v in y]
    denominator = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return sum(a * b for a, b in zip(dx, dy)) / denominator if denominator else None


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not any(amount < 0 for _, amount in flows) or not any(amount > 0 for _, amount in flows):
        return None
    origin = min(day for day, _ in flows)
    def value(rate: float) -> float:
        return sum(amount / (1 + rate) ** ((day - origin).days / 365.2425) for day, amount in flows)
    low, high = -0.9999, 1000.0
    low_value, high_value = value(low), value(high)
    if low_value * high_value > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        middle_value = value(middle)
        if low_value * middle_value <= 0:
            high = middle
        else:
            low, low_value = middle, middle_value
    return (low + high) / 2


def month_gap(left: date, right: date) -> int:
    return (right.year - left.year) * 12 + right.month - left.month


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trades', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--min-consecutive-entries', type=int, default=4)
    parser.add_argument('--correlation-sessions', type=int, default=63)
    parser.add_argument('--lookback-sessions', type=int, default=21)
    parser.add_argument('--min-relative-volume', type=float, default=1.2)
    parser.add_argument('--drawdown', type=float, default=0.10)
    args = parser.parse_args()
    if args.min_consecutive_entries < 2 or args.correlation_sessions < 20 or args.lookback_sessions < 2:
        parser.error('invalid lookback or consecutive-entry settings')

    with args.trades.open(newline='') as handle:
        base = list(csv.DictReader(handle))
    base.sort(key=lambda row: row['execution_date'])
    raw = args.raw_dir.resolve()
    etf = {symbol: load(raw, symbol) for symbol in ETFS}
    spy = {row['date']: float(row['adjusted_close']) for row in load(raw, 'SPY.US')}
    etf_index = {symbol: {row['date']: i for i, row in enumerate(data)} for symbol, data in etf.items()}

    tickers = sorted({row['ticker'].upper() for row in base})
    connection = duckdb.connect()
    try:
        placeholders = ','.join('?' * len(tickers))
        price_rows = connection.execute(
            f'''SELECT UPPER(Ticker), CAST(Date AS DATE), Open, AdjustedClose
                FROM read_parquet(?) WHERE UPPER(Ticker) IN ({placeholders}) ORDER BY 1, 2''',
            [str(args.project_root.resolve() / 'data/validated/sp500/eod_adjusted_current.parquet'), *tickers],
        ).fetchall()
    finally:
        connection.close()
    stocks: dict[str, list[tuple[date, float, float]]] = {}
    for ticker, observed, opened, adjusted_close in price_rows:
        stocks.setdefault(ticker, []).append((observed, float(opened), float(adjusted_close)))

    rows_by_ticker: dict[str, list[dict]] = {}
    for row in base:
        rows_by_ticker.setdefault(row['ticker'], []).append(row)
    actions: dict[tuple[str, str], dict] = {}

    for ticker, ticker_rows in rows_by_ticker.items():
        ticker_rows.sort(key=lambda row: row['execution_date'])
        episodes: list[list[dict]] = []
        current: list[dict] = []
        for row in ticker_rows:
            entry = date.fromisoformat(row['execution_date'])
            if current and month_gap(date.fromisoformat(current[-1]['execution_date']), entry) != 1:
                episodes.append(current); current = []
            current.append(row)
        if current:
            episodes.append(current)
        bars = stocks.get(ticker, [])
        bar_dates = [day for day, _, _ in bars]

        for episode in episodes:
            if len(episode) < args.min_consecutive_entries:
                continue
            activation = date.fromisoformat(episode[args.min_consecutive_entries - 1]['execution_date'])
            historical = [(day, close) for day, _, close in bars if day < activation]
            if len(historical) < args.correlation_sessions + 1:
                continue
            recent = historical[-(args.correlation_sessions + 1):]
            stock_returns = {recent[i][0].isoformat(): recent[i][1] / recent[i - 1][1] - 1 for i in range(1, len(recent))}
            best: tuple[str, float] | None = None
            for symbol, data in etf.items():
                closes = {row['date']: float(row['adjusted_close']) for row in data}
                ordered = sorted(closes)
                previous = {ordered[i]: ordered[i - 1] for i in range(1, len(ordered))}
                shared = [day for day in sorted(set(stock_returns) & set(closes)) if day in previous][-args.correlation_sessions:]
                pairs = [(stock_returns[day], closes[day] / closes[previous[day]] - 1) for day in shared]
                candidate = correlation([pair[0] for pair in pairs], [pair[1] for pair in pairs])
                if candidate is not None and (best is None or candidate > best[1]):
                    best = (symbol, candidate)
            if not best or activation.isoformat() not in etf_index[best[0]]:
                continue
            symbol, mapped_correlation = best
            data = etf[symbol]
            start = etf_index[symbol][activation.isoformat()]
            peak = float(data[start]['adjusted_close'])
            blocked = False
            intervals: list[tuple[date, date | None]] = []
            block_start: date | None = None
            for i in range(start + 1, len(data)):
                observed = date.fromisoformat(data[i]['date'])
                peak = max(peak, float(data[i]['adjusted_close']))
                if i < args.lookback_sessions or data[i - args.lookback_sessions]['date'] not in spy:
                    continue
                etf_return = float(data[i]['adjusted_close']) / float(data[i - args.lookback_sessions]['adjusted_close']) - 1
                spy_return = spy[data[i]['date']] / spy[data[i - args.lookback_sessions]['date']] - 1
                volumes = [float(row['volume']) for row in data[i - args.lookback_sessions:i] if float(row['volume']) > 0]
                relative_volume = float(data[i]['volume']) / fmean(volumes) if volumes else 0.0
                drawdown = float(data[i]['adjusted_close']) / peak - 1
                risk_off = etf_return < spy_return and relative_volume >= args.min_relative_volume and drawdown <= -args.drawdown
                recovered = etf_return >= spy_return and drawdown > -args.drawdown
                if not blocked and risk_off:
                    blocked, block_start = True, observed
                elif blocked and recovered:
                    intervals.append((block_start, observed)); blocked, block_start = False, None
            if blocked:
                intervals.append((block_start, None))
            for number, row in enumerate(episode, 1):
                entry = date.fromisoformat(row['execution_date'])
                base_exit = date.fromisoformat(row['exit_date'] or row['valuation_date'])
                for signal, recovery in intervals:
                    if entry >= signal and (recovery is None or entry < recovery):
                        actions[(ticker, entry.isoformat())] = {'action': 'blocked_entry', 'mapped_etf': symbol, 'mapping_correlation': mapped_correlation, 'signal_date': signal}
                        break
                    if entry < signal < base_exit:
                        exit_day = next((day for day in bar_dates if day > signal), None)
                        if exit_day and exit_day <= base_exit:
                            open_price = next(opened for day, opened, _ in bars if day == exit_day)
                            actions[(ticker, entry.isoformat())] = {'action': 'regime_exit', 'mapped_etf': symbol, 'mapping_correlation': mapped_correlation, 'signal_date': signal, 'exit_day': exit_day, 'exit_price': open_price}
                        break

    result: list[dict] = []
    exits = blocked_entries = 0
    for base_row in base:
        row = dict(base_row)
        row['exit_date'] = row['exit_date'] or row['valuation_date']
        key = (row['ticker'], row['execution_date'])
        action = actions.get(key)
        row.update({'regime_action': action['action'] if action else 'base_rule', 'mapped_etf': action['mapped_etf'] if action else '', 'mapping_correlation': action['mapping_correlation'] if action else '', 'regime_signal_date': action['signal_date'].isoformat() if action else ''})
        if action and action['action'] == 'blocked_entry':
            allocation = float(row['allocation'])
            row.update({'exit_date': row['execution_date'], 'exit_price': '', 'exit_reason': 'etf_regime_entry_blocked', 'net_proceeds': allocation, 'net_profit': 0.0, 'return_pct': 0.0, 'valuation_date': row['execution_date']})
            blocked_entries += 1
        elif action and action['action'] == 'regime_exit':
            exit_price = action['exit_price']; shares = float(row['shares']); cost = shares * exit_price * 0.001; proceeds = shares * exit_price - cost
            row.update({'exit_date': action['exit_day'].isoformat(), 'exit_price': exit_price, 'exit_reason': 'etf_regime_exit', 'exit_cost': cost, 'net_proceeds': proceeds, 'net_profit': proceeds - float(row['allocation']), 'return_pct': proceeds / float(row['allocation']) - 1, 'valuation_date': action['exit_day'].isoformat()})
            exits += 1
        result.append(row)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'combined_trades.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result[0])); writer.writeheader(); writer.writerows(result)
    invested = sum(float(row['allocation']) for row in result)
    proceeds = sum(float(row['net_proceeds']) for row in result)
    flows = [(date.fromisoformat(row['execution_date']), -float(row['allocation'])) for row in result]
    flows += [(date.fromisoformat(row['exit_date']), float(row['net_proceeds'])) for row in result]
    summary = {'trade_count': len(result), 'regime_exits': exits, 'blocked_entries': blocked_entries, 'invested_capital': invested, 'net_proceeds': proceeds, 'net_profit': proceeds - invested, 'roi': proceeds / invested - 1, 'xirr': xirr(flows), 'definition': 'after repeated monthly selection, mapped ETF risk-off exits all open lots and blocks entries until recovery', 'trades': str(args.output / 'combined_trades.csv')}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
