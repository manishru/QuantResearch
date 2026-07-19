#!/usr/bin/env python3
"""Test a direct stock-level risk-off exit overlay on Golden 1 lot trades.

Exit at the next stock-session open when the stock itself underperforms SPY
over the selected lookback, trades on elevated volume, and is sufficiently
below its highest adjusted close since entry. This is an EOD research test.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from statistics import fmean

import duckdb


def load_json(raw_dir: Path, symbol: str) -> list[dict]:
    files = sorted(raw_dir.glob(symbol.replace('.', '_') + '_*json'))
    if not files:
        raise SystemExit(f"missing cached {symbol} data in {raw_dir}")
    return json.loads(files[-1].read_text())


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not any(value < 0 for _, value in flows) or not any(value > 0 for _, value in flows):
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trades', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True, help='Cached EODHD directory containing SPY.US JSON.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--lookback-sessions', type=int, default=21)
    parser.add_argument('--drawdown', type=float, default=0.10)
    parser.add_argument('--min-relative-volume', type=float, default=1.0)
    args = parser.parse_args()
    if args.lookback_sessions < 2 or not 0 < args.drawdown < 1:
        parser.error('invalid lookback or drawdown')

    with args.trades.open(newline='') as handle:
        trades = list(csv.DictReader(handle))
    spy_rows = load_json(args.raw_dir.resolve(), 'SPY.US')
    spy = {row['date']: float(row['adjusted_close']) for row in spy_rows}
    tickers = sorted({row['ticker'].upper() for row in trades})
    placeholders = ','.join('?' * len(tickers))
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f'''SELECT UPPER(Ticker), CAST(Date AS DATE), Open, AdjustedClose, Volume
                FROM read_parquet(?) WHERE UPPER(Ticker) IN ({placeholders}) ORDER BY 1, 2''',
            [str(args.project_root.resolve() / 'data/validated/sp500/eod_adjusted_current.parquet'), *tickers],
        ).fetchall()
    finally:
        connection.close()
    bars: dict[str, list[tuple[date, float, float, float]]] = {}
    for ticker, observed, opened, adjusted_close, volume in rows:
        bars.setdefault(ticker, []).append((observed, float(opened), float(adjusted_close), float(volume)))

    output_rows: list[dict[str, str | float | bool]] = []
    exits = 0
    for base in trades:
        row: dict[str, str | float | bool] = dict(base)
        ticker = base['ticker'].upper()
        entry = date.fromisoformat(base['execution_date'])
        base_exit = date.fromisoformat(base['exit_date'] or base['valuation_date'])
        series = bars.get(ticker, [])
        entry_index = next((i for i, item in enumerate(series) if item[0] == entry), None)
        row.update({
            'exit_date': base_exit.isoformat(),
            'base_exit_date': base_exit.isoformat(),
            'base_exit_reason': base['exit_reason'],
            'overlay_signal_date': '',
            'overlay_stock_return': '',
            'overlay_spy_return': '',
            'overlay_relative_volume': '',
            'overlay_drawdown': '',
            'overlay_applied': False,
        })
        chosen: tuple[date, float, date, float, float, float, float] | None = None
        if entry_index is not None:
            peak = series[entry_index][2]
            for i in range(entry_index + 1, len(series) - 1):
                observed, _, close, volume = series[i]
                if observed >= base_exit:
                    break
                peak = max(peak, close)
                if i < args.lookback_sessions or observed.isoformat() not in spy or series[i - args.lookback_sessions][0].isoformat() not in spy:
                    continue
                stock_return = close / series[i - args.lookback_sessions][2] - 1
                spy_return = spy[observed.isoformat()] / spy[series[i - args.lookback_sessions][0].isoformat()] - 1
                volumes = [item[3] for item in series[i - args.lookback_sessions:i] if item[3] > 0]
                relative_volume = volume / fmean(volumes) if volumes else 0.0
                drawdown = close / peak - 1
                if stock_return < spy_return and relative_volume >= args.min_relative_volume and drawdown <= -args.drawdown:
                    next_day, next_open, *_ = series[i + 1]
                    if next_day <= base_exit and next_open > 0:
                        chosen = (next_day, next_open, observed, stock_return, spy_return, relative_volume, drawdown)
                    break
        if chosen:
            exit_day, exit_open, signal_day, stock_return, spy_return, relative_volume, drawdown = chosen
            shares = float(base['shares'])
            exit_cost = shares * exit_open * 0.001
            proceeds = shares * exit_open - exit_cost
            row.update({
                'exit_date': exit_day.isoformat(), 'exit_price': exit_open,
                'exit_reason': 'stock_rotation_risk_off_exit', 'exit_cost': exit_cost,
                'net_proceeds': proceeds, 'net_profit': proceeds - float(base['allocation']),
                'return_pct': proceeds / float(base['allocation']) - 1,
                'valuation_date': exit_day.isoformat(), 'overlay_signal_date': signal_day.isoformat(),
                'overlay_stock_return': stock_return, 'overlay_spy_return': spy_return,
                'overlay_relative_volume': relative_volume, 'overlay_drawdown': drawdown,
                'overlay_applied': True,
            })
            exits += 1
        output_rows.append(row)

    args.output.mkdir(parents=True, exist_ok=True)
    trades_path = args.output / 'combined_trades.csv'
    with trades_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader(); writer.writerows(output_rows)
    invested = sum(float(row['allocation']) for row in output_rows)
    proceeds = sum(float(row['net_proceeds']) for row in output_rows)
    flows = [(date.fromisoformat(row['execution_date']), -float(row['allocation'])) for row in output_rows]
    flows += [(date.fromisoformat(str(row['exit_date'])), float(row['net_proceeds'])) for row in output_rows]
    summary = {'trade_count': len(output_rows), 'overlay_exits': exits, 'invested_capital': invested,
               'net_proceeds': proceeds, 'net_profit': proceeds - invested, 'roi': proceeds / invested - 1,
               'xirr': xirr(flows), 'definition': 'stock return < SPY return; relative volume >= threshold; drawdown <= threshold; exit next session open',
               'trades': str(trades_path)}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
