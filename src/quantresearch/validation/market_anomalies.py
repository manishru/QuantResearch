"""Conservative quarantine checks for economic price continuity."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from quantresearch.simulation.models import Bar


@dataclass(frozen=True, slots=True)
class MarketAnomaly:
    ticker: str
    date: date
    prior_date: date
    ratio: float
    reason_code: str
    severity: str = "critical"
    eligible_for_research: bool = False


def detect_price_discontinuities(
    bars: Iterable[Bar], *, maximum_ratio: float = 5.0
) -> tuple[MarketAnomaly, ...]:
    """Flag extreme close-to-close ratios for identity/corporate-action review.

    This gate does not assert that every large move is bad. It prevents unexplained
    discontinuities from entering research until supporting identity and adjustment
    evidence is reviewed.
    """
    if maximum_ratio <= 1:
        raise ValueError("maximum_ratio must be greater than one")
    groups: dict[str, list[Bar]] = defaultdict(list)
    for item in bars:
        groups[item.ticker].append(item)
    findings: list[MarketAnomaly] = []
    for ticker, values in sorted(groups.items()):
        values.sort(key=lambda item: item.date)
        for previous, current in zip(values, values[1:], strict=False):
            ratio = max(current.close / previous.close, previous.close / current.close)
            if ratio > maximum_ratio:
                findings.append(
                    MarketAnomaly(
                        ticker=ticker,
                        date=current.date,
                        prior_date=previous.date,
                        ratio=ratio,
                        reason_code="unexplained_price_discontinuity",
                    )
                )
    return tuple(findings)
