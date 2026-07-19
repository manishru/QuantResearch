"""Deterministic daily-bar bracket resolution policies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from quantresearch.simulation.models import Bar


class BracketExitReason(StrEnum):
    OPEN = "open"
    STOP = "stop"
    TARGET = "target"


@dataclass(frozen=True, slots=True)
class BracketResolution:
    reason: BracketExitReason
    fill_price: float | None
    ambiguous_same_bar: bool = False


def resolve_long_bracket(
    bar: Bar,
    *,
    stop_price: float,
    target_price: float,
) -> BracketResolution:
    """Resolve a long stop/target on one daily bar using a stop-first policy.

    Opening gaps execute at the observed open. If both levels are reached after
    the open and intraday ordering is unknowable, the stop is assumed first.
    """
    if not all(math.isfinite(value) and value > 0 for value in (stop_price, target_price)):
        raise ValueError("stop_price and target_price must be positive and finite")
    if stop_price >= target_price:
        raise ValueError("A long bracket requires stop_price below target_price")

    if bar.open <= stop_price:
        return BracketResolution(BracketExitReason.STOP, bar.open)
    if bar.open >= target_price:
        return BracketResolution(BracketExitReason.TARGET, bar.open)

    stop_reached = bar.low <= stop_price
    target_reached = bar.high >= target_price
    if stop_reached and target_reached:
        return BracketResolution(BracketExitReason.STOP, stop_price, True)
    if stop_reached:
        return BracketResolution(BracketExitReason.STOP, stop_price)
    if target_reached:
        return BracketResolution(BracketExitReason.TARGET, target_price)
    return BracketResolution(BracketExitReason.OPEN, None)

