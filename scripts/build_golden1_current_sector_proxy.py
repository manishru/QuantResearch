#!/usr/bin/env python3
"""Build a cached current-sector proxy for every ticker selected by Golden 1.

EODHD Fundamentals `General.Sector` is current classification information, not
dated historical GICS. The output must therefore be used only as a clearly
labelled proxy when testing historical sector-ETF rotation overlays.
"""
from __future__ import annotations

import argparse, csv, json, os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ETF_BY_SECTOR = {
    "Technology": "XLK.US", "Communication Services": "XLC.US",
    "Consumer Cyclical": "XLY.US", "Consumer Defensive": "XLP.US",
    "Financial Services": "XLF.US", "Financial": "XLF.US",
    "Industrials": "XLI.US", "Healthcare": "XLV.US", "Health Care": "XLV.US",
    "Energy": "XLE.US", "Basic Materials": "XLB.US", "Utilities": "XLU.US",
    "Real Estate": "XLRE.US",
}

def fetch(ticker: str, token: str) -> dict[str, object]:
    query = urlencode({"api_token": token, "fmt": "json"})
    with urlopen(f"https://eodhd.com/api/fundamentals/{ticker}.US?{query}", timeout=60) as response:  # noqa: S310
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict): raise ValueError("unexpected fundamentals response")
    return value

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trades",type=Path,action="append",required=True,help="Repeat for Golden 1 trade CSVs")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--token-env",default="EODHD_API_TOKEN")
    p.add_argument("--refresh",action="store_true")
    a=p.parse_args(); token=os.environ.get(a.token_env)
    if not token:p.error(f"set {a.token_env}; token is not accepted on the command line")
    tickers=set()
    for path in a.trades:
        with path.expanduser().resolve().open(newline="",encoding="utf-8") as f:
            tickers|={row["ticker"].upper().strip() for row in csv.DictReader(f) if row.get("ticker","").strip()}
    out=a.output.expanduser().resolve();out.parent.mkdir(parents=True,exist_ok=True); cache=out.parent/"raw_eodhd_fundamentals";cache.mkdir(exist_ok=True)
    rows=[]
    for ticker in sorted(tickers):
        path=cache/f"{ticker}.json"
        try:
            if a.refresh or not path.exists():path.write_text(json.dumps(fetch(ticker,token))+"\n",encoding="utf-8")
            value=json.loads(path.read_text(encoding="utf-8"));general=value.get("General",{}) if isinstance(value.get("General",{}),dict) else {}
            sector=str(general.get("Sector","")).strip();industry=str(general.get("Industry","")).strip()
            rows.append({"ticker":ticker,"current_sector":sector,"current_industry":industry,"sector_etf":ETF_BY_SECTOR.get(sector,""),"classification_method":"current_eodhd_fundamentals_proxy","status":"mapped" if sector in ETF_BY_SECTOR else "unmapped"})
        except Exception as error:
            rows.append({"ticker":ticker,"current_sector":"","current_industry":"","sector_etf":"","classification_method":"current_eodhd_fundamentals_proxy","status":f"error: {error}"})
    fields=list(rows[0]) if rows else ["ticker","current_sector","current_industry","sector_etf","classification_method","status"]
    with out.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print(json.dumps({"output":str(out),"ticker_count":len(tickers),"mapped_count":sum(r['status']=='mapped' for r in rows),"unmapped_count":sum(r['status']!='mapped' for r in rows),"limitation":"Current EODHD sector classifications are a proxy; they are not historical sector classifications."},indent=2))
if __name__=="__main__":main()
