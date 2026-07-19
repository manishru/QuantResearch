"""Point-in-time candidate ranking and fold-scoped reference replay."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from quantresearch.domain.membership import MembershipHistory
from quantresearch.research.models import StrategyDefinition
from quantresearch.simulation.models import Bar, Signal, SignalAction, SimulationResult
from quantresearch.simulation.reference import ReferenceSimulator
from quantresearch.walkforward.models import WalkForwardWindow


class ReplayPeriod(StrEnum):
    TRAINING = "training"
    FORWARD = "forward"


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    """A causal candidate score available at one completed decision session."""

    decision_date: date
    ticker: str
    score: float
    quantity: float
    trigger_price: float | None = None

    def __post_init__(self) -> None:
        if not self.ticker.strip() or self.ticker != self.ticker.strip().upper():
            raise ValueError("Candidate ticker must be normalized uppercase")
        if not math.isfinite(self.score):
            raise ValueError("Candidate score must be finite")
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("Candidate quantity must be positive and finite")
        if self.trigger_price is not None and (
            not math.isfinite(self.trigger_price) or self.trigger_price <= 0
        ):
            raise ValueError("Candidate trigger_price must be positive and finite")


def select_point_in_time_entries(
    candidates: Iterable[CandidateEntry],
    membership_history: MembershipHistory,
    *,
    top_n: int,
) -> tuple[Signal, ...]:
    """Filter by effective membership before deterministically ranking each day."""
    if top_n < 1:
        raise ValueError("top_n must be positive")
    grouped: dict[date, list[CandidateEntry]] = {}
    seen: set[tuple[date, str]] = set()
    for candidate in candidates:
        key = (candidate.decision_date, candidate.ticker)
        if key in seen:
            raise ValueError("Duplicate candidate ticker-date is not allowed")
        seen.add(key)
        grouped.setdefault(candidate.decision_date, []).append(candidate)

    signals: list[Signal] = []
    for decision_date, daily_candidates in sorted(grouped.items()):
        members = membership_history.as_of(decision_date).symbols
        eligible = (item for item in daily_candidates if item.ticker in members)
        ranked = sorted(eligible, key=lambda item: (-item.score, item.ticker))[:top_n]
        signals.extend(
            Signal(
                decision_date=item.decision_date,
                ticker=item.ticker,
                action=SignalAction.ENTRY,
                quantity=item.quantity,
                trigger_price=item.trigger_price,
            )
            for item in ranked
        )
    return tuple(signals)


def replay_ranked_candidates(
    *,
    strategy: StrategyDefinition,
    window: WalkForwardWindow,
    period: ReplayPeriod,
    bars: Iterable[Bar],
    candidates: Iterable[CandidateEntry],
    exit_signals: Iterable[Signal],
    membership_history: MembershipHistory,
    top_n: int,
    simulator: ReferenceSimulator | None = None,
) -> SimulationResult:
    """Replay one training or forward segment with two membership gates."""
    strategy_index = strategy.universe.get("index_id")
    if strategy_index != membership_history.index_id:
        raise ValueError("Strategy and membership history index_id must match")
    if strategy.universe.get("membership") != "point_in_time":
        raise ValueError("Strategy must declare point_in_time membership")

    start, end = _period_bounds(window, period)
    scoped_bars = tuple(item for item in bars if start <= item.date <= end)
    scoped_candidates = tuple(
        item for item in candidates if start <= item.decision_date <= end
    )
    scoped_exits = tuple(
        item for item in exit_signals if start <= item.decision_date <= end
    )
    if any(item.action is not SignalAction.EXIT for item in scoped_exits):
        raise ValueError("exit_signals may contain only exit actions")

    entries = select_point_in_time_entries(
        scoped_candidates,
        membership_history,
        top_n=top_n,
    )
    membership = {
        session: membership_history.as_of(session).symbols
        for session in sorted({item.date for item in scoped_bars})
    }
    engine = simulator or ReferenceSimulator()
    return engine.run(
        scoped_bars,
        (*entries, *scoped_exits),
        membership=membership,
    )


def _period_bounds(window: WalkForwardWindow, period: ReplayPeriod) -> tuple[date, date]:
    if period is ReplayPeriod.TRAINING:
        return window.train_start, window.train_end
    if period is ReplayPeriod.FORWARD:
        return window.forward_start, window.forward_end
    raise ValueError(f"Unsupported replay period: {period}")

