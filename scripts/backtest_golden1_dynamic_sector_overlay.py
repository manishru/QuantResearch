#!/usr/bin/env python3
"""EOD-only dynamic sector-ETF exit overlay for Golden 1 lot trades.

Each entry is mapped, using only pre-entry data, to the sector ETF with the
highest trailing daily-return correlation. The mapped ETF can trigger an
earlier rotation exit; otherwise the original 51-week/stop exit remains.
This is a price-exposure proxy, not historical ETF membership.
"""
from __future__ import annotations
import argparse,csv,json,math
from datetime import date
from pathlib import Path
from statistics import fmean
import duckdb

ETFS=('XLK.US','XLC.US','XLY.US','XLF.US','XLI.US','XLV.US','XLE.US','XLB.US','XLU.US','XLRE.US','XLP.US')
def load(raw,s):
 f=sorted(raw.glob(s.replace('.','_')+'_*json'))
 if not f: return []
 return json.loads(f[-1].read_text())
def corr(x,y):
 if len(x)<2:return None
 ax,ay=fmean(x),fmean(y);dx=[v-ax for v in x];dy=[v-ay for v in y];den=math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy));return sum(a*b for a,b in zip(dx,dy))/den if den else None
def xirr(flows):
 if not any(v<0 for _,v in flows) or not any(v>0 for _,v in flows):return None
 o=min(d for d,_ in flows)
 def f(r):return sum(v/(1+r)**((d-o).days/365.2425) for d,v in flows)
 lo,hi=-.9999,1000.;a,b=f(lo),f(hi)
 if a*b>0:return None
 for _ in range(200):
  m=(lo+hi)/2;c=f(m)
  if a*c<=0:hi=m
  else:lo,a=m,c
 return (lo+hi)/2
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trades',type=Path,required=True);p.add_argument('--raw-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--project-root',type=Path,default=Path.cwd());p.add_argument('--correlation-sessions',type=int,default=63);p.add_argument('--rotation-lookback-sessions',type=int,default=21);p.add_argument('--drawdown',type=float,default=.10);p.add_argument('--min-relative-volume',type=float,default=1);p.add_argument('--require-stock-confirmation',action='store_true');p.add_argument('--stock-drawdown',type=float,default=.20);p.add_argument('--stock-min-relative-volume',type=float,default=1.5);a=p.parse_args()
 if a.correlation_sessions<20 or a.rotation_lookback_sessions<2:p.error('invalid lookback')
 with a.trades.open(newline='') as f:base=list(csv.DictReader(f))
 raw=a.raw_dir.resolve();etf={s:load(raw,s) for s in ETFS};spy={r['date']:r for r in load(raw,'SPY.US')};idx={s:{r['date']:i for i,r in enumerate(v)} for s,v in etf.items()}
 symbols=sorted({r['ticker'] for r in base});con=duckdb.connect();root=a.project_root.resolve()
 try:
  q=','.join('?'*len(symbols));rows=con.execute(f"SELECT UPPER(Ticker),CAST(Date AS DATE),Open,AdjustedClose,Volume FROM read_parquet(?) WHERE UPPER(Ticker) IN ({q}) ORDER BY 1,2",[str(root/'data/validated/sp500/eod_adjusted_current.parquet'),*symbols]).fetchall()
 finally:con.close()
 stock={};opens={}
 for t,d,o,c,v in rows:stock.setdefault(t,[]).append((d,float(c),float(v)));opens[(t,d)]=float(o)
 result=[];applied=0
 for r in base:
  row=dict(r);ticker=row['ticker'];entry=date.fromisoformat(row['execution_date']);base_exit=date.fromisoformat(row['exit_date'] or row['valuation_date']);bars=stock.get(ticker,[]);hist=[(d,c) for d,c,_ in bars if d<entry];stock_dates={d:i for i,(d,_,_) in enumerate(bars)}
  best=None
  if len(hist)>a.correlation_sessions:
   recent=hist[-(a.correlation_sessions+1):]
   sr={d.isoformat():recent[i][1]/recent[i-1][1]-1 for i,(d,_) in enumerate(recent) if i>0}
   for symbol,data in etf.items():
    dates={r['date']:float(r['adjusted_close']) for r in data};shared=sorted(set(sr)&set(dates));shared=[d for d in shared if d<entry.isoformat()][-a.correlation_sessions:]
    er=[dates[d]/dates[sorted(dates).index(d)-1] - 1 if False else 0 for d in []]
    vals=[]
    ordered=sorted(dates);prev={ordered[i]:dates[ordered[i-1]] for i in range(1,len(ordered))}
    for d in shared:
     if d in prev:vals.append((sr[d],dates[d]/prev[d]-1))
    c=corr([v[0] for v in vals],[v[1] for v in vals])
    if c is not None and (best is None or c>best[1]):best=(symbol,c)
  row.update({'exit_date':base_exit.isoformat(), 'dynamic_sector_etf':best[0] if best else '', 'mapping_correlation':best[1] if best else '', 'overlay_applied':False,'base_exit_date':base_exit.isoformat(),'base_exit_reason':row['exit_reason'],'overlay_signal_date':''})
  chosen=None
  if best and entry.isoformat() in idx[best[0]]:
   data=etf[best[0]];start=idx[best[0]][entry.isoformat()];peak=float(data[start]['adjusted_close'])
   for i in range(start+1,len(data)):
    d=date.fromisoformat(data[i]['date'])
    if d>=base_exit:break
    peak=max(peak,float(data[i]['adjusted_close']))
    if i<a.rotation_lookback_sessions or data[i]['date'] not in spy or data[i-a.rotation_lookback_sessions]['date'] not in spy:continue
    rel=float(data[i]['adjusted_close'])/float(data[i-a.rotation_lookback_sessions]['adjusted_close'])-float(spy[data[i]['date']]['adjusted_close'])/float(spy[data[i-a.rotation_lookback_sessions]['date']]['adjusted_close']);vs=[float(x['volume']) for x in data[i-a.rotation_lookback_sessions:i] if float(x['volume'])>0];rv=float(data[i]['volume'])/fmean(vs) if vs else 0;dd=float(data[i]['adjusted_close'])/peak-1
    stock_ok=True
    if a.require_stock_confirmation:
     stock_ok=False;si=stock_dates.get(d)
     if si is not None and si>=a.rotation_lookback_sessions:
      entry_i=stock_dates.get(entry,0);stock_peak=max(close for _,close,_ in bars[entry_i:si+1]);stock_return=bars[si][1]/bars[si-a.rotation_lookback_sessions][1]-1;stock_spy_return=float(spy[data[i]['date']]['adjusted_close'])/float(spy[data[i-a.rotation_lookback_sessions]['date']]['adjusted_close'])-1;stock_volumes=[volume for _,_,volume in bars[si-a.rotation_lookback_sessions:si] if volume>0];stock_rv=bars[si][2]/fmean(stock_volumes) if stock_volumes else 0;stock_dd=bars[si][1]/stock_peak-1;stock_ok=stock_return<stock_spy_return and stock_rv>=a.stock_min_relative_volume and stock_dd<=-a.stock_drawdown
    if rel<0 and rv>=a.min_relative_volume and dd<=-a.drawdown and stock_ok:
     for j in range(i+1,len(data)):
      ex=date.fromisoformat(data[j]['date']);price=opens.get((ticker,ex))
      if price and ex<=base_exit:chosen=(ex,price,d);break
     break
  if chosen:
   ex,price,signal=chosen;shares=float(row['shares']);cost=shares*price*.001;proceeds=shares*price-cost;row.update({'exit_date':ex.isoformat(),'exit_price':price,'exit_reason':'combined_sector_stock_rotation_exit' if a.require_stock_confirmation else 'dynamic_sector_etf_rotation_exit','exit_cost':cost,'net_proceeds':proceeds,'net_profit':proceeds-float(row['allocation']),'return_pct':proceeds/float(row['allocation'])-1,'valuation_date':ex.isoformat(),'overlay_applied':True,'overlay_signal_date':signal.isoformat()});applied+=1
  result.append(row)
 a.output.mkdir(parents=True,exist_ok=True)
 with (a.output/'combined_trades.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
 inv=sum(float(r['allocation']) for r in result);pro=sum(float(r['net_proceeds']) for r in result);flows=[(date.fromisoformat(r['execution_date']),-float(r['allocation'])) for r in result]+[(date.fromisoformat(r['exit_date']),float(r['net_proceeds'])) for r in result];summary={'trade_count':len(result),'overlay_exits':applied,'invested_capital':inv,'net_proceeds':pro,'net_profit':pro-inv,'roi':pro/inv-1,'xirr':xirr(flows),'mapping':'highest trailing stock/sector-ETF return correlation; EOD-only price-exposure proxy','stock_confirmation_required':a.require_stock_confirmation,'trades':str(a.output/'combined_trades.csv')};(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
