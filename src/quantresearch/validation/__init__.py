"""Research data-quality validation."""

from quantresearch.validation.market_anomalies import (
    MarketAnomaly,
    detect_price_discontinuities,
)

__all__ = ["MarketAnomaly", "detect_price_discontinuities"]
