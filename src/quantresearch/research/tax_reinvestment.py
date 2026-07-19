"""Tax-aware replay of capital-independent monthly trade templates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite


@dataclass(frozen=True, slots=True)
class TradeTemplate:
    template_id: str
    ticker: str
    entry_date: date
    exit_date: date | None
    return_pct: float
    exit_reason: str


@dataclass(frozen=True, slots=True)
class TaxReinvestmentConfig:
    monthly_contribution: float
    tax_rate: float
    final_date: date
    contribution_months: int | None = None
    spread_early_exit_to_maturity: bool = False
    maturity_reinvestment_spread_months: int = 1
    holding_months: int | None = 12
    holding_weeks: int | None = None

    def __post_init__(self) -> None:
        if self.monthly_contribution < 0:
            raise ValueError("monthly_contribution must be non-negative")
        if not 0 <= self.tax_rate <= 1:
            raise ValueError("tax_rate must be between zero and one")
        if self.contribution_months is not None and self.contribution_months < 0:
            raise ValueError("contribution_months must be non-negative")
        if self.maturity_reinvestment_spread_months < 1:
            raise ValueError("maturity_reinvestment_spread_months must be positive")
        if self.holding_months is not None and self.holding_months < 1:
            raise ValueError("holding_months must be positive")
        if self.holding_weeks is not None and self.holding_weeks < 1:
            raise ValueError("holding_weeks must be positive")
        if self.holding_months is not None and self.holding_weeks is not None:
            raise ValueError("holding_months and holding_weeks are mutually exclusive")


@dataclass(slots=True)
class ScaledTrade:
    template_id: str
    ticker: str
    entry_date: date
    exit_date: date | None
    exit_reason: str
    return_pct: float
    allocated_capital: float
    net_profit: float
    pre_tax_proceeds: float
    tax_paid: float
    after_tax_proceeds: float
    is_open: bool


@dataclass(frozen=True, slots=True)
class CashLedgerRow:
    event_date: date
    event_type: str
    starting_cash: float
    exit_proceeds: float
    tax_paid: float
    contribution: float
    invested: float
    ending_cash: float


@dataclass(slots=True)
class TaxReinvestmentResult:
    trades: list[ScaledTrade]
    ledger: list[CashLedgerRow]
    total_contributions: float
    total_net_profit: float
    total_tax_paid: float
    ending_cash: float
    open_market_value: float
    hypothetical_liquidation_tax: float
    ending_after_tax_wealth: float
    roi: float | None
    xirr: float | None
    ending_after_liquidation_tax: float
    liquidation_roi: float | None
    liquidation_xirr: float | None


def _xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if not any(value < 0 for _, value in cashflows) or not any(
        value > 0 for _, value in cashflows
    ):
        return None
    origin = min(day for day, _ in cashflows)

    def npv(rate: float) -> float:
        return sum(
            value / (1 + rate) ** ((day - origin).days / 365.2425)
            for day, value in cashflows
        )

    low, high = -0.9999, 1000.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_low * f_mid <= 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def replay_tax_reinvestment(
    templates: list[TradeTemplate], config: TaxReinvestmentConfig
) -> TaxReinvestmentResult:
    """Replay monthly batches, reusing only proceeds from earlier sessions."""
    if not templates:
        return TaxReinvestmentResult(
            [], [], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, None,
            0.0, None, None,
        )
    for template in templates:
        if not isfinite(template.return_pct) or template.return_pct < -1:
            raise ValueError(f"invalid return_pct for {template.template_id}")
        if template.entry_date > config.final_date:
            raise ValueError("entry_date cannot be after final_date")

    batches: dict[date, list[TradeTemplate]] = {}
    for template in templates:
        batches.setdefault(template.entry_date, []).append(template)

    cash = 0.0
    deferred_future_cash = 0.0
    scheduled_credits: dict[date, float] = {}
    contributions = 0.0
    realized_net_profit = 0.0
    realized_tax = 0.0
    scaled: list[ScaledTrade] = []
    pending: list[ScaledTrade] = []
    ledger: list[CashLedgerRow] = []
    cashflows: list[tuple[date, float]] = []

    purchase_dates = sorted(batches)
    if config.holding_weeks is not None:
        maturity_by_entry = {
            entry: entry + timedelta(days=config.holding_weeks * 7)
            for entry in purchase_dates
        }
    else:
        holding_months = config.holding_months or 12
        maturity_by_entry = {
            entry: purchase_dates[index + holding_months]
            for index, entry in enumerate(purchase_dates)
            if index + holding_months < len(purchase_dates)
        }

    def settle_before(
        cutoff: date, inclusive: bool, *, final_settlement: bool = False
    ) -> tuple[float, float]:
        nonlocal cash, deferred_future_cash, realized_net_profit, realized_tax, pending
        proceeds = 0.0
        remaining: list[ScaledTrade] = []
        due_trades: list[ScaledTrade] = []
        for trade in pending:
            due = trade.exit_date is not None and (
                trade.exit_date < cutoff or (inclusive and trade.exit_date <= cutoff)
            )
            if due:
                due_trades.append(trade)
            else:
                remaining.append(trade)
        event_profit = sum(trade.net_profit for trade in due_trades)
        new_realized_profit = realized_net_profit + event_profit
        new_tax_liability = max(new_realized_profit, 0.0) * config.tax_rate
        tax_change = new_tax_liability - realized_tax
        if tax_change >= 0:
            denominator = sum(max(trade.net_profit, 0.0) for trade in due_trades)
            for trade in due_trades:
                trade.tax_paid = (
                    tax_change * max(trade.net_profit, 0.0) / denominator
                    if denominator
                    else 0.0
                )
                trade.after_tax_proceeds = trade.pre_tax_proceeds - trade.tax_paid
        else:
            denominator = sum(max(-trade.net_profit, 0.0) for trade in due_trades)
            for trade in due_trades:
                trade.tax_paid = (
                    tax_change * max(-trade.net_profit, 0.0) / denominator
                    if denominator
                    else 0.0
                )
                trade.after_tax_proceeds = trade.pre_tax_proceeds - trade.tax_paid
        if config.spread_early_exit_to_maturity and not final_settlement:
            for trade in due_trades:
                maturity = maturity_by_entry.get(
                    trade.entry_date,
                    trade.entry_date
                    + timedelta(
                        days=(
                            config.holding_weeks * 7
                            if config.holding_weeks is not None
                            else round(365.2425 * (config.holding_months or 12) / 12)
                        )
                    ),
                )
                is_early = (
                    trade.exit_date is not None
                    and trade.exit_date < maturity
                    and trade.exit_reason not in {"one_year", "open", "open_mtm"}
                )
                if is_early:
                    remaining_dates = [
                        day
                        for day in purchase_dates
                        if trade.exit_date < day <= maturity
                    ]
                    if remaining_dates:
                        installment = trade.after_tax_proceeds / len(remaining_dates)
                        for day in remaining_dates:
                            scheduled_credits[day] = scheduled_credits.get(day, 0.0) + installment
                    else:
                        scheduled_credits[cutoff] = (
                            scheduled_credits.get(cutoff, 0.0) + trade.after_tax_proceeds
                        )
                else:
                    spread = config.maturity_reinvestment_spread_months
                    eligible_dates = [day for day in purchase_dates if day >= cutoff][:spread]
                    installment = trade.after_tax_proceeds / spread
                    for day in eligible_dates:
                        scheduled_credits[day] = scheduled_credits.get(day, 0.0) + installment
                    deferred_future_cash += installment * (spread - len(eligible_dates))
            proceeds = scheduled_credits.pop(cutoff, 0.0)
            cash += proceeds
        else:
            proceeds = sum(trade.after_tax_proceeds for trade in due_trades)
            cash += proceeds
        realized_net_profit = new_realized_profit
        realized_tax = new_tax_liability
        pending = remaining
        return proceeds, tax_change

    for batch_index, entry_date in enumerate(sorted(batches)):
        starting_cash = cash
        # The declared tranche convention sells a matured/triggered lot first and
        # reuses its after-tax proceeds for the purchase on the same session.
        exit_proceeds, tax_paid = settle_before(entry_date, inclusive=True)
        deferred_credit = scheduled_credits.pop(entry_date, 0.0)
        cash += deferred_credit
        exit_proceeds += deferred_credit
        contribution = (
            config.monthly_contribution
            if config.contribution_months is None
            or batch_index < config.contribution_months
            else 0.0
        )
        cash += contribution
        contributions += contribution
        if contribution:
            cashflows.append((entry_date, -contribution))
        batch = sorted(batches[entry_date], key=lambda item: (item.ticker, item.template_id))
        invested = cash
        if invested > 0:
            allocation = invested / len(batch)
            cash = 0.0
            for template in batch:
                profit = allocation * template.return_pct
                pre_tax = allocation + profit
                trade = ScaledTrade(
                    template.template_id,
                    template.ticker,
                    template.entry_date,
                    template.exit_date,
                    template.exit_reason,
                    template.return_pct,
                    allocation,
                    profit,
                    pre_tax,
                    0.0,
                    pre_tax,
                    template.exit_date is None or template.exit_reason in {"open", "open_mtm"},
                )
                scaled.append(trade)
                pending.append(trade)
        ledger.append(
            CashLedgerRow(
                entry_date,
                "monthly_purchase",
                starting_cash,
                exit_proceeds,
                tax_paid,
                contribution,
                invested,
                cash,
            )
        )

    starting_cash = cash
    exit_proceeds, tax_paid = settle_before(
        config.final_date, inclusive=True, final_settlement=True
    )
    deferred_credit = sum(scheduled_credits.values())
    scheduled_credits.clear()
    cash += deferred_credit + deferred_future_cash
    exit_proceeds += deferred_credit + deferred_future_cash
    deferred_future_cash = 0.0
    ledger.append(
        CashLedgerRow(
            config.final_date,
            "final_settlement",
            starting_cash,
            exit_proceeds,
            tax_paid,
            0.0,
            0.0,
            cash,
        )
    )

    open_value = sum(trade.pre_tax_proceeds for trade in pending)
    open_profit = sum(trade.net_profit for trade in pending)
    liquidation_tax = max(realized_net_profit + open_profit, 0.0) * config.tax_rate - realized_tax
    ending = cash + open_value
    total_profit = realized_net_profit + sum(trade.net_profit for trade in pending)
    total_tax = realized_tax
    roi = (ending / contributions - 1) if contributions else None
    ending_after_liquidation_tax = ending - liquidation_tax
    liquidation_roi = (
        ending_after_liquidation_tax / contributions - 1 if contributions else None
    )
    before_open_tax_cashflows = [*cashflows, (config.final_date, ending)]
    liquidation_cashflows = [
        *cashflows, (config.final_date, ending_after_liquidation_tax)
    ]

    return TaxReinvestmentResult(
        scaled,
        ledger,
        contributions,
        total_profit,
        total_tax,
        cash,
        open_value,
        liquidation_tax,
        ending,
        roi,
        _xirr(before_open_tax_cashflows),
        ending_after_liquidation_tax,
        liquidation_roi,
        _xirr(liquidation_cashflows),
    )
