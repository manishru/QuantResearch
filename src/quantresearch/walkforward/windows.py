"""Canonical 8-year train / 2-year forward calendar scheduling."""

from __future__ import annotations

from datetime import date, timedelta

from quantresearch.walkforward.models import (
    ForwardState,
    PurgedValidationSplit,
    WalkForwardWindow,
)


def generate_walk_forward_windows(
    research_start_year: int,
    last_completed_year: int,
    *,
    train_years: int = 8,
    forward_years: int = 2,
    step_years: int = 2,
    warmup_days: int = 400,
) -> tuple[WalkForwardWindow, ...]:
    """Generate completed forward windows plus one live/unobserved window."""
    if train_years < 1 or forward_years < 1 or step_years < 1 or warmup_days < 0:
        raise ValueError("Window lengths must be positive and warmup_days nonnegative")
    if research_start_year + train_years - 1 > last_completed_year:
        raise ValueError("Insufficient completed years for the first training window")

    windows: list[WalkForwardWindow] = []
    train_start_year = research_start_year
    while train_start_year + train_years - 1 <= last_completed_year:
        train_start = date(train_start_year, 1, 1)
        train_end = date(train_start_year + train_years - 1, 12, 31)
        forward_start = date(train_start_year + train_years, 1, 1)
        forward_end = date(train_start_year + train_years + forward_years - 1, 12, 31)
        state = (
            ForwardState.AVAILABLE
            if forward_end.year <= last_completed_year
            else ForwardState.LIVE_UNOBSERVED
        )
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                forward_start=forward_start,
                forward_end=forward_end,
                warmup_start=train_start - timedelta(days=warmup_days),
                execution_start=train_start,
                forward_state=state,
            )
        )
        train_start_year += step_years
    return tuple(windows)


def purged_training_validation_split(
    window: WalkForwardWindow,
    *,
    validation_years: int = 2,
    purge_days: int,
    embargo_days: int,
) -> PurgedValidationSplit:
    """Reserve the final training years for internal time-series validation."""
    if validation_years < 1 or purge_days < 0 or embargo_days < 0:
        raise ValueError("Validation years and boundary controls are invalid")
    nominal_start = date(window.train_end.year - validation_years + 1, 1, 1)
    fit_end = nominal_start - timedelta(days=purge_days + 1)
    validation_start = nominal_start + timedelta(days=embargo_days)
    if fit_end < window.train_start or validation_start > window.train_end:
        raise ValueError("Purge/embargo leaves an empty fit or validation period")
    return PurgedValidationSplit(
        fit_start=window.train_start,
        fit_end=fit_end,
        validation_nominal_start=nominal_start,
        validation_start=validation_start,
        validation_end=window.train_end,
        purge_days=purge_days,
        embargo_days=embargo_days,
    )
