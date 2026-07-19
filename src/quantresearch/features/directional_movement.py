"""Wilder directional movement, DI, DX, and ADX feature grids."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.features.volatility import compute_true_ranges
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class DirectionalMovementConfig:
    periods: tuple[int, ...] = (7, 10, 14, 20)

    def __post_init__(self) -> None:
        if not self.periods or any(
            not isinstance(period, int) or period < 2 for period in self.periods
        ):
            raise ValueError("periods must contain integers >= 2")
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("periods must be unique")


def directional_movement_manifest(
    config: DirectionalMovementConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "directional_movement",
            "periods": list(config.periods),
            "plus_dm": "up move when up > down and up > 0; otherwise zero",
            "minus_dm": "down move when down > up and down > 0; otherwise zero",
            "di": "100 * Wilder-smoothed DM / Wilder-smoothed true range",
            "dx": "100 * abs(DI+ - DI-) / (DI+ + DI-)",
            "adx_seed": "mean of first N available DX values",
            "smoothing": "wilder",
            "availability": "completed_bar_close",
            "selection": "none",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_directional_movement_features(
    bars: Iterable[Bar], config: DirectionalMovementConfig | None = None
) -> list[FeatureRow]:
    config = config or DirectionalMovementConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    output: list[FeatureRow] = []
    for ticker, ticker_bars in sorted(groups.items()):
        true_ranges = compute_true_ranges(ticker_bars)
        plus_dm, minus_dm = _directional_moves(ticker_bars)
        grid = {
            period: _compute_period(true_ranges, plus_dm, minus_dm, period)
            for period in config.periods
        }
        for index, item in enumerate(ticker_bars):
            values: dict[str, float | bool | str | None] = {
                "plus_dm": plus_dm[index],
                "minus_dm": minus_dm[index],
            }
            for period in config.periods:
                plus_di, minus_di, dx, adx = grid[period]
                values[f"plus_di_{period}"] = plus_di[index]
                values[f"minus_di_{period}"] = minus_di[index]
                values[f"dx_{period}"] = dx[index]
                values[f"adx_{period}"] = adx[index]
                values[f"di_bullish_{period}"] = (
                    plus_di[index] > minus_di[index]
                    if plus_di[index] is not None and minus_di[index] is not None
                    else False
                )
            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output


def _directional_moves(bars: list[Bar]) -> tuple[list[float], list[float]]:
    plus = [0.0]
    minus = [0.0]
    for previous, current in zip(bars, bars[1:], strict=False):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus.append(down_move if down_move > up_move and down_move > 0 else 0.0)
    return plus, minus


def _compute_period(
    true_ranges: list[float], plus_dm: list[float], minus_dm: list[float], period: int
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
]:
    smoothed_tr = _wilder_sums(true_ranges, period)
    smoothed_plus = _wilder_sums(plus_dm, period)
    smoothed_minus = _wilder_sums(minus_dm, period)
    plus_di: list[float | None] = []
    minus_di: list[float | None] = []
    dx: list[float | None] = []
    for tr, positive, negative in zip(smoothed_tr, smoothed_plus, smoothed_minus, strict=True):
        if tr is None or tr <= 0 or positive is None or negative is None:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        current_plus = 100 * positive / tr
        current_minus = 100 * negative / tr
        denominator = current_plus + current_minus
        plus_di.append(current_plus)
        minus_di.append(current_minus)
        dx.append(100 * abs(current_plus - current_minus) / denominator if denominator > 0 else 0.0)
    return plus_di, minus_di, dx, _adx(dx, period)


def _wilder_sums(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period])
    output[period - 1] = current
    for index in range(period, len(values)):
        current = current - current / period + values[index]
        output[index] = current
    return output


def _adx(dx: list[float | None], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(dx)
    seed_index = 2 * period - 2
    if seed_index >= len(dx):
        return output
    seed_values = dx[period - 1 : seed_index + 1]
    if any(value is None for value in seed_values):
        return output
    current = sum(float(value) for value in seed_values) / period
    output[seed_index] = current
    for index in range(seed_index + 1, len(dx)):
        if dx[index] is None:
            continue
        current = (current * (period - 1) + float(dx[index])) / period
        output[index] = current
    return output
