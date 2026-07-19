"""Pure helpers for daily basket news/sentiment aggregation."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def aggregate_basket_observations(
    observations: Iterable[tuple[str, str, float, int]], basket: set[str],
) -> dict[str, tuple[float, int]]:
    """Return day -> (count-weighted sentiment, article count) for a basket."""
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for ticker, observed, sentiment, count in observations:
        if ticker not in basket or count <= 0:
            continue
        totals[observed][0] += sentiment * count
        totals[observed][1] += count
    return {day: (value / count, int(count)) for day, (value, count) in totals.items() if count}
