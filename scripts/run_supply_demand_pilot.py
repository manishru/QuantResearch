"""Run the declared two-candidate S&P 500 supply/demand feasibility pilot."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from quantresearch.domain.exclusions import apply_exclusions
from quantresearch.ingestion.component_csv import load_component_snapshots
from quantresearch.ingestion.parquet_bars import (
    approved_provider_to_constituent,
    load_adjusted_bars,
)
from quantresearch.ingestion.review_decisions import (
    load_exclusion_decisions,
    load_mapping_decisions,
)
from quantresearch.research.demand_evaluator import DemandFoldEvaluator, ValidatedDataVersion
from quantresearch.search.bounded import BoundedGridSearch
from quantresearch.search.models import HardConstraints, SearchPlan
from quantresearch.simulation.demand import DemandSimulationConfig
from quantresearch.strategies.supply_demand import (
    SupplyDemandParameters,
    daily_supply_demand,
)
from quantresearch.walkforward.models import ForwardState
from quantresearch.walkforward.replay import ReplayPeriod
from quantresearch.walkforward.windows import generate_walk_forward_windows

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/sp500"
VALIDATED = ROOT / "data/validated/sp500"
OUTPUT = ROOT / "reports/supply_demand_pilot_v2"


def pilot_candidates() -> tuple[SupplyDemandParameters, ...]:
    return (
        SupplyDemandParameters(),
        SupplyDemandParameters(
            previous_range_ratio=2.5, departure_range_ratio=4.0,
            base_atr_ratio=0.45, departure_body_ratio=0.7, volume_multiplier=1.5,
        ),
    )


def _metrics(evaluation) -> dict[str, object]:
    return {
        "cagr": evaluation.performance.cagr,
        "average_yearly_return": evaluation.performance.average_calendar_year_return,
        "maximum_drawdown": evaluation.performance.maximum_drawdown,
        "sharpe": evaluation.performance.sharpe,
        "trade_count": len(evaluation.result.trades),
        "win_rate": evaluation.performance.win_rate,
        "profit_factor": evaluation.performance.profit_factor,
        "ending_equity": evaluation.result.ending_equity,
        "membership_violation_count": evaluation.membership_violation_count,
    }


def _write_trades(path: Path, fold_id: str, evaluation) -> None:
    fields = [
        "fold_id", "ticker", "quantity", "entry_date", "entry_price",
        "exit_date", "exit_price", "entry_commission", "exit_commission",
        "tax_haircut", "net_profit",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in evaluation.result.trades:
            writer.writerow(
                {
                    "fold_id": fold_id,
                    "ticker": trade.ticker,
                    "quantity": trade.quantity,
                    "entry_date": trade.entry_date.isoformat(),
                    "entry_price": trade.entry_price,
                    "exit_date": trade.exit_date.isoformat() if trade.exit_date else "",
                    "exit_price": trade.exit_price if trade.exit_price is not None else "",
                    "entry_commission": trade.entry_commission,
                    "exit_commission": trade.exit_commission,
                    "tax_haircut": trade.tax_haircut,
                    "net_profit": trade.net_profit if trade.net_profit is not None else "",
                }
            )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mappings = load_mapping_decisions(VALIDATED / "mapping_decisions_operator.csv")
    exclusions = load_exclusion_decisions(VALIDATED / "exclusion_decisions_operator.csv")
    manifest = json.loads((VALIDATED / "eligible_universe_manifest.json").read_text())
    if not manifest["optimization_allowed"] or not mappings.ready or not exclusions.ready:
        raise RuntimeError("Validated point-in-time data gate is not open")
    membership = apply_exclusions(
        load_component_snapshots(
            RAW / "S&P 500 Historical Components & Changes (Updated).csv",
            index_id="SP500",
        ),
        exclusions.registry,
        decision_sha256=exclusions.source_sha256,
    )
    aliases = approved_provider_to_constituent(mappings.registry, "EODHD")
    data_version = ValidatedDataVersion(
        "sp500-eligible-operator-v1", manifest["eligible_history_version"], True
    )
    candidates = pilot_candidates()
    simulation = DemandSimulationConfig(
        initial_cash=100_000,
        risk_fraction=0.01,
        maximum_position_weight=0.10,
        max_positions=10,
        commission_bps=1.0,
        slippage_bps=5.0,
    )
    evaluator = DemandFoldEvaluator(simulation)
    summaries: list[dict[str, object]] = []

    for fold_number, window in enumerate(generate_walk_forward_windows(1996, 2025), start=1):
        fold_id = f"fold_{fold_number:02d}"
        fold_path = OUTPUT / f"{fold_id}.json"
        if fold_path.exists():
            summaries.append(json.loads(fold_path.read_text()))
            print(f"{fold_id}: checkpoint reused", flush=True)
            continue
        data_end = (
            window.train_end
            if window.forward_state is ForwardState.LIVE_UNOBSERVED
            else window.forward_end
        )
        membership_start = max(window.warmup_start, membership.first_snapshot_date)
        relevant_constituents = set(membership.as_of(membership_start).symbols)
        for snapshot in membership.snapshots:
            if membership_start < snapshot.effective_date <= data_end:
                relevant_constituents.update(snapshot.symbols)
        constituent_to_provider = {value: key for key, value in aliases.items()}
        included_provider_symbols = frozenset(
            constituent_to_provider.get(symbol, symbol)
            for symbol in relevant_constituents
        )
        bars = load_adjusted_bars(
            RAW / "eod_final_1996-01-01_to_2026-07-12.parquet",
            start=max(window.warmup_start, date(1996, 1, 1)),
            end=data_end,
            provider_to_constituent=aliases,
            included_provider_symbols=included_provider_symbols,
        )
        evaluations = {}
        plan = SearchPlan(
            experiment_id=f"supply-demand-pilot-v2-{fold_id}",
            parameters={"candidate_index": tuple(range(len(candidates)))},
            budget=len(candidates),
            constraints=HardConstraints(
                maximum_drawdown_fraction=0.40,
                minimum_average_entries_per_year=0,
                minimum_entries_each_year=0,
                maximum_position_weight=0.10,
                allow_anomalies=False,
            ),
            score_weights={
                "cagr": 0.25,
                "average_yearly_return": 0.20,
                "sharpe": 0.30,
                "drawdown": 0.25,
            },
        )

        def evaluate_candidate(
            values,
            *,
            fold_bars=bars,
            fold_window=window,
            fold_evaluations=evaluations,
            current_fold_id=fold_id,
        ):
            index = int(values["candidate_index"])
            evaluation = evaluator.evaluate(
                bars=fold_bars,
                membership_history=membership,
                window=fold_window,
                period=ReplayPeriod.TRAINING,
                parameters=candidates[index],
                data_version=data_version,
            )
            fold_evaluations[index] = evaluation
            print(
                f"{current_fold_id}: candidate {index + 1}/{len(candidates)} "
                f"trades={len(evaluation.result.trades)} "
                f"cagr={evaluation.performance.cagr:.4%}",
                flush=True,
            )
            return evaluation.candidate_metrics

        search = BoundedGridSearch(plan).run(evaluate_candidate)
        selected = search.selected
        if selected is None:
            raise RuntimeError(f"{fold_id} produced no selectable pilot candidate")
        selected_index = int(selected.parameters["candidate_index"])
        forward = None
        if window.forward_state is ForwardState.AVAILABLE:
            forward = evaluator.evaluate(
                bars=bars,
                membership_history=membership,
                window=window,
                period=ReplayPeriod.FORWARD,
                parameters=candidates[selected_index],
                data_version=data_version,
            )
            _write_trades(OUTPUT / f"{fold_id}_forward_trades.csv", fold_id, forward)
        summary = {
            "fold_id": fold_id,
            "window": window.to_dict(),
            "pilot_non_final": True,
            "selected_candidate_index": selected_index,
            "selected_strategy_id": daily_supply_demand(
                "SP500", candidates[selected_index]
            ).strategy_id,
            "selected_parameters": asdict(candidates[selected_index]),
            "training": _metrics(evaluations[selected_index]),
            "forward": _metrics(forward) if forward else None,
            "candidates": [
                {
                    **item.to_dict(),
                    "actual_parameters": asdict(
                        candidates[int(item.parameters["candidate_index"])]
                    ),
                }
                for item in search.results
            ],
        }
        fold_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        summaries.append(summary)
        print(f"{fold_id}: published", flush=True)

    completed = [item for item in summaries if item["forward"] is not None]
    final = {
        "run": "supply-demand-pilot-v2",
        "pilot_non_final": True,
        "fold_count": len(summaries),
        "completed_forward_folds": len(completed),
        "total_forward_trades": sum(item["forward"]["trade_count"] for item in completed),
        "folds": summaries,
    }
    (OUTPUT / "summary.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    print(f"Pilot complete: {OUTPUT / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
