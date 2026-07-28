#!/usr/bin/env python3
"""Chronological 5M>3M>0 momentum with sector-ETF exits and six-month cooldowns.

Research-only. ETF mappings are current category proxies, not dated holdings.
Candidate templates must be generated with ``--top-n 10`` so every possible
rank fallback has a point-in-time entry, stop/volatility exit, and maturity path.
"""
from __future__ import annotations

import argparse, calendar, csv, json, os
from datetime import date
from pathlib import Path

import duckdb

from backtest_etf_confirmed_momentum_overlay import fetch, rows, state, xirr


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year, month = value.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def write(path: Path, values: list[dict]) -> None:
    fields = list(values[0]) if values else ["execution_date"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=fields); out.writeheader(); out.writerows(values)


def trade_sort_key(row: dict) -> tuple[str, str, str]:
    return row.get("signal_date", ""), row.get("execution_date", ""), row.get("ticker", "")


def load_mapping_resolver(static_path: Path, interval_path: Path | None):
    """Resolve a reviewed primary ETF strictly as of the simulated date."""
    static = {row["ticker"]: row for row in rows(static_path)}
    intervals: dict[str, list[dict]] = {}
    if interval_path and interval_path.is_file():
        for row in rows(interval_path):
            if row.get("status", "").lower() not in {"approved", "excluded"}:
                continue
            intervals.setdefault(row["ticker"], []).append(row)
    for values in intervals.values():
        values.sort(key=lambda row: row.get("effective_from") or "0001-01-01")

    def resolve(ticker: str, observed: date) -> dict | None:
        for row in intervals.get(ticker, []):
            start = date.fromisoformat(row["effective_from"]) if row.get("effective_from") else date.min
            end = date.fromisoformat(row["effective_to"]) if row.get("effective_to") else date.max
            if start <= observed <= end:
                return row
        return static.get(ticker)

    all_symbols = {row.get("primary_etf", "") for row in static.values()}
    all_symbols |= {row.get("primary_etf", "") for group in intervals.values() for row in group if row.get("status", "").lower() == "approved"}
    return resolve, {symbol for symbol in all_symbols if symbol}


def simulate_threshold(*, threshold: int, entry_mode: str, external_events: dict[str, list[date]], days: list[date], by_entry: dict[date, list[dict]], templates: dict, mapping_resolver, etf: dict, spy: dict, next_open, output_dir: Path, cooldown_months: int, min_relative_volume: float, drawdown: float, monthly_budget: float, cost: float) -> dict:
    """Run one chronological threshold without sharing mutable state with peers."""
    active: list[dict] = []; finished: list[dict] = []; decisions: list[dict] = []; cooldown: dict[str, date] = {}
    for today in days:
        active, due = [lot for lot in active if lot["exit_date"] > today], [lot for lot in active if lot["exit_date"] <= today]
        finished.extend(due)
        sectors: dict[str, list[dict]] = {}
        for lot in active:
            if lot["primary_etf"]: sectors.setdefault(lot["primary_etf"], []).append(lot)
        for symbol, lots in sectors.items():
            risk = state(etf.get(symbol, []), spy, today.isoformat(), 21, None)
            if len(lots) < threshold or not risk or not (risk["vs_spy"] < 1 and risk["relative_volume"] >= min_relative_volume and risk["drawdown"] <= -drawdown):
                continue
            early = []
            for lot in lots:
                fill = next_open(lot["ticker"], today)
                if fill and fill[0] < lot["exit_date"]:
                    early.append((lot, fill))
            if not early:
                continue
            until = add_months(today, cooldown_months)
            cooldown[symbol] = max(cooldown.get(symbol, until), until)
            for lot, fill in early:
                lot.update(exit_date=fill[0], exit_price=fill[1], exit_reason="etf_rotation_risk_off", etf_signal_date=today.isoformat(), sector_open_lots=len(lots), cooldown_until=until.isoformat())
        if today not in by_entry:
            continue
        chosen = None; rejected = []
        for candidate in by_entry[today]:
            mapped = mapping_resolver(candidate["ticker"], today); symbol = mapped["primary_etf"] if mapped else ""
            if mapped and mapped.get("status", "").lower() == "excluded":
                rejected.append(f"{candidate['ticker']}:excluded_identity"); continue
            strategy_until = cooldown.get(symbol, date.min)
            event = next((d for d in reversed(external_events.get(symbol, [])) if d < today and today < add_months(d, cooldown_months)), None)
            strategy_blocked = today < strategy_until
            external_blocked = event is not None
            blocked = (entry_mode == "existing" and strategy_blocked) or (entry_mode == "external" and external_blocked) or (entry_mode == "combined" and (strategy_blocked or external_blocked))
            if blocked:
                source = "external" if external_blocked and (entry_mode != "existing" or not strategy_blocked) else "strategy"
                rejected.append(f"{candidate['ticker']}:{source}_sector_cooldown"); continue
            template = templates.get((today, candidate["ticker"], candidate["rank"]))
            if template:
                chosen = (candidate, mapped, template); break
            rejected.append(f"{candidate['ticker']}:missing_template")
        if not chosen:
            decisions.append({"execution_date": today.isoformat(), "decision": "cash", "reason": ";".join(rejected) or "no_candidate", "entry_mode": entry_mode}); continue
        candidate, mapped, template = chosen
        active.append({"execution_date": today, "signal_date": candidate["signal_date"], "ticker": candidate["ticker"], "rank_selected": candidate["rank"], "primary_etf": mapped["primary_etf"] if mapped else "", "entry_price": float(template["entry_price"]), "exit_date": date.fromisoformat(template["exit_date"] or template["valuation_date"]), "exit_price": float(template["exit_price"]), "exit_reason": template["exit_reason"], "etf_signal_date": "", "sector_open_lots": "", "cooldown_until": ""})
        decisions.append({"execution_date": today.isoformat(), "decision": "invested", "ticker": candidate["ticker"], "rank_selected": candidate["rank"], "reason": "rank_selection", "entry_mode": entry_mode})
    finished.extend(active)
    output = []
    for lot in finished:
        shares = monthly_budget * (1 - cost) / lot["entry_price"]; proceeds = shares * lot["exit_price"] * (1 - cost)
        output.append({**lot, "execution_date": lot["execution_date"].isoformat(), "exit_date": lot["exit_date"].isoformat(), "allocation": monthly_budget, "net_proceeds": proceeds, "net_profit": proceeds - monthly_budget, "return_pct": proceeds / monthly_budget - 1})
    output.sort(key=trade_sort_key)
    decisions.sort(key=lambda row: row["execution_date"])
    trades_path = output_dir / "trades.csv"
    decisions_path = output_dir / "monthly_decisions.csv"
    write(trades_path, output); write(decisions_path, decisions)
    # Matrix runs also expose flat, self-describing copies for spreadsheet review.
    if output_dir.name.startswith(("existing_", "external_", "combined_")):
        write(output_dir.parent / f"{output_dir.name}_trades.csv", output)
        write(output_dir.parent / f"{output_dir.name}_monthly_decisions.csv", decisions)
    cash_months = sum(d["decision"] == "cash" for d in decisions)
    invested_proceeds = sum(float(r["net_proceeds"]) for r in output)
    total_contributions = len(decisions) * monthly_budget
    net_proceeds = invested_proceeds + cash_months * monthly_budget
    flows = [(date.fromisoformat(d["execution_date"]), -monthly_budget) for d in decisions]
    flows += [(date.fromisoformat(r["exit_date"]), float(r["net_proceeds"])) for r in output]
    flows += [(date.fromisoformat(d["execution_date"]), monthly_budget) for d in decisions if d["decision"] == "cash"]
    result = {"entry_mode": entry_mode, "minimum_sector_open_lots": threshold, "trade_count": len(output), "cash_months": cash_months, "total_contributions": total_contributions, "idle_cash_contributions": cash_months * monthly_budget, "net_proceeds": net_proceeds, "net_profit": net_proceeds - total_contributions, "roi": net_proceeds / total_contributions - 1 if total_contributions else 0, "xirr": xirr(flows), "early_etf_exits": sum(r["exit_reason"] == "etf_rotation_risk_off" for r in output), "trades": str(trades_path), "decisions": str(decisions_path)}
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", type=Path, required=True); p.add_argument("--templates", type=Path, required=True)
    p.add_argument("--mapping", type=Path, default=Path("config/etf_confirmed_momentum_mapping.csv")); p.add_argument("--mapping-intervals", type=Path, default=Path("config/etf_confirmed_momentum_mapping_intervals.csv")); p.add_argument("--parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    p.add_argument("--start", type=date.fromisoformat, required=True); p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--rule", default="5M>3M>0"); p.add_argument("--nominal-day", type=int, default=26); p.add_argument("--max-rank", type=int, default=10, choices=range(1, 11))
    p.add_argument("--min-relative-volume", type=float, default=1.25); p.add_argument("--drawdown", type=float, default=.10)
    p.add_argument("--min-sector-open-lots", type=int, action="append", choices=range(1, 11), help="Repeat to run a threshold matrix; defaults to 5.")
    p.add_argument("--cooldown-months", type=int, default=6); p.add_argument("--entry-mode", choices=("existing", "external", "combined"), action="append", help="Repeat to compare entry cooldown modes; default existing.")
    p.add_argument("--monthly-budget", type=float, default=1000); p.add_argument("--cost", type=float, default=.001); p.add_argument("--token-env", default="EODHD_API_TOKEN"); p.add_argument("--cache-dir", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); token = os.environ.get(a.token_env)
    if not token: p.error(f"set {a.token_env}; tokens are not accepted on the command line")
    thresholds = sorted(set(a.min_sector_open_lots or [5]))
    if a.cooldown_months < 1: p.error("cooldown months must be positive")
    a.output.mkdir(parents=True, exist_ok=True); a.cache_dir.mkdir(parents=True, exist_ok=True)
    mapping_resolver, mapped_symbols = load_mapping_resolver(a.mapping, a.mapping_intervals)
    candidates = [r for r in rows(a.candidates) if r["rule_name"] == a.rule and int(r["nominal_day"]) == a.nominal_day and a.start <= date.fromisoformat(r["execution_date"]) <= a.end and int(r["rank"]) <= a.max_rank]
    by_entry: dict[date, list[dict]] = {}
    for r in candidates: by_entry.setdefault(date.fromisoformat(r["execution_date"]), []).append(r)
    for group in by_entry.values(): group.sort(key=lambda r: int(r["rank"]))
    templates = {(date.fromisoformat(r["execution_date"]), r["ticker"], r["rank"]): r for r in rows(a.templates) if r["rule"] == a.rule and int(r["nominal_day"]) == a.nominal_day}
    if not templates: p.error("no matching templates; generate them with run_monthly_momentum_lot_matrix.py --top-n 10")
    symbols = {"SPY.US"} | mapped_symbols
    history_start = add_months(a.start, -a.cooldown_months)
    etf = {symbol: fetch(symbol, history_start, a.end, token, a.cache_dir) for symbol in sorted(symbols)}
    spy = {r["date"]: float(r["adjusted_close"]) for r in etf["SPY.US"] if r.get("adjusted_close") is not None}
    tickers = sorted({r["ticker"] for r in templates.values()}); q = ",".join("?" * len(tickers))
    con = duckdb.connect(); data = con.execute(f"SELECT UPPER(Ticker),CAST(Date AS DATE),Open FROM read_parquet(?) WHERE UPPER(Ticker) IN ({q}) ORDER BY 1,2", [str(a.parquet), *tickers]).fetchall(); con.close()
    opens: dict[str, list[tuple[date, float]]] = {}
    for ticker, observed, open_ in data: opens.setdefault(ticker, []).append((observed, float(open_)))
    def next_open(ticker: str, signal: date) -> tuple[date, float] | None:
        return next(((d, o) for d, o in opens.get(ticker, []) if d > signal), None)
    days = sorted(date.fromisoformat(day) for day in spy if a.start <= date.fromisoformat(day) <= a.end)
    external_events = {}
    for symbol in symbols - {"SPY.US"}:
        external_events[symbol] = [date.fromisoformat(day) for day in spy if history_start <= date.fromisoformat(day) <= a.end and (risk := state(etf.get(symbol, []), spy, day, 21, None)) and risk["vs_spy"] < 1 and risk["relative_volume"] >= a.min_relative_volume and risk["drawdown"] <= -a.drawdown]
    modes = a.entry_mode or ["existing"]
    matrix = []
    for entry_mode in modes:
      for threshold in thresholds:
        output_dir = a.output if len(thresholds) == len(modes) == 1 else a.output / f"{entry_mode}_min_open_lots_{threshold}"
        output_dir.mkdir(parents=True, exist_ok=True)
        matrix.append(simulate_threshold(threshold=threshold, entry_mode=entry_mode, external_events=external_events, days=days, by_entry=by_entry, templates=templates, mapping_resolver=mapping_resolver, etf=etf, spy=spy, next_open=next_open, output_dir=output_dir, cooldown_months=a.cooldown_months, min_relative_volume=a.min_relative_volume, drawdown=a.drawdown, monthly_budget=a.monthly_budget, cost=a.cost))
    for result in matrix:
        result["parameters"] = {"max_rank": a.max_rank, "cooldown_months": a.cooldown_months, "minimum_relative_volume": a.min_relative_volume, "drawdown": a.drawdown}
    write(a.output / "comparison.csv", matrix)
    result = {"thresholds": thresholds, "comparison": str(a.output / "comparison.csv"), "results": matrix, "limitation": "Current ETF mappings are sector/theme proxies, not dated ETF holdings. Research only."}
    (a.output / "summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__": main()
