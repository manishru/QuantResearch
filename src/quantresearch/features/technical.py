"""Transparent weekly momentum, breakout, ATR, and Supertrend features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureRow
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class WeeklyFeatureConfig:
    return_windows: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10, 13, 26, 39, 52)
    breakout_windows: tuple[int, ...] = tuple(range(5, 61))
    atr_windows: tuple[int, ...] = (5, 7, 10, 13, 14, 20)
    supertrends: tuple[tuple[int, float], ...] = ((5, 2.25), (13, 2.75))

    def __post_init__(self) -> None:
        windows = self.return_windows + self.breakout_windows + self.atr_windows
        if any(not isinstance(window, int) or window < 1 for window in windows):
            raise ValueError("Feature windows must be positive integers")
        if any(period < 1 or multiplier <= 0 for period, multiplier in self.supertrends):
            raise ValueError("Supertrend period and multiplier must be positive")


def compute_weekly_features(
    weekly_bars: Iterable[Bar], config: WeeklyFeatureConfig | None = None
) -> list[FeatureRow]:
    config = config or WeeklyFeatureConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(weekly_bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date weekly bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    rows: list[FeatureRow] = []
    for ticker, bars in sorted(groups.items()):
        true_ranges = _true_ranges(bars)
        atrs = {window: _rolling_mean(true_ranges, window) for window in config.atr_windows}
        supertrends = {
            (period, multiplier): _supertrend(bars, _rolling_mean(true_ranges, period), multiplier)
            for period, multiplier in config.supertrends
        }
        for index, item in enumerate(bars):
            values: dict[str, float | bool | None] = {}
            for window in config.return_windows:
                values[f"return_{window}w"] = (
                    item.close / bars[index - window].close - 1 if index >= window else None
                )
            for window in config.breakout_windows:
                prior = bars[max(0, index - window) : index]
                trigger = (
                    max((bar.high for bar in prior), default=None) if len(prior) == window else None
                )
                values[f"breakout_high_{window}w"] = trigger
                values[f"breakout_close_{window}w"] = (
                    item.close > trigger if trigger is not None else False
                )
            for window in config.atr_windows:
                values[f"atr_{window}w"] = atrs[window][index]
            for period, multiplier in config.supertrends:
                label = _number_label(multiplier)
                line, green = supertrends[(period, multiplier)][index]
                values[f"supertrend_{period}_{label}"] = line
                values[f"supertrend_green_{period}_{label}"] = green
            rows.append(FeatureRow(ticker, item.date, item.date, values))
    return rows


def _true_ranges(bars: list[Bar]) -> list[float]:
    result: list[float] = []
    for index, item in enumerate(bars):
        previous_close = bars[index - 1].close if index else item.close
        result.append(
            max(
                item.high - item.low,
                abs(item.high - previous_close),
                abs(item.low - previous_close),
            )
        )
    return result


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        output.append(running / window if index + 1 >= window else None)
    return output


def _supertrend(
    bars: list[Bar], atr: list[float | None], multiplier: float
) -> list[tuple[float | None, bool]]:
    output: list[tuple[float | None, bool]] = []
    final_upper: float | None = None
    final_lower: float | None = None
    previous_line: float | None = None
    previous_upper: float | None = None

    for index, item in enumerate(bars):
        current_atr = atr[index]
        if current_atr is None:
            output.append((None, False))
            continue
        midpoint = (item.high + item.low) / 2
        basic_upper = midpoint + multiplier * current_atr
        basic_lower = midpoint - multiplier * current_atr
        previous_close = bars[index - 1].close if index else item.close
        final_upper = (
            basic_upper
            if final_upper is None or basic_upper < final_upper or previous_close > final_upper
            else final_upper
        )
        final_lower = (
            basic_lower
            if final_lower is None or basic_lower > final_lower or previous_close < final_lower
            else final_lower
        )
        if previous_line is None or previous_upper is None or previous_line == previous_upper:
            line = final_upper if item.close <= final_upper else final_lower
        else:
            line = final_lower if item.close >= final_lower else final_upper
        output.append((line, item.close > line))
        previous_line = line
        previous_upper = final_upper
    return output


def _number_label(value: float) -> str:
    return str(value).rstrip("0").rstrip(".").replace(".", "p")
