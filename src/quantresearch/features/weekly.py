"""Daily-to-weekly OHLCV aggregation using ISO calendar weeks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from quantresearch.simulation.models import Bar


def aggregate_weekly_bars(daily_bars: Iterable[Bar]) -> list[Bar]:
    ordered = sorted(daily_bars, key=lambda item: (item.ticker, item.date))
    keys = [(item.ticker, item.date) for item in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate ticker-date daily bars are not allowed")

    groups: dict[tuple[str, int, int], list[Bar]] = defaultdict(list)
    for item in ordered:
        iso = item.date.isocalendar()
        groups[(item.ticker, iso.year, iso.week)].append(item)

    weekly: list[Bar] = []
    for values in groups.values():
        values.sort(key=lambda item: item.date)
        first, last = values[0], values[-1]
        weekly.append(
            Bar(
                ticker=first.ticker,
                date=last.date,
                open=first.open,
                high=max(item.high for item in values),
                low=min(item.low for item in values),
                close=last.close,
                volume=sum(item.volume for item in values),
            )
        )
    return sorted(weekly, key=lambda item: (item.ticker, item.date))
