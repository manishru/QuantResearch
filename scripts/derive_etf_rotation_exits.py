#!/usr/bin/env python3
"""Replace fixed event exits with price/volume rotation exits using cached ETF data."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from statistics import fmean

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--events',type=Path,required=True);p.add_argument('--raw-dir',type=Path,required=True);p.add_argument('--drawdown',type=float,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--min-relative-volume',type=float,default=1.0);a=p.parse_args()
 with a.events.open(newline='',encoding='utf-8') as f: events=list(csv.DictReader(f))
 def load(symbol):
  files=sorted(a.raw_dir.glob(symbol.replace('.','_')+'_*.json'))
  if not files: raise FileNotFoundError(symbol)
  return json.loads(files[-1].read_text())
 spy={r['date']:r for r in load('SPY.US')}; cache={}
 out=[]
 for e in events:
  symbol=e['etf']; data=cache.setdefault(symbol,load(symbol)); by={r['date']:i for i,r in enumerate(data)}
  if e['entry_date'] not in by: continue
  start=by[e['entry_date']]; entry=float(data[start]['adjusted_close']); peak=entry; exit_i=len(data)-1; reason='end_of_data'
  for i in range(start+1,len(data)):
   peak=max(peak,float(data[i]['adjusted_close']))
   if i<21 or data[i]['date'] not in spy or data[i-21]['date'] not in spy: continue
   rel=float(data[i]['adjusted_close'])/float(data[i-21]['adjusted_close'])-float(spy[data[i]['date']]['adjusted_close'])/float(spy[data[i-21]['date']]['adjusted_close'])
   vols=[float(x['volume']) for x in data[i-21:i] if float(x['volume'])>0]; rv=float(data[i]['volume'])/fmean(vols) if vols else 0
   dd=float(data[i]['adjusted_close'])/peak-1
   if rel<0 and rv>=a.min_relative_volume and dd<=-a.drawdown: exit_i=i;reason='rotation_exit';break
  exit_=float(data[exit_i]['adjusted_close']);out.append({**e,'exit_date':data[exit_i]['date'],'etf_return':exit_/entry-1,'exit_reason':reason,'exit_drawdown_from_peak':exit_/peak-1,'exit_relative_volume':rv if 'rv' in locals() else '', 'rotation_drawdown_threshold':a.drawdown})
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
 print(f'wrote {len(out)} rotation-exit events to {a.output}')
if __name__=='__main__':main()
