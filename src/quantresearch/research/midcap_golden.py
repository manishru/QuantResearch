"""Frozen contract for the reviewed Midcap Golden research strategy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MidcapGoldenDefinition:
    strategy_id: str = "midcap_golden_10m6m3m"
    momentum_rule: str = "10M>6M>3M>0"
    lookback_sessions: tuple[int, int, int] = (210, 126, 63)
    ranking_horizon: str = "10M"
    nominal_day: int = 14
    holding_weeks: int = 12
    stop: float = 0.30
    total_capital: float = 12_000.0
    sleeves: int = 3
    cost: float = 0.001
    candidate_depth: int = 20
    renewal_mode: str = "fixed_monthly_vintage"


MIDCAP_GOLDEN = MidcapGoldenDefinition()


def qualifies(return_10m: float, return_6m: float, return_3m: float) -> bool:
    """Return whether completed-close momentum strictly passes the rule."""
    return return_10m > return_6m > return_3m > 0


def build_backtest_command(
    *, python: str, project_root: Path, end: str, database: Path,
    membership: Path, corporate_actions: Path, output: Path,
    start: str = "2016-01-01",
) -> list[str]:
    """Translate the frozen contract into the existing audited engine CLI."""
    strategy = MIDCAP_GOLDEN
    return [
        python, str(project_root / "scripts" / "backtest_sp400_dynamic_vintage_matrix.py"),
        "--database", str(database), "--membership", str(membership),
        "--corporate-action-exits", str(corporate_actions),
        "--start", start, "--end", end,
        "--rule", strategy.momentum_rule, "--days", str(strategy.nominal_day),
        "--holding-weeks", str(strategy.holding_weeks), "--stops", str(strategy.stop),
        "--total-capital", str(strategy.total_capital), "--cost", str(strategy.cost),
        "--candidate-depth", str(strategy.candidate_depth),
        "--unique-open-tickers-for", "all",
        "--renewal-mode", strategy.renewal_mode,
        "--top-ledgers", "1", "--output", str(output),
    ]
