"""Pure timing and exit rules for monthly momentum lots."""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class LotBar:
    date: date
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("lot bar prices must be positive and finite")
        if self.high + 1e-10 < max(self.open, self.low, self.close):
            raise ValueError("lot bar high violates OHLC")
        if self.low - 1e-10 > min(self.open, self.high, self.close):
            raise ValueError("lot bar low violates OHLC")


@dataclass(frozen=True, slots=True)
class LotExit:
    date: date
    price: float
    reason: str


def scheduled_calendar_date(year: int, month: int, nominal_day: int) -> date:
    """Clamp a nominal day to month-end so every experiment deploys monthly."""
    if not 1 <= nominal_day <= 31:
        raise ValueError("nominal_day must be between 1 and 31")
    return date(year, month, min(nominal_day, calendar.monthrange(year, month)[1]))


def select_lot_exit(
    entry_date: date,
    entry_price: float,
    bars: tuple[LotBar, ...],
    *,
    stop_fraction: float,
    trailing_activation: float | None = None,
    trailing_initial_floor: float = 0.60,
    trailing_peak_step: float = 0.10,
    trailing_floor_step: float = 0.05,
    scheduled_maturity_date: date | None = None,
) -> LotExit:
    """Choose the first causal stop or declared monthly-cycle maturity exit."""
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise ValueError("entry_price must be positive and finite")
    if not 0 < stop_fraction < 1:
        raise ValueError("stop_fraction must be between zero and one")
    if trailing_activation is not None:
        if not 0 <= trailing_initial_floor < trailing_activation:
            raise ValueError("trailing floor must be below activation")
        if trailing_peak_step <= 0 or trailing_floor_step <= 0:
            raise ValueError("trailing steps must be positive")
    ordered = tuple(sorted(bars, key=lambda bar: bar.date))
    if len({bar.date for bar in ordered}) != len(ordered):
        raise ValueError("future bars contain duplicate dates")
    maturity_date = scheduled_maturity_date or entry_date + timedelta(days=365)
    if maturity_date <= entry_date:
        raise ValueError("scheduled_maturity_date must be after entry_date")
    stop = entry_price * (1 - stop_fraction)
    peak_close_return: float | None = None
    trailing_exit_next_open = False
    for bar in ordered:
        if bar.date <= entry_date:
            continue
        if bar.date >= maturity_date:
            return LotExit(bar.date, bar.open, "one_year")
        if bar.open <= stop:
            return LotExit(bar.date, bar.open, "stop_gap")
        if trailing_exit_next_open:
            return LotExit(bar.date, bar.open, "stepwise_profit_trailing")
        if bar.low <= stop:
            return LotExit(bar.date, stop, "stop_intraday")
        if trailing_activation is not None:
            close_return = bar.close / entry_price - 1
            peak_close_return = max(peak_close_return or close_return, close_return)
            if peak_close_return >= trailing_activation:
                completed_steps = math.floor(
                    (peak_close_return - trailing_activation + 1e-12)
                    / trailing_peak_step
                )
                protected_return = (
                    trailing_initial_floor + completed_steps * trailing_floor_step
                )
                trailing_exit_next_open = close_return <= protected_return
    raise LookupError("no completed stop or maturity exit is available")
