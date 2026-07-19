#!/usr/bin/env python3
"""Compare weekly, biweekly, three-week and monthly ETF rotation horizons."""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from", dest="start", default="2010-01-01")
    p.add_argument("--to", default="2026-07-17")
    p.add_argument("--lookback-sessions", type=int, action="append", default=None)
    p.add_argument("--train-end", default="2020-12-31")
    p.add_argument("--test-start", default="2023-01-01")
    p.add_argument("--forward-start", default="2026-04-01",
                   help="Recent forward slice; includes DRAM only once its data exists")
    p.add_argument("--drawdown", type=float, default=.10)
    p.add_argument("--min-relative-volume", type=float, default=1.0)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    horizons = sorted(set(a.lookback_sessions or [5, 10, 15, 21]))
    if any(value < 2 for value in horizons): p.error("lookback sessions must be at least 2")
    root, out = a.project_root.resolve(), a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    result=[]
    for horizon in horizons:
        event_dir=out/f"events_{horizon}d"
        cmd=[sys.executable,str(root/'scripts/backtest_etf_momentum_breadth_proxy.py'),'--from',a.start,'--to',a.to,'--holding-sessions','21','--lookback-sessions',str(horizon),'--minimum-breadth','.55','--minimum-relative-volume',str(a.min_relative_volume),'--output',str(event_dir)]
        if a.refresh: cmd.append('--refresh')
        run(cmd)
        exits=out/f"rotation_exit_{horizon}d.csv"
        run([sys.executable,str(root/'scripts/derive_etf_rotation_exits.py'),'--events',str(event_dir/'signal_events.csv'),'--raw-dir',str(event_dir/'raw_eodhd'),'--drawdown',str(a.drawdown),'--lookback-sessions',str(horizon),'--min-relative-volume',str(a.min_relative_volume),'--output',str(exits)])
        for period,start,end in [('train',a.start,a.train_end),('test',a.test_start,a.to),('forward',a.forward_start,a.to)]:
            selected=out/f"{period}_{horizon}d"
            run([sys.executable,str(root/'scripts/backtest_constituent_sma_ranking.py'),'--events',str(exits),'--from-signal',start,'--to-signal',end,'--sma-pair','20:50','--top-n','1','--min-relative-volume',str(a.min_relative_volume),'--output',str(selected)])
            with (selected/'sma_candidate_summary.csv').open(newline='',encoding='utf-8') as f:
                for row in csv.DictReader(f): result.append({'period':period,'rotation_lookback_sessions':horizon,'rotation_drawdown':a.drawdown,**row})
    fields=['period','rotation_lookback_sessions','rotation_drawdown','fast_sma','slow_sma','top_n','stock_trades','average_return','win_rate']
    with (out/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(result)
    print(f"wrote {out/'comparison.csv'}")


if __name__ == '__main__': main()
