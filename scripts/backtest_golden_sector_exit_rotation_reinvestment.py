#!/usr/bin/env python3
"""Research-only golden sector-exit ETF rotation with finite external capital.

The golden stock-selection and ETF mapping inputs are read-only.  This overlay
adds only the first N monthly contributions, rotates early-exit proceeds into
confirmed leading ETFs, and liquidates overlays to finance later stock entries.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from statistics import fmean

import duckdb

from backtest_etf_confirmed_momentum_overlay import fetch, rows, state, xirr
from backtest_sector_cooldown_momentum import add_months, load_mapping_resolver, load_price_alias_resolver, write


def next_bar(data: list[dict], observed: date) -> dict | None:
    return next((row for row in data if date.fromisoformat(row["date"]) > observed), None)


def select_rotation_targets(ranked: list[tuple[float, float, str]], *, selection: str, top_n: int, selected_minimum_relative_volume: float) -> list[str]:
    """Choose equal-weight price leaders or one unusually liquid leader from them."""
    price_leaders = ranked[:top_n]
    if selection == "equal_top_n":
        return [symbol for _, _, symbol in price_leaders]
    if selection == "highest_volume_top_n":
        if not price_leaders:
            return []
        _, relative_volume, symbol = max(price_leaders, key=lambda item: (item[1], item[0], item[2]))
        return [symbol] if relative_volume >= selected_minimum_relative_volume else []
    raise ValueError(f"unknown rotation selection: {selection}")


def rotation_leaders(*, universe: list[str], etf: dict[str, list[dict]], spy: dict[str, float], signal_date: date, confirmation_date: date, exclude_symbol: str, top_n: int, minimum_relative_volume: float, selection: str = "equal_top_n", selected_minimum_relative_volume: float = 0.0) -> list[str]:
    """Return completed-data ETF leaders, excluding the sector just exited."""
    ranked: list[tuple[float, float, str]] = []
    for symbol in universe:
        if symbol == exclude_symbol:
            continue
        data = etf.get(symbol, [])
        indexed = {row.get("date"): index for index, row in enumerate(data)}
        start, end = indexed.get(signal_date.isoformat()), indexed.get(confirmation_date.isoformat())
        if start is None or end is None or end < 50 or signal_date.isoformat() not in spy or confirmation_date.isoformat() not in spy:
            continue
        close = float(data[end]["adjusted_close"])
        sma21 = fmean(float(row["adjusted_close"]) for row in data[end - 20:end + 1])
        sma50 = fmean(float(row["adjusted_close"]) for row in data[end - 49:end + 1])
        volumes = [float(row.get("volume") or 0) for row in data[end - 21:end] if float(row.get("volume") or 0) > 0]
        relative_volume = float(data[end].get("volume") or 0) / fmean(volumes) if volumes else 0.0
        relative_return = (close / float(data[start]["adjusted_close"]) - 1) - (spy[confirmation_date.isoformat()] / spy[signal_date.isoformat()] - 1)
        if close > sma21 > sma50 and relative_volume >= minimum_relative_volume and relative_return > 0:
            ranked.append((relative_return, relative_volume, symbol))
    return select_rotation_targets(sorted(ranked, key=lambda item: (item[0], item[2]), reverse=True), selection=selection, top_n=top_n, selected_minimum_relative_volume=selected_minimum_relative_volume)


def liquidate_overlays(*, overlays: list[dict], etf: dict[str, list[dict]], observed: date, cost: float, exit_reason: str = "fund_golden_stock") -> tuple[float, list[dict]]:
    """Close all active overlays at the date's daily open and return net cash."""
    cash, closed = 0.0, []
    for lot in overlays:
        if not lot["active"]:
            continue
        bar = next((row for row in etf.get(lot["etf"], []) if row.get("date") == observed.isoformat()), None)
        if not bar or bar.get("open") is None:
            continue
        proceeds = lot["shares"] * float(bar["open"]) * (1 - cost)
        lot.update(active=False, exit_date=observed.isoformat(), exit_price=float(bar["open"]), exit_reason=exit_reason, net_proceeds=proceeds, net_profit=proceeds - lot["allocation"])
        cash += proceeds
        closed.append(lot.copy())
    return cash, closed


def pending_is_screenable(item: dict, observed: date, *, daily_until_maturity: bool, cash_until_maturity: bool) -> bool:
    """Keep the cash control free of ETF-selection information."""
    if cash_until_maturity:
        return False
    if daily_until_maturity:
        return item["confirmation_date"] <= observed < item["maturity_date"]
    return item["confirmation_date"] == observed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True); parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True); parser.add_argument("--mapping-intervals", type=Path, required=True); parser.add_argument("--price-aliases", type=Path, required=True)
    parser.add_argument("--rotation-universe", type=Path, required=True); parser.add_argument("--parquet", type=Path, default=Path("data/validated/sp500/eod_adjusted_current.parquet"))
    parser.add_argument("--start", type=date.fromisoformat, required=True); parser.add_argument("--end", type=date.fromisoformat, required=True); parser.add_argument("--rule", default="5M>3M>0"); parser.add_argument("--nominal-day", type=int, default=26); parser.add_argument("--max-rank", type=int, default=10)
    parser.add_argument("--min-sector-open-lots", type=int, default=4); parser.add_argument("--cooldown-months", type=int, default=6); parser.add_argument("--min-relative-volume", type=float, default=1.25); parser.add_argument("--drawdown", type=float, default=.10)
    parser.add_argument("--rotation-confirmation-sessions", type=int, default=2); parser.add_argument("--rotation-top-n", type=int, default=3); parser.add_argument("--rotation-min-relative-volume", type=float, default=1.0)
    parser.add_argument("--rotation-selection", choices=("equal_top_n", "highest_volume_top_n"), default="equal_top_n", help="Either split among the top price leaders or select the highest-relative-volume member of that group.")
    parser.add_argument("--rotation-selected-min-relative-volume", type=float, default=0.0, help="Extra relative-volume floor for highest_volume_top_n; 3.0 means 3x the preceding 21 sessions.")
    parser.add_argument("--funded-months", type=int, default=12); parser.add_argument("--monthly-budget", type=float, default=1000); parser.add_argument("--cost", type=float, default=.001); parser.add_argument("--exit-by-current-ticker-etf", action="store_true")
    maturity_mode = parser.add_mutually_exclusive_group()
    maturity_mode.add_argument("--daily-until-maturity", action="store_true", help="Experimental v2: recheck ETF leaders daily and close each sleeve at its source lot's twelve-month maturity.")
    maturity_mode.add_argument("--cash-until-maturity", action="store_true", help="Fair control: retain each early-exit lot as cash until its own twelve-month maturity; never buy a rotation ETF.")
    parser.add_argument("--cache-dir", type=Path, required=True); parser.add_argument("--token-env", default="EODHD_API_TOKEN"); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.funded_months, args.rotation_confirmation_sessions, args.rotation_top_n, args.min_sector_open_lots) < 1 or min(args.rotation_min_relative_volume, args.rotation_selected_min_relative_volume) < 0:
        parser.error("funded months, confirmation sessions, top N, and open-lot threshold must be positive; volume floors cannot be negative")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"set {args.token_env}; tokens are not accepted on the command line")
    args.output.mkdir(parents=True, exist_ok=True)

    resolver, mapped_symbols = load_mapping_resolver(args.mapping, args.mapping_intervals)
    alias_resolver, aliases = load_price_alias_resolver(args.price_aliases)
    rotation_universe = sorted({row["etf"].upper() for row in rows(args.rotation_universe) if row.get("status", "").lower() == "approved"})
    symbols = {"SPY.US"} | mapped_symbols | aliases | set(rotation_universe)
    history = add_months(args.start, -6)
    etf = {symbol: fetch(symbol, history, args.end, token, args.cache_dir) for symbol in sorted(symbols)}
    spy = {row["date"]: float(row["adjusted_close"]) for row in etf["SPY.US"] if row.get("adjusted_close") is not None}
    days = [date.fromisoformat(day) for day in sorted(spy) if args.start <= date.fromisoformat(day) <= args.end]
    candidates = [row for row in rows(args.candidates) if row["rule_name"] == args.rule and int(row["nominal_day"]) == args.nominal_day and args.start <= date.fromisoformat(row["execution_date"]) <= args.end and int(row["rank"]) <= args.max_rank]
    by_day: dict[date, list[dict]] = {}
    for row in candidates: by_day.setdefault(date.fromisoformat(row["execution_date"]), []).append(row)
    for group in by_day.values(): group.sort(key=lambda row: int(row["rank"]))
    templates = {(date.fromisoformat(row["execution_date"]), row["ticker"], row["rank"]): row for row in rows(args.templates) if row["rule"] == args.rule and int(row["nominal_day"]) == args.nominal_day}
    tickers = sorted({row["ticker"] for row in templates.values()})
    marks = ",".join("?" for _ in tickers)
    connection = duckdb.connect()
    try:
        raw = connection.execute(f"SELECT upper(Ticker), cast(Date as date), Open FROM read_parquet(?) WHERE upper(Ticker) IN ({marks}) ORDER BY 1,2", [str(args.parquet), *tickers]).fetchall()
    finally:
        connection.close()
    stock_opens: dict[str, list[tuple[date, float]]] = {}
    for ticker, observed, open_price in raw:
        if open_price is not None: stock_opens.setdefault(ticker, []).append((observed, float(open_price)))
    def next_stock_open(ticker: str, observed: date) -> tuple[date, float] | None:
        return next(((day, price) for day, price in stock_opens.get(ticker, []) if day > observed), None)

    active_stocks: list[dict] = []; completed_stocks: list[dict] = []; overlays: list[dict] = []; completed_overlays: list[dict] = []
    pending: list[dict] = []; scheduled: list[dict] = []; decisions: list[dict] = []; cash_ledger: list[dict] = []; mapping_review: list[dict] = []
    cooldown: dict[str, date] = {}; cash = 0.0; contribution_dates: list[date] = []; exited_ids: set[int] = set()
    managed_maturity = args.daily_until_maturity or args.cash_until_maturity
    for today_index, today in enumerate(days):
        # Mature stock holdings return cash at their template exit date.
        still_active = []
        for lot in active_stocks:
            if lot["exit_date"] <= today:
                proceeds = lot["shares"] * lot["exit_price"] * (1 - args.cost)
                lot.update(net_proceeds=proceeds, net_profit=proceeds - lot["allocation"]); completed_stocks.append(lot); cash += proceeds
                cash_ledger.append({"date": today.isoformat(), "event": "stock_maturity", "amount": proceeds, "cash_balance": cash, "reason": lot["ticker"]})
            else: still_active.append(lot)
        active_stocks = still_active
        if args.daily_until_maturity:
            raised, closed = liquidate_overlays(overlays=[lot for lot in overlays if lot.get("maturity_date") == today], etf=etf, observed=today, cost=args.cost, exit_reason="scheduled_stock_maturity")
            if raised:
                cash += raised; completed_overlays.extend(closed)
                cash_ledger.append({"date": today.isoformat(), "event": "overlay_scheduled_maturity", "amount": raised, "cash_balance": cash, "reason": "source_lot_maturity"})
        # Execute pre-scheduled ETF next-open purchases.
        for order in [value for value in scheduled if value["entry_date"] == today]:
            if managed_maturity and today >= order.get("maturity_date", date.max):
                cash += order["allocation"]
                cash_ledger.append({"date": today.isoformat(), "event": "rotation_entry_after_maturity", "amount": order["allocation"], "cash_balance": cash, "reason": order["etf"]})
                continue
            shares = order["allocation"] * (1 - args.cost) / order["entry_price"]
            overlays.append({**order, "shares": shares, "active": True, "exit_date": "", "exit_price": "", "exit_reason": "", "net_proceeds": "", "net_profit": ""})
        scheduled = [value for value in scheduled if value["entry_date"] > today]
        if managed_maturity:
            for item in [value for value in pending if value["maturity_date"] == today]:
                cash += item["amount"]
                cash_ledger.append({"date": today.isoformat(), "event": "rotation_cash_maturity", "amount": item["amount"], "cash_balance": cash, "reason": item["source_ticker"]})
        # V1 confirms once; v2 checks every completed day until the individual lot matures.
        eligible_pending = [value for value in pending if pending_is_screenable(value, today, daily_until_maturity=args.daily_until_maturity, cash_until_maturity=args.cash_until_maturity)]
        for item in eligible_pending:
            leaders = rotation_leaders(universe=rotation_universe, etf=etf, spy=spy, signal_date=item["signal_date"], confirmation_date=today, exclude_symbol=item["exit_etf"], top_n=args.rotation_top_n, minimum_relative_volume=args.rotation_min_relative_volume, selection=args.rotation_selection, selected_minimum_relative_volume=args.rotation_selected_min_relative_volume)
            if not leaders:
                if not args.daily_until_maturity:
                    cash += item["amount"]; cash_ledger.append({"date": today.isoformat(), "event": "rotation_no_leader", "amount": item["amount"], "cash_balance": cash, "reason": item["exit_etf"]})
                continue
            allocation = item["amount"] / len(leaders)
            for symbol in leaders:
                entry = next_bar(etf[symbol], today)
                if not entry or entry.get("open") is None:
                    cash += allocation; cash_ledger.append({"date": today.isoformat(), "event": "rotation_missing_open", "amount": allocation, "cash_balance": cash, "reason": symbol}); continue
                scheduled.append({"source_id": item.get("source_id"), "source_signal_date": item["signal_date"].isoformat(), "source_exit_etf": item["exit_etf"], "source_ticker": item.get("source_ticker", ""), "maturity_date": item.get("maturity_date", date.max), "etf": symbol, "entry_date": date.fromisoformat(entry["date"]), "entry_price": float(entry["open"]), "allocation": allocation})
        if args.cash_until_maturity:
            pending = [value for value in pending if today < value["maturity_date"]]
        elif args.daily_until_maturity:
            pending = [value for value in pending if value["confirmation_date"] > today or (today < value["maturity_date"] and not any(order.get("source_id") == value.get("source_id") for order in scheduled))]
        else:
            pending = [value for value in pending if value["confirmation_date"] > today]
        # Golden ETF risk-off exits, preserving one exit per active lot.
        sectors: dict[str, list[dict]] = {}
        for lot in active_stocks:
            current = resolver(lot["ticker"], today) if args.exit_by_current_ticker_etf else None
            mapped = current if current and current.get("status", "approved").lower() in {"", "approved"} else lot
            if str(mapped.get("sector_exit_eligible", "true")).lower() in {"true", "1", "yes"} and mapped.get("primary_etf"):
                sectors.setdefault(mapped["primary_etf"], []).append(lot)
        for symbol, lots in sectors.items():
            if len(lots) < args.min_sector_open_lots:
                continue
            price_symbol = alias_resolver(symbol, today); risk = state(etf.get(price_symbol, []), spy, today.isoformat(), 21, None)
            if not risk or not (risk["vs_spy"] < 1 and risk["relative_volume"] >= args.min_relative_volume and risk["drawdown"] <= -args.drawdown):
                continue
            for lot in lots:
                if id(lot) in exited_ids:
                    continue
                fill = next_stock_open(lot["ticker"], today)
                if not fill or fill[0] >= lot["exit_date"]:
                    continue
                exit_date, exit_price = fill; proceeds = lot["shares"] * exit_price * (1 - args.cost)
                lot.update(exit_date=exit_date, exit_price=exit_price, exit_reason="etf_rotation_risk_off", etf_signal_date=today.isoformat(), etf_price_symbol=price_symbol, net_proceeds=proceeds, net_profit=proceeds - lot["allocation"])
                completed_stocks.append(lot); active_stocks.remove(lot); exited_ids.add(id(lot))
                confirmation_index = today_index + args.rotation_confirmation_sessions
                maturity = add_months(date.fromisoformat(lot["execution_date"]), 12)
                if confirmation_index < len(days) and days[confirmation_index] < maturity:
                    pending.append({"source_id": id(lot), "source_ticker": lot["ticker"], "signal_date": today, "confirmation_date": days[confirmation_index], "maturity_date": maturity, "exit_etf": symbol, "amount": proceeds})
                else: cash += proceeds
            cooldown[symbol] = add_months(today, args.cooldown_months)
        if today not in by_day:
            continue
        month_number = len(decisions) + 1
        if month_number <= args.funded_months:
            cash += args.monthly_budget; contribution_dates.append(today); cash_ledger.append({"date": today.isoformat(), "event": "external_contribution", "amount": args.monthly_budget, "cash_balance": cash, "reason": f"month_{month_number}"})
        chosen = None; rejected = []
        for candidate in by_day[today]:
            mapped = resolver(candidate["ticker"], today)
            if not mapped:
                mapping_review.append({"execution_date": today.isoformat(), "ticker": candidate["ticker"], "rank": candidate["rank"], "reason": "missing_effective_dated_etf_mapping"}); rejected.append(f"{candidate['ticker']}:missing_mapping"); continue
            symbol = mapped.get("primary_etf", "")
            if mapped.get("status", "approved").lower() == "excluded" or today < cooldown.get(symbol, date.min):
                rejected.append(f"{candidate['ticker']}:sector_cooldown"); continue
            template = templates.get((today, candidate["ticker"], candidate["rank"]))
            if template: chosen = (candidate, mapped, template); break
        if cash < args.monthly_budget and overlays and not managed_maturity:
            raised, closed = liquidate_overlays(overlays=overlays, etf=etf, observed=today, cost=args.cost)
            if raised:
                cash += raised; completed_overlays.extend(closed); cash_ledger.append({"date": today.isoformat(), "event": "liquidate_overlays_for_stock", "amount": raised, "cash_balance": cash, "reason": "golden_entry_funding"})
        if not chosen:
            decisions.append({"execution_date": today.isoformat(), "decision": "cash", "reason": ";".join(rejected) or "no_candidate", "cash_balance": cash}); continue
        if cash < args.monthly_budget:
            decisions.append({"execution_date": today.isoformat(), "decision": "unfunded", "ticker": chosen[0]["ticker"], "rank_selected": chosen[0]["rank"], "reason": "insufficient_cash_after_overlay_liquidation", "cash_balance": cash}); continue
        candidate, mapped, template = chosen; allocation = args.monthly_budget; cash -= allocation
        shares = allocation * (1 - args.cost) / float(template["entry_price"])
        active_stocks.append({"execution_date": today.isoformat(), "signal_date": candidate["signal_date"], "ticker": candidate["ticker"], "rank_selected": candidate["rank"], "primary_etf": mapped["primary_etf"], "sector_exit_eligible": mapped.get("sector_exit_eligible", "true"), "entry_price": float(template["entry_price"]), "exit_date": date.fromisoformat(template["exit_date"] or template["valuation_date"]), "exit_price": float(template["exit_price"]), "exit_reason": template["exit_reason"], "etf_signal_date": "", "etf_price_symbol": "", "allocation": allocation, "shares": shares})
        decisions.append({"execution_date": today.isoformat(), "decision": "invested", "ticker": candidate["ticker"], "rank_selected": candidate["rank"], "reason": "golden_rank_selection", "cash_balance": cash})
    # End valuation: unfinished reservations/orders become cash; active overlays are marked at final close.
    for item in pending: cash += item["amount"]
    for order in scheduled: cash += order["allocation"]
    for lot in overlays:
        if not lot["active"]: continue
        bars = [row for row in etf.get(lot["etf"], []) if row.get("date") <= args.end.isoformat() and row.get("adjusted_close") is not None]
        if bars:
            close = float(bars[-1]["adjusted_close"]); proceeds = lot["shares"] * close * (1 - args.cost)
            lot.update(active=False, exit_date=bars[-1]["date"], exit_price=close, exit_reason="end_valuation", net_proceeds=proceeds, net_profit=proceeds - lot["allocation"]); completed_overlays.append(lot); cash += proceeds
        else: cash += lot["allocation"]
    for lot in active_stocks:
        # Templates already provide the as-of-end valuation in the canonical golden inputs.
        proceeds = lot["shares"] * lot["exit_price"] * (1 - args.cost); lot.update(net_proceeds=proceeds, net_profit=proceeds-lot["allocation"]); completed_stocks.append(lot); cash += proceeds
    # Every closed stock/ETF lot either entered cash immediately, was reserved
    # for a pending ETF allocation, or was converted into an active overlay.
    # Those amounts are now all settled into ``cash``; adding closed proceeds a
    # second time would double-count the same portfolio capital.
    portfolio_value = cash
    contributions = len(contribution_dates) * args.monthly_budget
    flows = [(day, -args.monthly_budget) for day in contribution_dates] + [(args.end, portfolio_value)]
    mode = "daily_etf_rotation_until_maturity" if args.daily_until_maturity else "cash_until_maturity_control" if args.cash_until_maturity else "legacy_rotation"
    result = {"mode": mode, "rotation_selection": args.rotation_selection, "rotation_selected_min_relative_volume": args.rotation_selected_min_relative_volume, "funded_months": args.funded_months, "external_contributions": contributions, "stock_trade_count": len(completed_stocks), "etf_overlay_trade_count": len(completed_overlays), "unfunded_months": sum(row["decision"] == "unfunded" for row in decisions), "portfolio_value": portfolio_value, "net_profit": portfolio_value-contributions, "roi": portfolio_value/contributions-1 if contributions else 0, "xirr": xirr(flows), "mapping_review_count": len(mapping_review), "incomplete_mapping_review": bool(mapping_review)}
    all_trades = [{"trade_type": "golden_stock", **lot} for lot in completed_stocks] + [{"trade_type": "rotation_etf", **lot} for lot in completed_overlays]
    all_trades.sort(key=lambda row: (str(row.get("execution_date") or row.get("entry_date") or ""), row["trade_type"], str(row.get("ticker") or row.get("etf") or "")))
    write(args.output / "stock_trades.csv", completed_stocks); write(args.output / "etf_overlay_trades.csv", completed_overlays); write(args.output / "all_trades.csv", all_trades); write(args.output / "monthly_decisions.csv", decisions); write(args.output / "cash_ledger.csv", cash_ledger); write(args.output / "mapping_review_required.csv", mapping_review); write(args.output / "comparison.csv", [result]); (args.output / "summary.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__": main()
