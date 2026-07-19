"""Pure accounting helpers for the research-only short-sale proxy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class ShortBar:
    observed: date
    open_price: float
    close_price: float


@dataclass(frozen=True)
class ShortExit:
    observed: date
    price: float
    reason: str


def select_short_exit(
    entry_price: float, bars: Iterable[ShortBar], maturity_close_date: date, stop_fraction: float,
) -> ShortExit | None:
    """Cover on the open after a close-confirmed stop or maturity close."""
    ordered = tuple(sorted(bars, key=lambda bar: bar.observed))
    for index, bar in enumerate(ordered):
        if bar.observed > maturity_close_date:
            return ShortExit(bar.observed, bar.open_price, "time_exit_next_open")
        if bar.close_price >= entry_price * (1 + stop_fraction):
            if index + 1 < len(ordered):
                next_bar = ordered[index + 1]
                return ShortExit(next_bar.observed, next_bar.open_price, "stop_close_next_open")
            return None
    return None


def short_net_return(entry_price: float, cover_price: float, holding_days: int, borrow_rate: float, cost: float) -> float:
    """Return after an annual borrow fee and one transaction cost on each side."""
    if entry_price <= 0 or cover_price <= 0:
        raise ValueError("entry and cover prices must be positive")
    if holding_days < 0:
        raise ValueError("holding days cannot be negative")
    return (entry_price / cover_price - 1) - borrow_rate * holding_days / 365.2425 - 2 * cost


def apply_asymmetric_pnl_haircut(raw_pnl: float, gain_keep: float = .90, loss_multiplier: float = 1.10) -> float:
    """Apply conservative post-exit slippage haircuts to realised P&L."""
    if not 0 <= gain_keep <= 1 or loss_multiplier < 1:
        raise ValueError("gain_keep must be in [0,1] and loss_multiplier at least one")
    return raw_pnl * (gain_keep if raw_pnl >= 0 else loss_multiplier)


def select_short_target_exit(
    entry_price: float, bars: Iterable[ShortBar], stop_fraction: float, reward_multiple: float,
) -> ShortExit | None:
    """Cover next open after a completed-close short stop or profit target."""
    if stop_fraction <= 0 or reward_multiple <= 0:
        raise ValueError("stop fraction and reward multiple must be positive")
    ordered = tuple(sorted(bars, key=lambda bar: bar.observed))
    stop_price = entry_price * (1 + stop_fraction)
    target_price = entry_price * (1 - stop_fraction * reward_multiple)
    for index, bar in enumerate(ordered):
        if bar.close_price >= stop_price or bar.close_price <= target_price:
            if index + 1 >= len(ordered):
                return None
            reason = "stop_close_next_open" if bar.close_price >= stop_price else "target_close_next_open"
            next_bar = ordered[index + 1]
            return ShortExit(next_bar.observed, next_bar.open_price, reason)
    return None
