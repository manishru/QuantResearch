from unittest import TestCase

from quantresearch.research.news_rotation import aggregate_basket_observations


class NewsRotationTests(TestCase):
    def test_sentiment_is_weighted_by_article_count_and_basket_membership(self) -> None:
        result = aggregate_basket_observations(
            (("MU", "2026-07-01", .2, 10), ("WDC", "2026-07-01", .8, 30), ("AAPL", "2026-07-01", .9, 20)),
            {"MU", "WDC"},
        )
        self.assertEqual(result["2026-07-01"][1], 40)
        self.assertAlmostEqual(result["2026-07-01"][0], .65)
