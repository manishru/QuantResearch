"""Versioned point-in-time Supertrend feature grid."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.features.volatility import (
    compute_true_ranges,
    compute_wilder_average,
)
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class SupertrendConfig:
    """Standard research grid plus immutable prior-research control pairs."""

    periods: tuple[int, ...] = (5, 7, 10, 13, 14, 20, 52)
    multipliers: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
    reference_pairs: tuple[tuple[int, float], ...] = (
        (5, 2.25),
        (13, 2.75),
        (7, 4.78),
        (52, 4.88),
    )

    def __post_init__(self) -> None:
        if not self.periods or any(
            not isinstance(period, int) or period < 1 for period in self.periods
        ):
            raise ValueError("periods must contain positive integers")
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("periods must be unique")
        if not self.multipliers or any(multiplier <= 0 for multiplier in self.multipliers):
            raise ValueError("multipliers must contain positive values")
        if len(set(self.multipliers)) != len(self.multipliers):
            raise ValueError("multipliers must be unique")
        if any(
            not isinstance(period, int) or period < 1 or multiplier <= 0
            for period, multiplier in self.reference_pairs
        ):
            raise ValueError("reference pairs must contain positive periods and multipliers")
        if len(set(self.reference_pairs)) != len(self.reference_pairs):
            raise ValueError("reference pairs must be unique")

    def pairs(self) -> tuple[tuple[int, float], ...]:
        """Return a deterministic, deduplicated union of grid and controls."""

        pairs = {
            (period, float(multiplier))
            for period in self.periods
            for multiplier in self.multipliers
        }
        pairs.update((period, float(multiplier)) for period, multiplier in self.reference_pairs)
        return tuple(sorted(pairs))


def supertrend_manifest(
    config: SupertrendConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    """Record the complete grid, formulas, controls, and availability."""

    pairs = config.pairs()
    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "supertrend",
            "periods": list(config.periods),
            "multipliers": list(config.multipliers),
            "reference_pairs": [list(pair) for pair in config.reference_pairs],
            "pairs": [list(pair) for pair in pairs],
            "pair_count": len(pairs),
            "atr_method": "wilder_rma",
            "midpoint": "(high + low) / 2",
            "basic_bands": "midpoint +/- multiplier * ATR",
            "final_bands": "standard prior-band and prior-close recursion",
            "direction": "green when Supertrend line is the final lower band",
            "availability": "completed_bar_close",
            "selection": "none; reference pairs are controls only",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_supertrend_features(
    bars: Iterable[Bar], config: SupertrendConfig | None = None
) -> list[FeatureRow]:
    """Calculate every declared pair independently for each ticker."""

    config = config or SupertrendConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, object]] = set()
    for item in sorted(bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    output: list[FeatureRow] = []
    pairs = config.pairs()
    for ticker, ticker_bars in sorted(groups.items()):
        true_ranges = compute_true_ranges(ticker_bars)
        atr_by_period = {
            period: compute_wilder_average(true_ranges, period)
            for period in sorted({period for period, _ in pairs})
        }
        results = {
            pair: _compute_pair(ticker_bars, atr_by_period[pair[0]], pair[1]) for pair in pairs
        }
        for index, item in enumerate(ticker_bars):
            values: dict[str, float | bool | None] = {}
            for pair in pairs:
                period, multiplier = pair
                label = _number_label(multiplier)
                line, upper, lower, green, flip = results[pair][index]
                values[f"supertrend_{period}_{label}"] = line
                values[f"supertrend_upper_{period}_{label}"] = upper
                values[f"supertrend_lower_{period}_{label}"] = lower
                values[f"supertrend_green_{period}_{label}"] = green
                values[f"supertrend_flip_{period}_{label}"] = flip
            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output


def _compute_pair(
    bars: list[Bar], atrs: list[float | None], multiplier: float
) -> list[tuple[float | None, float | None, float | None, bool, bool]]:
    output: list[tuple[float | None, float | None, float | None, bool, bool]] = []
    final_upper: float | None = None
    final_lower: float | None = None
    previous_line: float | None = None
    previous_green: bool | None = None

    for index, item in enumerate(bars):
        atr = atrs[index]
        if atr is None:
            output.append((None, None, None, False, False))
            continue

        midpoint = (item.high + item.low) / 2
        basic_upper = midpoint + multiplier * atr
        basic_lower = midpoint - multiplier * atr
        previous_close = bars[index - 1].close if index else item.close
        previous_final_upper = final_upper
        previous_final_lower = final_lower

        final_upper = (
            basic_upper
            if previous_final_upper is None
            or basic_upper < previous_final_upper
            or previous_close > previous_final_upper
            else previous_final_upper
        )
        final_lower = (
            basic_lower
            if previous_final_lower is None
            or basic_lower > previous_final_lower
            or previous_close < previous_final_lower
            else previous_final_lower
        )

        if previous_line is None or previous_final_upper is None:
            line = final_upper if item.close <= final_upper else final_lower
        elif previous_line == previous_final_upper:
            line = final_upper if item.close <= final_upper else final_lower
        else:
            line = final_lower if item.close >= final_lower else final_upper

        green = line == final_lower
        flip = previous_green is not None and green != previous_green
        output.append((line, final_upper, final_lower, green, flip))
        previous_line = line
        previous_green = green

    return output


def _number_label(value: float) -> str:
    return format(value, "g").replace(".", "p")
