"""Point-in-time volume-price money-flow features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from quantresearch.features.models import FeatureManifest, FeatureRow
from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class MoneyFlowConfig:
    """Windows used by Chaikin Money Flow and Money Flow Index."""

    cmf_windows: tuple[int, ...] = (20,)
    mfi_windows: tuple[int, ...] = (14,)

    def __post_init__(self) -> None:
        for name, windows in (
            ("cmf_windows", self.cmf_windows),
            ("mfi_windows", self.mfi_windows),
        ):
            if not windows or any(not isinstance(window, int) or window < 1 for window in windows):
                raise ValueError(f"{name} must contain positive integers")
            if len(set(windows)) != len(windows):
                raise ValueError(f"{name} must contain unique windows")


def money_flow_manifest(
    config: MoneyFlowConfig,
    *,
    frequency: str,
    source_data_version: str,
    code_version: str,
    price_basis: str = "split_dividend_adjusted",
) -> FeatureManifest:
    """Describe the exact formulas and availability of this feature family."""

    return FeatureManifest(
        frequency=frequency,
        price_basis=price_basis,
        definitions={
            "family": "money_flow",
            "cmf_windows": list(config.cmf_windows),
            "mfi_windows": list(config.mfi_windows),
            "obv": "cumulative signed volume; first observation is zero",
            "money_flow_multiplier": "((close-low)-(high-close))/(high-low); zero when high=low",
            "adl": "cumulative money_flow_multiplier * volume",
            "cmf": "rolling sum(money_flow_volume) / rolling sum(volume)",
            "mfi": "100 - 100/(1 + positive_raw_flow/negative_raw_flow)",
            "rolling_windows": "current-inclusive completed bars",
            "availability": "completed_bar_close",
        },
        source_data_version=source_data_version,
        code_version=code_version,
    )


def compute_money_flow_features(
    bars: Iterable[Bar], config: MoneyFlowConfig | None = None
) -> list[FeatureRow]:
    """Calculate causal OBV, ADL, CMF, and MFI for each ticker."""

    config = config or MoneyFlowConfig()
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
        volumes = [item.volume for item in ticker_bars]
        typical_prices = [(item.high + item.low + item.close) / 3 for item in ticker_bars]
        raw_flows = [
            price * item.volume for price, item in zip(typical_prices, ticker_bars, strict=True)
        ]

        obv_values: list[float] = []
        multipliers: list[float] = []
        money_flow_volumes: list[float] = []
        adl_values: list[float] = []
        positive_flows: list[float] = []
        negative_flows: list[float] = []

        obv = 0.0
        adl = 0.0
        for index, item in enumerate(ticker_bars):
            if index:
                if item.close > ticker_bars[index - 1].close:
                    obv += item.volume
                elif item.close < ticker_bars[index - 1].close:
                    obv -= item.volume
            obv_values.append(obv)

            price_range = item.high - item.low
            multiplier = (
                ((item.close - item.low) - (item.high - item.close)) / price_range
                if price_range != 0
                else 0.0
            )
            flow_volume = multiplier * item.volume
            adl += flow_volume
            multipliers.append(multiplier)
            money_flow_volumes.append(flow_volume)
            adl_values.append(adl)

            positive = 0.0
            negative = 0.0
            if index and typical_prices[index] > typical_prices[index - 1]:
                positive = raw_flows[index]
            elif index and typical_prices[index] < typical_prices[index - 1]:
                negative = raw_flows[index]
            positive_flows.append(positive)
            negative_flows.append(negative)

        for index, item in enumerate(ticker_bars):
            values: dict[str, float | bool | None] = {
                "obv": obv_values[index],
                "money_flow_multiplier": multipliers[index],
                "money_flow_volume": money_flow_volumes[index],
                "adl": adl_values[index],
            }
            for window in config.cmf_windows:
                if index + 1 < window:
                    cmf = None
                else:
                    start = index - window + 1
                    volume_sum = sum(volumes[start : index + 1])
                    cmf = (
                        sum(money_flow_volumes[start : index + 1]) / volume_sum
                        if volume_sum > 0
                        else None
                    )
                values[f"cmf_{window}"] = cmf

            for window in config.mfi_windows:
                if index + 1 < window:
                    mfi = None
                else:
                    start = index - window + 1
                    positive_sum = sum(positive_flows[start : index + 1])
                    negative_sum = sum(negative_flows[start : index + 1])
                    if positive_sum == 0 and negative_sum == 0:
                        mfi = 50.0
                    elif negative_sum == 0:
                        mfi = 100.0
                    elif positive_sum == 0:
                        mfi = 0.0
                    else:
                        ratio = positive_sum / negative_sum
                        mfi = 100 - 100 / (1 + ratio)
                values[f"mfi_{window}"] = mfi

            output.append(FeatureRow(ticker, item.date, item.date, values))
    return output
