"""Synthetic-fixture checks for tuning feature availability and preservation."""
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

from shrinkflation.category_data import _add_months, _build_category_frame
from shrinkflation.category_tuning_data import _enhance_frame, _same_month_features


class CategoryTuningDataTests(unittest.TestCase):
    def fixture(self):
        index = {_add_months(date(2015, 1, 1), offset): 100 + offset for offset in range(142)}
        weekly = {"cocoa_gbp": pd.DataFrame({"week_end": [date(2014, 1, 3) + timedelta(weeks=week) for week in range(670)], "value": np.arange(100, 770, dtype=float)})}
        base = _build_category_frame({"chocolate": index}, weekly, date(2026, 11, 8))
        return index, weekly, base

    def test_same_month_label_availability_and_aggregation(self):
        changes = {date(2023, 1, 1): 8., date(2022, 1, 1): 2., date(2021, 1, 1): -1.}
        result = _same_month_features(changes, date(2024, 1, 1), date(2023, 2, 8))
        self.assertTrue(np.isnan(result["history_same_month_lag1y_pct"]))
        self.assertEqual(result["history_same_month_mean3y_pct"], .5)
        later = _same_month_features(changes, date(2024, 1, 1), date(2023, 12, 8))
        self.assertEqual(later["history_same_month_lag1y_pct"], 8.)
        self.assertEqual(later["history_same_month_median3y_pct"], 2.)

    def test_preserves_frozen_targets_baselines_and_dates(self):
        index, weekly, base = self.fixture()
        enhanced, groups = _enhance_frame(base, {"chocolate": index}, weekly)
        pd.testing.assert_frame_equal(base, enhanced[base.columns], check_dtype=False)
        self.assertTrue((enhanced[[f"season_month_{month:02d}" for month in range(1, 13)]].sum(axis=1) == 1).all())
        self.assertIn("history_baseline_seasonal", groups["chocolate"]["seasonal_history"])
        self.assertNotIn("target_change_pct", groups["chocolate"]["seasonal_history_commodities"])

    def test_future_changes_cannot_change_historical_features(self):
        index, weekly, base = self.fixture()
        before, _ = _enhance_frame(base, {"chocolate": index}, weekly)
        target = "2024-01-01"
        changed = {month: value * (20 if month >= date(2023, 11, 1) else 1) for month, value in index.items()}
        changed_weekly = weekly["cocoa_gbp"].copy()
        changed_weekly.loc[changed_weekly.week_end >= date(2023, 12, 2), "value"] = 100000
        # Keep original labels in base: this tests only whether newly observed
        # source values can leak into the fixed historical feature computation.
        after, _ = _enhance_frame(base, {"chocolate": changed}, {"cocoa_gbp": changed_weekly})
        names = [name for name in before if name.startswith(("history_", "season_", "commodity_"))]
        a = before.loc[before.target_month == target, names].reset_index(drop=True)
        b = after.loc[after.target_month == target, names].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_live_lag_features_do_not_require_future_target_labels(self):
        index, weekly, base = self.fixture()
        # No Oct/Nov target labels: the earlier source issue remains observable.
        base = base.loc[(base.target_month < "2026-10-01") | base.is_live].copy()
        enhanced, _ = _enhance_frame(base, {"chocolate": index}, weekly)
        live = enhanced.loc[enhanced.is_live].iloc[0]
        self.assertTrue(np.isnan(live.target_change_pct))
        self.assertTrue(np.isfinite(live.commodity_cocoa_gbp_return_4w_pct_issue_lag1m))

    def test_easter_uses_known_calendar_not_outcomes(self):
        index, weekly, base = self.fixture()
        enhanced, groups = _enhance_frame(base, {"chocolate": index}, weekly)
        march = enhanced.loc[enhanced.target_month == "2024-03-01"].iloc[0]
        april = enhanced.loc[enhanced.target_month == "2024-04-01"].iloc[0]
        self.assertEqual(march.season_easter_month, 1.)
        self.assertEqual(april.season_after_easter_month, 1.)
        self.assertIn("season_easter_month", groups["chocolate"]["compactseasonal"])


if __name__ == "__main__":
    unittest.main()
