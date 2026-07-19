#!/usr/bin/env python3
"""Rank ETF-basket constituents by normalized SMA trend spread at event entry."""
from __future__ import annotations
import argparse, csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import fmean
import duckdb

LISTS={
 "health_care":"xlv_health_care_2026-07-16.csv", "financials":"xlf_financials_2026-07-16.csv",
 "semiconductors_smh":"smh_soxx_semiconductors_2026-07-16.csv", "semiconductors_soxx":"smh_soxx_semiconductors_2026-07-16.csv",
 "memory_dram":"dram_memory_sp500_2026-04-02.csv"}
def rows(path):
 with path.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))
def write(path, data, fields):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--events",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 p.add_argument("--project-root",type=Path,default=Path.cwd());p.add_argument("--sma-pair",action="append")
 p.add_argument("--top-n",action="append",type=int);p.add_argument("--from-signal",type=date.fromisoformat);p.add_argument("--to-signal",type=date.fromisoformat);p.add_argument("--min-relative-volume",type=float,default=1.0)
 a=p.parse_args(); a.sma_pair=a.sma_pair or ["10:30","20:50","30:100","50:150"]; a.top_n=a.top_n or [1,3,5,10]; root=a.project_root.resolve(); events=rows(a.events)
 events=[e for e in events if e["basket"] in LISTS and (not a.from_signal or date.fromisoformat(e["signal_date"])>=a.from_signal) and (not a.to_signal or date.fromisoformat(e["signal_date"])<=a.to_signal)]
 baskets={b:{r["ticker"].upper().replace(".","-") for r in rows(root/"data/features/current_sector_lists"/file)} for b,file in LISTS.items()}
 tickers=sorted(set().union(*baskets.values())); con=duckdb.connect()
 try:
  q="SELECT UPPER(Ticker),CAST(Date AS DATE),AdjustedClose,Volume FROM read_parquet(?) WHERE UPPER(Ticker) IN ("+",".join("?"*len(tickers))+") AND AdjustedClose>0 AND Volume>0 ORDER BY 1,2"
  raw=con.execute(q,[str(root/"data/validated/sp500/eod_adjusted_current.parquet"),*tickers]).fetchall()
 finally: con.close()
 prices=defaultdict(list)
 for t,d,c,v in raw: prices[t].append((d,float(c),float(v)))
 pairs=[tuple(map(int,x.split(":"))) for x in a.sma_pair]
 trades=[]
 for e in events:
  signal,entry,exit_=map(date.fromisoformat,(e["signal_date"],e["entry_date"],e["exit_date"]))
  for fast,slow in pairs:
   scored=[]
   for t in baskets[e["basket"]]:
    hist=[(d,c,v) for d,c,v in prices[t] if d<=signal]
    by={d:c for d,c,_ in prices[t]}
    if len(hist)<max(slow,21) or entry not in by or exit_ not in by: continue
    fs=fmean(c for _,c,_ in hist[-fast:]); ss=fmean(c for _,c,_ in hist[-slow:]); spread=fs/ss-1
    relative_volume=hist[-1][2]/fmean(v for _,_,v in hist[-21:-1])
    if spread>0 and relative_volume>=a.min_relative_volume: scored.append((spread,t,by[entry],by[exit_],relative_volume))
   for n in a.top_n:
    for rank,(spread,t,ep,xp,relative_volume) in enumerate(sorted(scored,reverse=True)[:n],1):
     trades.append({"basket":e["basket"],"signal_date":signal,"entry_date":entry,"exit_date":exit_,"fast_sma":fast,"slow_sma":slow,"top_n":n,"rank":rank,"ticker":t,"trend_spread":spread,"relative_volume":relative_volume,"entry_adjusted_close":ep,"exit_adjusted_close":xp,"return":xp/ep-1})
 summary=[]
 for fast,slow in pairs:
  for n in a.top_n:
   x=[float(r["return"]) for r in trades if r["fast_sma"]==fast and r["slow_sma"]==slow and r["top_n"]==n]
   summary.append({"fast_sma":fast,"slow_sma":slow,"top_n":n,"stock_trades":len(x),"average_return":fmean(x) if x else "","win_rate":sum(v>0 for v in x)/len(x) if x else ""})
 write(a.output/"sma_ranked_trades.csv",trades,list(trades[0]) if trades else ["ticker"])
 write(a.output/"sma_candidate_summary.csv",summary,list(summary[0]))
 print(f"wrote {a.output}")
if __name__=="__main__": main()
