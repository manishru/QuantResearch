"""Versioned strategy definitions used as research controls."""

from quantresearch.research.models import StrategyDefinition


def buy_and_hold(index_id: str) -> StrategyDefinition:
    return StrategyDefinition(
        name="point-in-time-index-buy-and-hold",
        universe={"index_id": index_id, "membership": "point_in_time"},
        signal={"type": "always_invested"},
        ranking={"type": "equal_weight"},
        entry={"timing": "next_session_open"},
        exit={"on_index_removal": "next_session_open"},
        sizing={"type": "equal_weight"},
        risk={"max_drawdown_fraction": 0.40},
    )


def balanced_dual_supertrend(index_id: str) -> StrategyDefinition:
    return StrategyDefinition(
        name="balanced-dual-supertrend-v1",
        universe={"index_id": index_id, "membership": "point_in_time"},
        signal={"momentum_order": ["5W", "6M", "9M"], "require_positive_5w": True},
        ranking={"candidate_pool": 20, "order_by": "5W", "descending": True},
        entry={
            "breakout_weeks": 7,
            "supertrend": [5, 2.25],
            "timing": "next_session_open_or_trigger",
        },
        exit={"supertrend": [13, 2.75], "timing": "next_session_open"},
        sizing={"type": "equal_weight", "max_positions": 16},
        risk={"max_drawdown_fraction": 0.40},
    )


def contaminated_52w_momentum_benchmark(index_id: str) -> StrategyDefinition:
    return StrategyDefinition(
        name="rejected-contaminated-52w-momentum",
        universe={"index_id": index_id, "membership": "point_in_time"},
        signal={"momentum_weeks": 52},
        ranking={"top_n": 10, "rebalance": "weekly"},
        entry={"timing": "next_session_open"},
        exit={"rebalance": "weekly"},
        sizing={"type": "equal_weight", "max_positions": 10},
        risk={
            "max_drawdown_fraction": 0.40,
            "deployment_status": "rejected_data_contamination",
        },
    )
