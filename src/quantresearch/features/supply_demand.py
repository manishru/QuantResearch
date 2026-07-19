"""Daily three-candle supply and demand imbalance features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.features.volatility import compute_true_ranges, compute_wilder_average
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class SupplyDemandConfig:
    """Objective Drop-Base-Rally and Rally-Base-Drop parameters."""

    atr_period: int = 14
    volume_period: int = 20
    base_atr_ratio: float = 0.50
    previous_range_ratio: float = 2.0
    departure_range_ratio: float = 3.0
    departure_body_ratio: float = 0.60
    volume_multiplier: float = 1.25
    structure_lookback: int = 20
    require_structure_break: bool = False
    entry_expiry_bars: int = 60
    max_retests: int = 1
    max_active_zones_per_kind: int = 20

    def __post_init__(self) -> None:
        for name, value, minimum in (
            ("atr_period", self.atr_period, 2),
            ("volume_period", self.volume_period, 1),
            ("structure_lookback", self.structure_lookback, 1),
            ("entry_expiry_bars", self.entry_expiry_bars, 1),
            ("max_active_zones_per_kind", self.max_active_zones_per_kind, 1),
        ):
            if not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        for name, value in (
            ("base_atr_ratio", self.base_atr_ratio),
            ("previous_range_ratio", self.previous_range_ratio),
            ("departure_range_ratio", self.departure_range_ratio),
            ("departure_body_ratio", self.departure_body_ratio),
            ("volume_multiplier", self.volume_multiplier),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.departure_body_ratio > 1:
            raise ValueError("departure_body_ratio cannot exceed one")
        if not isinstance(self.max_retests, int) or self.max_retests < 0:
            raise ValueError("max_retests must be a nonnegative integer")


@dataclass(slots=True)
class _Zone:
    kind: str
    lower: float
    upper: float
    base_date: date
    confirmation_index: int
    retest_count: int = 0


def supply_demand_manifest(
    config: SupplyDemandConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    """Record formula parameters and causal availability."""

    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "supply_demand_zones",
            "definition_version": "daily_three_candle_v1",
            **{
                name: getattr(config, name)
                for name in (
                    "atr_period",
                    "volume_period",
                    "base_atr_ratio",
                    "previous_range_ratio",
                    "departure_range_ratio",
                    "departure_body_ratio",
                    "volume_multiplier",
                    "structure_lookback",
                    "require_structure_break",
                    "entry_expiry_bars",
                    "max_retests",
                    "max_active_zones_per_kind",
                )
            },
            "demand": "bearish previous, small base, bullish departure",
            "supply": "bullish previous, small base, bearish departure",
            "volume_average": "prior N completed bars excluding departure",
            "demand_bounds": "base low to max(base open, base close)",
            "supply_bounds": "min(base open, base close) to base high",
            "availability": "departure_close",
            "revisit": "first later bar whose high-low range intersects zone",
            "invalidation": "completed close beyond distal boundary",
            "selection": "none",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_supply_demand_features(
    bars: Iterable[Bar], config: SupplyDemandConfig | None = None
) -> list[FeatureRow]:
    """Detect setups and track zones without retroactive availability."""

    config = config or SupplyDemandConfig()
    groups: dict[str, list[Bar]] = defaultdict(list)
    seen: set[tuple[str, date]] = set()
    for item in sorted(bars, key=lambda value: (value.ticker, value.date)):
        key = (item.ticker, item.date)
        if key in seen:
            raise ValueError("duplicate ticker-date bars are not allowed")
        seen.add(key)
        groups[item.ticker].append(item)

    output: list[FeatureRow] = []
    for ticker, ticker_bars in sorted(groups.items()):
        output.extend(_compute_ticker(ticker, ticker_bars, config))
    return output


def _compute_ticker(ticker: str, bars: list[Bar], config: SupplyDemandConfig) -> list[FeatureRow]:
    true_ranges = compute_true_ranges(bars)
    atrs = compute_wilder_average(true_ranges, config.atr_period)
    active: dict[str, list[_Zone]] = {"demand": [], "supply": []}
    output: list[FeatureRow] = []

    for index, current in enumerate(bars):
        revisited_zone: dict[str, _Zone | None] = {"demand": None, "supply": None}
        events = {
            kind: {"created": False, "revisited": False, "invalidated": False, "expired": False}
            for kind in ("demand", "supply")
        }
        for kind in ("demand", "supply"):
            kept: list[_Zone] = []
            for zone in active[kind]:
                age = index - zone.confirmation_index
                if age > config.entry_expiry_bars:
                    events[kind]["expired"] = True
                elif (kind == "demand" and current.close < zone.lower) or (
                    kind == "supply" and current.close > zone.upper
                ):
                    events[kind]["invalidated"] = True
                else:
                    kept.append(zone)
            active[kind] = kept

        measurements = _setup_measurements(bars, atrs, index, config)
        created_kind = measurements.get("setup_kind") if measurements else None
        if created_kind:
            base = bars[index - 1]
            if created_kind == "demand":
                lower, upper = base.low, max(base.open, base.close)
            else:
                lower, upper = min(base.open, base.close), base.high
            if lower < upper:
                active[created_kind].append(
                    _Zone(created_kind, lower, upper, base.date, index)
                )
                active[created_kind] = active[created_kind][
                    -config.max_active_zones_per_kind :
                ]
                events[created_kind]["created"] = True

        for kind in ("demand", "supply"):
            for zone in active[kind]:
                if zone.confirmation_index < index and _intersects(current, zone):
                    zone.retest_count += 1
                    events[kind]["revisited"] = True
                    if (
                        revisited_zone[kind] is None
                        or zone.base_date > revisited_zone[kind].base_date
                    ):
                        revisited_zone[kind] = zone

        values: dict[str, float | bool | str | None] = {
            key: value for key, value in (measurements or {}).items() if key != "setup_kind"
        }
        values["atr"] = atrs[index]
        for kind in ("demand", "supply"):
            nearest = revisited_zone[kind] or _nearest(active[kind], current.close)
            values[f"{kind}_created"] = events[kind]["created"]
            values[f"{kind}_revisited"] = events[kind]["revisited"]
            values[f"{kind}_invalidated"] = events[kind]["invalidated"]
            values[f"{kind}_expired"] = events[kind]["expired"]
            values[f"{kind}_lower"] = nearest.lower if nearest else None
            values[f"{kind}_upper"] = nearest.upper if nearest else None
            values[f"{kind}_base_date"] = nearest.base_date.isoformat() if nearest else None
            values[f"{kind}_retest_count"] = float(nearest.retest_count) if nearest else None
            values[f"in_{kind}_zone"] = (
                nearest.lower <= current.close <= nearest.upper if nearest else False
            )
            values[f"active_{kind}_zone_count"] = float(len(active[kind]))
        output.append(FeatureRow(ticker, current.date, current.date, values))
    return output


def _setup_measurements(
    bars: list[Bar],
    atrs: list[float | None],
    index: int,
    config: SupplyDemandConfig,
) -> dict[str, float | bool | str | None]:
    empty: dict[str, float | bool | str | None] = {
        "previous_base_range_ratio": None,
        "departure_base_range_ratio": None,
        "base_atr_actual_ratio": None,
        "departure_body_ratio": None,
        "departure_volume_ratio": None,
        "structure_break": False,
    }
    if index < 2:
        return empty
    previous, base, departure = bars[index - 2], bars[index - 1], bars[index]
    base_atr = atrs[index - 1]
    base_range = base.high - base.low
    departure_range = departure.high - departure.low
    if (
        base_atr is None
        or base_range <= 0
        or departure_range <= 0
        or index < config.volume_period
    ):
        return empty
    prior_volumes = [item.volume for item in bars[index - config.volume_period : index]]
    average_volume = sum(prior_volumes) / config.volume_period
    previous_ratio = (previous.high - previous.low) / base_range
    departure_ratio = departure_range / base_range
    body_ratio = abs(departure.close - departure.open) / departure_range
    volume_ratio = departure.volume / average_volume if average_volume > 0 else None
    structure_start = max(0, index - 1 - config.structure_lookback)
    structure_bars = bars[structure_start : index - 1]
    demand_break = bool(structure_bars) and departure.close > max(
        item.high for item in structure_bars
    )
    supply_break = bool(structure_bars) and departure.close < min(
        item.low for item in structure_bars
    )
    common = (
        base_range <= config.base_atr_ratio * base_atr
        and previous_ratio >= config.previous_range_ratio
        and departure_ratio >= config.departure_range_ratio
        and body_ratio >= config.departure_body_ratio
        and volume_ratio is not None
        and volume_ratio >= config.volume_multiplier
    )
    demand = common and previous.close < previous.open and departure.close > departure.open
    supply = common and previous.close > previous.open and departure.close < departure.open
    if config.require_structure_break:
        demand = demand and demand_break
        supply = supply and supply_break
    return {
        "setup_kind": "demand" if demand else "supply" if supply else None,
        "previous_base_range_ratio": previous_ratio,
        "departure_base_range_ratio": departure_ratio,
        "base_atr_actual_ratio": base_range / base_atr,
        "departure_body_ratio": body_ratio,
        "departure_volume_ratio": volume_ratio,
        "structure_break": demand_break if demand else supply_break if supply else False,
    }


def _intersects(bar: Bar, zone: _Zone) -> bool:
    return bar.high >= zone.lower and bar.low <= zone.upper


def _nearest(zones: list[_Zone], close: float) -> _Zone | None:
    return min(
        zones,
        key=lambda zone: (_distance(close, zone), -zone.base_date.toordinal()),
        default=None,
    )


def _distance(close: float, zone: _Zone) -> float:
    if close < zone.lower:
        return zone.lower - close
    if close > zone.upper:
        return close - zone.upper
    return 0.0
