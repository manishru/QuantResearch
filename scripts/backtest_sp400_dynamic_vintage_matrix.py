#!/usr/bin/env python3
"""Rank S&P 400 momentum rules using holding-period-matched monthly vintages.

Each configuration begins with exactly ``--total-capital``.  Its number of
initial monthly sleeves is ``ceil(holding_weeks / 4)`` and each sleeve receives
an equal share.  A sleeve reinvests its actual proceeds at the next scheduled
monthly entry after it exits.  This preserves the user's requested staggered
capital schedule rather than comparing every hold length with five sleeves.
"""
from __future__ import annotations

import argparse, bisect, csv, heapq, json, math, re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb

from backtest_sp400_proxy_momentum_matrix import RULES, scheduled_sessions, xirr


def csv_write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, default=Path("data/validated/sp400/eodhd_sp400_proxy_eod.duckdb"))
    p.add_argument("--membership", type=Path, default=Path("reports/sp400_wikipedia_reverse_membership_2016_2026/membership_intervals.csv"))
    p.add_argument("--corporate-action-exits", type=Path, default=Path("config/experiments/sp400_proxy_corporate_action_exits.csv"))
    p.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--days", default="1-31")
    p.add_argument("--entry-months", default="1-12", help="Calendar months to trade, e.g. 3,6,9,12.")
    p.add_argument("--holding-weeks", default="4,6,8,12,16,20,24,28,32,36,40,44,48,52")
    p.add_argument("--stops", default=".20,.25,.30")
    p.add_argument("--rule", action="append", choices=sorted(RULES))
    p.add_argument("--total-capital", type=float, default=12000.0)
    p.add_argument("--sleeve-count", type=int, help="Override ceil(holding_weeks/4), for explicitly spaced schedules such as quarterly trading.")
    p.add_argument("--cost", type=float, default=.001)
    p.add_argument("--candidate-depth", type=int, default=20)
    p.add_argument("--unique-open-tickers-for", choices=("1M>0", "all", "none"), default="1M>0")
    p.add_argument("--duplicate-fallback-rank-one", action="store_true",
                   help="If ranks 1-2 are blocked by active holdings, permit a duplicate purchase of valid rank 1 rather than leave the sleeve in cash."
                   )
    p.add_argument("--duplicate-fallback-rank-two", action="store_true",
                   help="If ranks 1-2 are blocked by active holdings, permit a duplicate purchase of valid rank 2 rather than leave the sleeve in cash."
                   )
    p.add_argument("--rescreen-empty-next-month-first-day", action="store_true",
                   help="When a scheduled screen has no qualifying stocks, re-screen after the following month's first trading-day close and enter at its next open.")
    p.add_argument("--renewal-mode", choices=("fixed_monthly_vintage", "next_available"), default="fixed_monthly_vintage",
                   help="fixed_monthly_vintage preserves each initial monthly sleeve's cadence; early-exit cash waits for that sleeve's next cycle.")
    p.add_argument("--top-ledgers", type=int, default=5)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.duplicate_fallback_rank_one and a.duplicate_fallback_rank_two:
        p.error("choose only one duplicate fallback rank")
    out = a.output.expanduser().resolve(); out.mkdir(parents=True, exist_ok=True)

    def parse_ints(value: str) -> list[int]:
        values: set[int] = set()
        for part in value.split(","):
            if "-" in part:
                left, right = map(int, part.split("-", 1)); values.update(range(left, right + 1))
            else: values.add(int(part))
        return sorted(values)
    days, weeks_values = parse_ints(a.days), parse_ints(a.holding_weeks)
    entry_months = parse_ints(a.entry_months)
    if not entry_months or any(month < 1 or month > 12 for month in entry_months):
        p.error("entry months must be between 1 and 12")
    if a.sleeve_count is not None and a.sleeve_count < 1:
        p.error("sleeve count must be positive")
    stops = [float(x) for x in a.stops.split(",")]
    rules = a.rule or sorted(RULES)
    if a.total_capital <= 0 or a.candidate_depth < 1: p.error("capital and candidate depth must be positive")

    intervals: dict[str, list[tuple[date, date]]] = defaultdict(list)
    with a.membership.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            intervals[row["ticker"].upper()].append((date.fromisoformat(row["effective_from"]), date.fromisoformat(row["effective_to"])))
    actions: dict[str, tuple[date, float]] = {}
    if a.corporate_action_exits.is_file():
        with a.corporate_action_exits.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                actions[row["ticker"].upper()] = (date.fromisoformat(row["effective_date"]), float(row["cash_exit_price"]))

    con = duckdb.connect(str(a.database), read_only=True)
    try:
        rows = con.execute("""SELECT ticker, observed, open, close, adjusted_close
            FROM sp400_proxy_prices WHERE observed BETWEEN ? AND ?
            AND open > 0 AND close > 0 AND adjusted_close > 0 ORDER BY ticker, observed""",
            [a.start - timedelta(days=430), a.end]).fetchall()
    finally:
        con.close()
    raw: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    session_set: set[date] = set()
    for ticker, observed, opening, closing, adjusted_close in rows:
        factor = float(adjusted_close) / float(closing)
        raw[ticker].append((observed, float(opening) * factor, float(adjusted_close)))
        if observed >= a.start: session_set.add(observed)
    prices = {ticker: ([x[0] for x in values], [x[1] for x in values], [x[2] for x in values]) for ticker, values in raw.items()}
    sessions = sorted(session_set)
    schedules = {day: [pair for pair in scheduled_sessions(sessions, a.start, a.end, day) if pair[1].month in entry_months] for day in days}

    def is_member(ticker: str, signal: date, entry: date) -> bool:
        return any(left <= signal <= right and left <= entry <= right for left, right in intervals.get(ticker, []))
    # Selection is calculated just once per rule/day/month and used by every
    # stop/holding portfolio variant.
    candidates: dict[tuple[str, int, date], list[tuple[str, int, float]]] = {}
    rescreen_candidates: dict[tuple[str, int, date], tuple[date, date, list[tuple[str, int, float]]]] = {}

    def ranked_candidates(rule: str, signal: date, entry: date) -> list[tuple[str, int, float]]:
        needed = set(re.findall(r"ret\d+", RULES[rule])); lead = max(int(x[3:]) for x in needed); rank_name = f"ret{lead}"
        ranked: list[tuple[float, str, int]] = []
        for ticker, (ticker_days, ticker_opens, ticker_closes) in prices.items():
            i, ei = bisect.bisect_left(ticker_days, signal), bisect.bisect_left(ticker_days, entry)
            if i >= len(ticker_days) or ticker_days[i] != signal or i < lead or ei >= len(ticker_days) or ticker_days[ei] != entry or not is_member(ticker, signal, entry):
                continue
            returns = {f"ret{h}": ticker_closes[i] / ticker_closes[i-h] - 1 if i >= h else None for h in (21,42,63,84,105,126,147,168,189,210,231,252)}
            if all(returns[x] is not None for x in needed) and eval(RULES[rule], {"__builtins__": {}}, returns):
                ranked.append((returns[rank_name], ticker, ei))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        return [(ticker, index, score) for score, ticker, index in ranked[:a.candidate_depth]]

    for rule in rules:
        for day, schedule in schedules.items():
            for signal, entry in schedule:
                primary = ranked_candidates(rule, signal, entry)
                candidates[(rule, day, entry)] = primary
                if a.rescreen_empty_next_month_first_day and not primary:
                    next_month = date(entry.year + (entry.month == 12), entry.month % 12 + 1, 1)
                    first_i = bisect.bisect_left(sessions, next_month)
                    if first_i + 1 < len(sessions) and sessions[first_i] <= a.end and sessions[first_i + 1] <= a.end:
                        resignal, reentry = sessions[first_i], sessions[first_i + 1]
                        rescreen_candidates[(rule, day, entry)] = (resignal, reentry, ranked_candidates(rule, resignal, reentry))

    outcome_cache: dict[tuple[str, int, int, float], tuple[date, float, str]] = {}
    def outcome(ticker: str, entry_index: int, weeks: int, stop: float) -> tuple[date, float, str]:
        key = (ticker, entry_index, weeks, stop)
        if key in outcome_cache: return outcome_cache[key]
        ticker_days, ticker_opens, ticker_closes = prices[ticker]
        entry_price = ticker_opens[entry_index] * (1 + a.cost)
        maturity_i = bisect.bisect_left(ticker_days, ticker_days[entry_index] + timedelta(days=weeks * 7))
        last = bisect.bisect_right(ticker_days, a.end) - 1
        for i in range(entry_index, min(maturity_i, last) + 1):
            if ticker_closes[i] <= entry_price * (1 - stop):
                exit_i = min(i + 1, last); result = (ticker_days[exit_i], ticker_opens[exit_i] * (1-a.cost), "stop_close_next_open"); outcome_cache[key] = result; return result
        action = actions.get(ticker)
        if maturity_i > last and action and ticker_days[entry_index] <= action[0] <= a.end:
            result = (action[0], action[1] * (1-a.cost), "corporate_action_cash_exit"); outcome_cache[key] = result; return result
        if maturity_i <= last:
            exit_i = min(maturity_i + 1, last); result = (ticker_days[exit_i], ticker_opens[exit_i] * (1-a.cost), "scheduled_maturity"); outcome_cache[key] = result; return result
        result = (ticker_days[last], ticker_closes[last] * (1-a.cost), "open_mtm"); outcome_cache[key] = result; return result

    def simulate(rule: str, day: int, weeks: int, stop: float) -> tuple[dict, list[dict]]:
        signal_by_entry = {entry: signal for signal, entry in schedules[day]}
        entries = list(signal_by_entry)
        sleeve_count = a.sleeve_count or math.ceil(weeks / 4)
        initial = entries[:sleeve_count]
        allocation = a.total_capital / sleeve_count
        unique = a.unique_open_tickers_for == "all" or (a.unique_open_tickers_for == "1M>0" and rule == "1M>0")
        if a.renewal_mode == "fixed_monthly_vintage":
            # The nth initial sleeve can only renew at entry indexes n,
            # n+sleeve_count, n+2*sleeve_count, ... .  This is deliberately
            # different from deploying early-stop cash immediately: it keeps
            # the original monthly capital stagger intact.
            scheduled: list[tuple[date, int]] = []
            for sleeve in range(1, sleeve_count + 1):
                for index in range(sleeve - 1, len(entries), sleeve_count):
                    scheduled.append((entries[index], sleeve))
            scheduled.sort()
            capital = {sleeve: allocation for sleeve in range(1, sleeve_count + 1)}
            last_exit = {sleeve: date.min for sleeve in range(1, sleeve_count + 1)}
            last_reason = {sleeve: "" for sleeve in range(1, sleeve_count + 1)}
            last_trade_id = {sleeve: "" for sleeve in range(1, sleeve_count + 1)}
            last_ticker = {sleeve: "" for sleeve in range(1, sleeve_count + 1)}
            sequence = {sleeve: 0 for sleeve in range(1, sleeve_count + 1)}
            active: list[tuple[date, str]] = []; ledger: list[dict] = []
            for entry, sleeve in scheduled:
                # If the prior fixed-cycle position has not yet exited, this
                # sleeve cannot deploy a second lot. This should be rare as
                # cycles are rounded upward from the holding period.
                if last_reason[sleeve] == "open_mtm":
                    continue
                selection_signal, selection_entry, selection_source = signal_by_entry[entry], entry, "scheduled_monthly_screen"
                candidate_list = candidates[(rule, day, entry)]
                if not candidate_list and a.rescreen_empty_next_month_first_day:
                    rescreen = rescreen_candidates.get((rule, day, entry))
                    if rescreen is not None:
                        selection_signal, selection_entry, candidate_list = rescreen
                        selection_source = "next_month_first_day_rescreen"
                if last_exit[sleeve] >= selection_entry:
                    continue
                active = [(exit_day, ticker) for exit_day, ticker in active if exit_day >= selection_entry]
                active_tickers = {ticker for _, ticker in active}
                selected = None; selected_outcome = None
                rank_one_fallback = None
                rank_two_fallback = None
                used_rank_one_duplicate_fallback = False
                used_rank_two_duplicate_fallback = False
                for candidate_rank, candidate in enumerate(candidate_list, 1):
                    candidate_outcome = outcome(candidate[0], candidate[1], weeks, stop)
                    # A price series that ended before the final available
                    # market session is not a live position.  Move to the
                    # next ranked candidate instead of retaining bad data.
                    if candidate_outcome[2] == "open_mtm" and candidate_outcome[0] < sessions[-1]:
                        continue
                    if rank_one_fallback is None:
                        rank_one_fallback = (candidate, candidate_outcome)
                    if candidate_rank == 2:
                        rank_two_fallback = (candidate, candidate_outcome)
                    if unique and candidate[0] in active_tickers:
                        continue
                    selected, selected_outcome = candidate, candidate_outcome
                    break
                # This optional policy is deliberately narrow: only rank 1
                # may be duplicated, never rank 3+, and only after its price
                # path has passed the same stale/delisted validity checks.
                if selected is None and a.duplicate_fallback_rank_one and rank_one_fallback is not None:
                    selected, selected_outcome = rank_one_fallback
                    used_rank_one_duplicate_fallback = True
                if selected is None and a.duplicate_fallback_rank_two and rank_two_fallback is not None:
                    selected, selected_outcome = rank_two_fallback
                    used_rank_two_duplicate_fallback = True
                if selected is None:
                    continue
                ticker, entry_index, score = selected
                exit_day, exit_price, reason = selected_outcome
                entry_price = prices[ticker][1][entry_index] * (1 + a.cost)
                proceeds = capital[sleeve] * exit_price / entry_price
                sequence[sleeve] += 1
                trade_id = f"V{sleeve:02d}-{initial[sleeve-1].isoformat()}-T{sequence[sleeve]:03d}"
                selection_mode = "rank1_duplicate_fallback" if used_rank_one_duplicate_fallback else ("rank2_duplicate_fallback" if used_rank_two_duplicate_fallback else "distinct_rank_selection")
                ledger.append({"rule": rule, "nominal_day": day, "holding_weeks": weeks, "stop": stop, "sleeve_count": sleeve_count, "renewal_mode": a.renewal_mode, "vintage_id": f"V{sleeve:02d}-{initial[sleeve-1].isoformat()}", "trade_id": trade_id, "parent_trade_id": last_trade_id[sleeve], "sequence": sequence[sleeve], "capital": capital[sleeve], "signal_date": selection_signal, "entry_date": selection_entry, "selection_source": selection_source, "ticker": ticker, "rank_used": next(i for i,x in enumerate(candidate_list,1) if x[0] == ticker), "selection_mode": selection_mode, "ranking_return": score, "entry_price_adjusted": entry_price, "exit_date": exit_day, "exit_price_adjusted": exit_price, "exit_reason": reason, "return_factor": proceeds/capital[sleeve], "proceeds": proceeds, "net_profit": proceeds-capital[sleeve], "net_return": proceeds/capital[sleeve]-1})
                capital[sleeve], last_exit[sleeve], last_reason[sleeve], last_trade_id[sleeve], last_ticker[sleeve] = proceeds, exit_day, reason, trade_id, ticker
                active.append((exit_day, ticker))
            final = sum(capital.values())
            unresolved = sum(t["exit_reason"] == "open_mtm" and t["exit_date"] < sessions[-1] for t in ledger)
            result = {"rule": rule, "nominal_day": day, "entry_months": ",".join(map(str, entry_months)), "holding_weeks": weeks, "stop": stop, "sleeve_count": sleeve_count, "renewal_mode": a.renewal_mode, "initial_sleeve_allocation": allocation, "total_capital": a.total_capital, "final_value": final, "roi": final/a.total_capital-1, "xirr": xirr([(entry, -allocation) for entry in initial] + [(a.end, final)]), "trade_count": len(ledger), "win_rate": sum(t["net_return"] > 0 for t in ledger)/len(ledger) if ledger else None, "unresolved_open_mtm": unresolved, "eligible_for_ranking": unresolved == 0, "unique_open_tickers": unique, "duplicate_fallback_rank_one": a.duplicate_fallback_rank_one, "duplicate_fallback_rank_two": a.duplicate_fallback_rank_two}
            return result, ledger
        events: list[tuple[date, int, int, tuple]] = []
        serial = 0
        for sleeve, entry in enumerate(initial, 1):
            heapq.heappush(events, (entry, 1, serial, ("entry", sleeve, entry, allocation, "", 1))); serial += 1
        active: set[str] = set(); finals: list[tuple[date, float]] = []; ledger: list[dict] = []
        while events:
            when, _, _, payload = heapq.heappop(events)
            if payload[0] == "exit":
                _, sleeve, ticker, capital, exit_day, parent, sequence = payload
                if unique: active.remove(ticker)
                next_entry = next((d for d in entries if d > exit_day and d <= a.end), None)
                if next_entry is None: finals.append((exit_day, capital))
                else:
                    heapq.heappush(events, (next_entry, 1, serial, ("entry", sleeve, next_entry, capital, parent, sequence + 1))); serial += 1
                continue
            _, sleeve, entry, capital, parent, sequence = payload
            selected = next((x for x in candidates[(rule, day, entry)] if not unique or x[0] not in active), None)
            if selected is None:
                next_entry = next((d for d in entries if d > entry and d <= a.end), None)
                if next_entry is None: finals.append((entry, capital))
                else: heapq.heappush(events, (next_entry, 1, serial, ("entry", sleeve, next_entry, capital, parent, sequence))); serial += 1
                continue
            ticker, entry_index, score = selected
            if unique: active.add(ticker)
            exit_day, exit_price, reason = outcome(ticker, entry_index, weeks, stop)
            entry_price = prices[ticker][1][entry_index] * (1+a.cost); proceeds = capital * exit_price / entry_price
            trade_id = f"V{sleeve:02d}-{initial[sleeve-1].isoformat()}-T{sequence:03d}"
            ledger.append({"rule": rule, "nominal_day": day, "holding_weeks": weeks, "stop": stop, "sleeve_count": sleeve_count, "vintage_id": f"V{sleeve:02d}-{initial[sleeve-1].isoformat()}", "trade_id": trade_id, "parent_trade_id": parent, "sequence": sequence, "capital": capital, "entry_date": entry, "ticker": ticker, "rank_used": next(i for i,x in enumerate(candidates[(rule, day, entry)],1) if x[0] == ticker), "ranking_return": score, "entry_price_adjusted": entry_price, "exit_date": exit_day, "exit_price_adjusted": exit_price, "exit_reason": reason, "return_factor": proceeds/capital, "proceeds": proceeds, "net_profit": proceeds-capital, "net_return": proceeds/capital-1})
            if reason == "open_mtm": finals.append((a.end, proceeds))
            else: heapq.heappush(events, (exit_day, 0, serial, ("exit", sleeve, ticker, proceeds, exit_day, trade_id, sequence))); serial += 1
        final = sum(value for _, value in finals)
        # ``--end`` can be a weekend/non-trading date.  A mark-to-market on
        # the final available market session is a live position, not a missing
        # delisting resolution.  Only an earlier stale final quote is excluded.
        unresolved = sum(t["exit_reason"] == "open_mtm" and t["exit_date"] < sessions[-1] for t in ledger)
        result = {"rule": rule, "nominal_day": day, "holding_weeks": weeks, "stop": stop, "sleeve_count": sleeve_count, "initial_sleeve_allocation": allocation, "total_capital": a.total_capital, "final_value": final, "roi": final/a.total_capital-1, "xirr": xirr([(entry, -allocation) for entry in initial] + finals), "trade_count": len(ledger), "win_rate": sum(t["net_return"] > 0 for t in ledger)/len(ledger) if ledger else None, "unresolved_open_mtm": unresolved, "eligible_for_ranking": unresolved == 0, "unique_open_tickers": unique}
        return result, ledger

    results: list[dict] = []
    total = len(rules)*len(days)*len(weeks_values)*len(stops); done = 0
    for rule in rules:
        for day in days:
            for weeks in weeks_values:
                for stop in stops:
                    # Retaining every ledger would hold millions of Python
                    # dictionaries in memory.  Keep only the summary during
                    # the matrix pass, then replay the final five below.
                    result, _ = simulate(rule, day, weeks, stop); results.append(result); done += 1
                    if done % 1000 == 0 or done == total: print(f"[{done}/{total}]", flush=True)
    results.sort(key=lambda r: (not r["eligible_for_ranking"], -r["final_value"]))
    csv_write(out / "dynamic_vintage_matrix_summary.csv", results)
    eligible = [r for r in results if r["eligible_for_ranking"]][:a.top_ledgers]
    top_rows: list[dict] = []
    for rank, result in enumerate(eligible, 1):
        result = {"strategy_rank": rank, **result}; top_rows.append(result)
        _, ledger = simulate(result["rule"], result["nominal_day"], result["holding_weeks"], result["stop"])
        csv_write(out / f"top_{rank:02d}_trade_ledger.csv", ledger)
    csv_write(out / "top_5_dynamic_vintage_strategies.csv", top_rows)
    (out / "summary.json").write_text(json.dumps({"configurations": total, "total_capital": a.total_capital, "dynamic_sleeves": "ceil(holding_weeks / 4)", "top_5": str(out / "top_5_dynamic_vintage_strategies.csv")}, indent=2, default=str) + "\n")
    print(json.dumps({"configurations": total, "top_5": str(out / "top_5_dynamic_vintage_strategies.csv")}, indent=2))


if __name__ == "__main__":
    main()
