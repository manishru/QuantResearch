"""Reference fold evaluator for the registered daily demand strategy."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.domain.membership import MembershipHistory
from quantresearch.features.supply_demand import (
    SupplyDemandConfig,
    compute_supply_demand_features,
)
from quantresearch.search.models import CandidateMetrics
from quantresearch.simulation.demand import DemandSimulationConfig, DemandTradeSimulator
from quantresearch.simulation.metrics import PerformanceReport, calculate_performance
from quantresearch.simulation.models import Bar, SimulationResult
from quantresearch.strategies.supply_demand import SupplyDemandParameters
from quantresearch.strategies.supply_demand_signals import build_demand_trade_plans
from quantresearch.walkforward.models import WalkForwardWindow
from quantresearch.walkforward.replay import ReplayPeriod


@dataclass(frozen=True, slots=True)
class ValidatedDataVersion:
    version_id: str
    sha256: str
    validated: bool

    def __post_init__(self) -> None:
        if not self.version_id.strip() or len(self.sha256) != 64:
            raise ValueError("A data version ID and SHA-256 digest are required")
        if not self.validated:
            raise ValueError("Demand fold evaluation requires a validated data version")


@dataclass(frozen=True, slots=True)
class DemandFoldEvaluation:
    window_id: str
    period: ReplayPeriod
    parameters: SupplyDemandParameters
    data_version: ValidatedDataVersion
    result: SimulationResult
    performance: PerformanceReport
    candidate_metrics: CandidateMetrics
    membership_violation_count: int


class DemandFoldEvaluator:
    """Calculate causal features, plans, simulation, and metrics for one fold segment."""

    def __init__(self, simulation_config: DemandSimulationConfig | None = None) -> None:
        self.simulation_config = simulation_config or DemandSimulationConfig()

    def evaluate(
        self,
        *,
        bars: Iterable[Bar],
        membership_history: MembershipHistory,
        window: WalkForwardWindow,
        period: ReplayPeriod,
        parameters: SupplyDemandParameters,
        data_version: ValidatedDataVersion,
        anomaly_count: int = 0,
    ) -> DemandFoldEvaluation:
        if parameters.trend_filter != "none":
            raise NotImplementedError("EMA trend filters require Feature 004 registration")
        start, end = _bounds(window, period)
        all_bars = tuple(
            sorted(
                (item for item in bars if window.warmup_start <= item.date <= end),
                key=lambda item: (item.ticker, item.date),
            )
        )
        execution_bars = tuple(item for item in all_bars if start <= item.date <= end)
        if not execution_bars:
            raise ValueError("Fold segment contains no execution bars")

        feature_config = SupplyDemandConfig(
            atr_period=parameters.atr_period,
            volume_period=parameters.volume_period,
            base_atr_ratio=parameters.base_atr_ratio,
            previous_range_ratio=parameters.previous_range_ratio,
            departure_range_ratio=parameters.departure_range_ratio,
            departure_body_ratio=parameters.departure_body_ratio,
            volume_multiplier=parameters.volume_multiplier,
            structure_lookback=parameters.structure_lookback,
            require_structure_break=False,
            entry_expiry_bars=parameters.entry_expiry_days,
            max_retests=parameters.maximum_retests + 1,
        )
        plans = []
        bars_by_ticker: dict[str, list[Bar]] = defaultdict(list)
        for item in all_bars:
            bars_by_ticker[item.ticker].append(item)
        for ticker_bars in bars_by_ticker.values():
            features = compute_supply_demand_features(ticker_bars, feature_config)
            scoped_features = (row for row in features if start <= row.date <= end)
            plans.extend(build_demand_trade_plans(scoped_features, ticker_bars, parameters))
        membership = {
            session: membership_history.as_of(session).symbols
            for session in sorted({item.date for item in execution_bars})
        }
        result = DemandTradeSimulator(self.simulation_config).run(
            bars=execution_bars,
            plans=plans,
            membership=membership,
        )
        performance = calculate_performance(
            result,
            initial_equity=self.simulation_config.initial_cash,
        )
        violations = sum(
            trade.ticker not in membership.get(trade.entry_date, frozenset())
            for trade in result.trades
        )
        entries = Counter(trade.entry_date.year for trade in result.trades)
        for year in range(start.year, end.year + 1):
            entries.setdefault(year, 0)
        candidate_metrics = CandidateMetrics(
            cagr=performance.cagr,
            average_yearly_return=performance.average_calendar_year_return,
            maximum_drawdown=performance.maximum_drawdown,
            sharpe=performance.sharpe or 0.0,
            entries_by_year=dict(entries),
            max_position_weight=self.simulation_config.maximum_position_weight,
            anomaly_count=anomaly_count,
            membership_violation_count=violations,
        )
        return DemandFoldEvaluation(
            window_id=window.window_id,
            period=period,
            parameters=parameters,
            data_version=data_version,
            result=result,
            performance=performance,
            candidate_metrics=candidate_metrics,
            membership_violation_count=violations,
        )


def _bounds(window: WalkForwardWindow, period: ReplayPeriod):
    if period is ReplayPeriod.TRAINING:
        return window.train_start, window.train_end
    if period is ReplayPeriod.FORWARD:
        return window.forward_start, window.forward_end
    raise ValueError(f"Unsupported replay period: {period}")
