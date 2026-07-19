from __future__ import annotations

import unittest

from quantresearch.research.momentum_recommendations import qualifies, rank_qualifying


class MomentumRecommendationTests(unittest.TestCase):
    def test_12m_9m_6m_3m_rule_has_no_two_month_requirement(self) -> None:
        candidate = {
            "ret252": 0.80,
            "ret189": 0.60,
            "ret126": 0.40,
            "ret63": 0.20,
            "ret42": -0.50,
        }
        self.assertTrue(qualifies(candidate, "12M>9M>6M>3M>0"))

    def test_12m_6m_3m_rule_requires_each_return_to_descend_and_3m_to_be_positive(self) -> None:
        self.assertTrue(
            qualifies({"ret252": 0.80, "ret126": 0.40, "ret63": 0.20}, "12M>6M>3M>0")
        )
        self.assertFalse(
            qualifies({"ret252": 0.80, "ret126": 0.20, "ret63": 0.40}, "12M>6M>3M>0")
        )
        self.assertFalse(
            qualifies({"ret252": 0.80, "ret126": 0.40, "ret63": 0.00}, "12M>6M>3M>0")
        )

    def test_6m_4m_rule_requires_positive_4m_and_greater_6m(self) -> None:
        self.assertTrue(qualifies({"ret126": 0.50, "ret84": 0.20}, "6M>4M>0"))
        self.assertFalse(qualifies({"ret126": 0.50, "ret84": -0.01}, "6M>4M>0"))
        self.assertFalse(qualifies({"ret126": 0.20, "ret84": 0.50}, "6M>4M>0"))

    def test_ranking_uses_score_then_ticker_tie_break(self) -> None:
        rows = [
            {"ticker": "Z", "ret126": 0.4, "ret84": 0.1, "ranking_return": 0.9},
            {"ticker": "A", "ret126": 0.5, "ret84": 0.2, "ranking_return": 0.9},
            {"ticker": "X", "ret126": 0.1, "ret84": 0.2, "ranking_return": 1.0},
        ]
        ranked = rank_qualifying(rows, "6M>4M>0")
        self.assertEqual([row["ticker"] for row in ranked], ["A", "Z"])
        self.assertEqual([row["rank"] for row in ranked], [1, 2])
