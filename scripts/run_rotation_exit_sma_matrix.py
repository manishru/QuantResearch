#!/usr/bin/env python3
"""Run rotation-exit and constituent-SMA grids without manual command repetition."""
from __future__ import annotations
import argparse,csv,subprocess,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--events',type=Path,required=True);p.add_argument('--raw-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--project-root',type=Path,default=Path.cwd());p.add_argument('--drawdown',action='append',type=float);p.add_argument('--sma-pair',action='append');p.add_argument('--top-n',action='append',type=int);p.add_argument('--min-relative-volume',type=float,default=1.0);p.add_argument('--train-end',default='2020-12-31');p.add_argument('--test-start',default='2023-01-01');p.add_argument('--test-end',default='2026-07-17');a=p.parse_args();a.drawdown=a.drawdown or [.02,.04,.06,.08,.10];a.sma_pair=a.sma_pair or ['10:30','20:50','30:100','50:150'];a.top_n=a.top_n or [1,3,5]
 root=a.project_root.resolve(); out=a.output.resolve();out.mkdir(parents=True,exist_ok=True); rows=[]; trade_rows=[]
 for dd in a.drawdown:
  rotation=out/f'rotation_exit_dd{int(dd*100):02d}.csv'
  subprocess.run([sys.executable,str(root/'scripts/derive_etf_rotation_exits.py'),'--events',str(a.events),'--raw-dir',str(a.raw_dir),'--drawdown',str(dd),'--min-relative-volume',str(a.min_relative_volume),'--output',str(rotation)],check=True)
  for label,start,end in [('train','2010-01-01',a.train_end),('test',a.test_start,a.test_end)]:
   run=out/f'{label}_dd{int(dd*100):02d}'
   cmd=[sys.executable,str(root/'scripts/backtest_constituent_sma_ranking.py'),'--events',str(rotation),'--from-signal',start,'--to-signal',end,'--min-relative-volume',str(a.min_relative_volume),'--output',str(run)]
   for pair in a.sma_pair: cmd += ['--sma-pair',pair]
   for n in a.top_n: cmd += ['--top-n',str(n)]
   subprocess.run(cmd,check=True)
   with (run/'sma_candidate_summary.csv').open(newline='',encoding='utf-8') as f:
    for r in csv.DictReader(f): rows.append({'period':label,'drawdown':dd,**r})
   with (run/'sma_ranked_trades.csv').open(newline='',encoding='utf-8') as f:
    for r in csv.DictReader(f):
     rule=f"rotation_dd{int(dd*100):02d}_sma{r['fast_sma']}_{r['slow_sma']}_top{r['top_n']}_rvol{a.min_relative_volume:g}"
     trade_rows.append({'period':label,'strategy_rule':rule,'rotation_drawdown':dd,**r})
 fields=['period','drawdown','fast_sma','slow_sma','top_n','stock_trades','average_return','win_rate']
 with (out/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 trade_fields=['period','strategy_rule','rotation_drawdown','basket','signal_date','entry_date','exit_date','fast_sma','slow_sma','top_n','rank','ticker','trend_spread','relative_volume','entry_adjusted_close','exit_adjusted_close','return']
 with (out/'comparison_trades.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=trade_fields);w.writeheader();w.writerows(trade_rows)
 print(f'wrote {out}/comparison.csv and {out}/comparison_trades.csv')
if __name__=='__main__': main()
