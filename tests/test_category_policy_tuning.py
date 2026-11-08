"""Synthetic policy/cache fixtures; no real accuracy claims."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

STAGED = Path(__file__).resolve().parents[1] / "src/shrinkflation/category_policy_tuning.py"
if STAGED.exists():
    spec = importlib.util.spec_from_file_location("shrinkflation.category_policy_under_test", STAGED)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
else:
    from shrinkflation import category_policy_tuning as policy


def cache_fixture():
    rows = []
    for month in pd.date_range("2020-01-01", "2024-06-01", freq="MS", tz="UTC"):
        rows.append({"target_month": month.strftime("%Y-%m-%d"),
                     "forecast_cutoff": (month - pd.DateOffset(months=1) + pd.Timedelta(days=7)).isoformat(),
                     "label_available_date": (month + pd.DateOffset(months=2)).isoformat(),
                     "actual_pct": 0.0, "predicted_pct": 0.0, "baseline_pct": 0.0})
    base = pd.DataFrame(rows)
    caches = {"baseline_zero": base.copy()}
    for i in range(1, 6):
        predictions = base.copy()
        predictions["predicted_pct"] = i / 10
        caches[f"candidate_{i}"] = predictions
    return caches


class CategoryPolicyTests(unittest.TestCase):
    def test_ten_frozen_policies_include_safe_zero_and_recent_windows(self):
        catalog = policy.policy_catalog()
        self.assertEqual(len(catalog), 10)
        self.assertEqual(len({p["policy_id"] for p in catalog}), 10)
        self.assertEqual({p["candidate_error_window_months"] for p in catalog}, {12, 24, 36})
        self.assertEqual(next(p for p in catalog if p["policy_id"] == "zero")["aggregation"], "zero")

    def test_inverse_mae_weights_use_only_scores_and_handle_zero_error(self):
        p = next(p for p in policy.policy_catalog() if p["policy_id"] == "inverse_mae_top3")
        scores = [{"candidate_id": "a", "mae_pp": 1.0}, {"candidate_id": "b", "mae_pp": 2.0},
                  {"candidate_id": "c", "mae_pp": 4.0}]
        value, components = policy._aggregate(p, scores, {"a": 1.0, "b": 2.0, "c": 4.0})
        self.assertAlmostEqual(value, 12 / 7)
        self.assertAlmostEqual(sum(c["weight"] for c in components), 1.0)
        scores[0]["mae_pp"] = 0.0
        value, components = policy._aggregate(p, scores, {"a": 1.0, "b": 2.0, "c": 4.0})
        self.assertTrue(np.isfinite(value))
        self.assertGreater(components[0]["weight"], .999)

    def test_median_and_shrinkage_are_auditable(self):
        catalog = {p["policy_id"]: p for p in policy.policy_catalog()}
        scores = [{"candidate_id": str(i), "mae_pp": i + 1.0} for i in range(3)]
        value, components = policy._aggregate(catalog["median_top3"], scores, {"0": 1.0, "1": 100.0, "2": 2.0})
        self.assertEqual(value, 2.0)
        self.assertTrue(all(c["weight"] is None for c in components))
        value, _ = policy._aggregate(catalog["best1_shrink075"], scores, {"0": 4.0})
        self.assertEqual(value, 3.0)
        value, components = policy._aggregate(catalog["zero"], [], {})
        self.assertEqual(value, 0.0)
        self.assertEqual(components, [])

    def test_recent_window_never_mutates_helper_or_uses_unknown_errors(self):
        caches = cache_fixture()
        cutoff = pd.Timestamp("2023-12-08", tz="UTC")
        scores, audit = policy._candidate_scores(caches, cutoff, 12)
        self.assertEqual(audit["n"], 12)
        self.assertEqual(audit["min_target_month"], "2022-11-01")
        self.assertEqual(audit["max_target_month"], "2023-10-01")
        for rows in caches.values():
            rows.loc[rows.target_month >= "2023-11-01", "actual_pct"] = 10000.0
        changed, _ = policy._candidate_scores(caches, cutoff, 12)
        self.assertEqual(scores, changed)
        _, full = policy._candidate_scores(caches, cutoff, 36)
        self.assertEqual(full["n"], 36)

    def test_policy_oof_and_meta_choice_obey_both_availability_layers(self):
        caches = cache_fixture()
        target = caches["baseline_zero"]
        target = target[target.target_month >= "2021-01-01"]
        oof = policy.build_policy_oof(caches, target)
        outer = target[target.target_month >= "2024-01-01"]
        selected = policy.select_policies(oof, outer)
        self.assertFalse(selected.empty)
        for _, row in selected.iterrows():
            self.assertLessEqual(pd.Timestamp(row.candidate_selection_max_label_available_date), pd.Timestamp(row.forecast_cutoff))
            self.assertLessEqual(pd.Timestamp(row.policy_selection_max_label_available_date), pd.Timestamp(row.forecast_cutoff))
            self.assertIn("components", row)
        cutoff = pd.Timestamp("2023-12-08", tz="UTC")
        before, _ = policy._policy_scores(oof, cutoff)
        for rows in oof.values():
            unknown = pd.to_datetime(rows.label_available_date, utc=True) > cutoff
            rows.loc[unknown, "actual_pct"] = 10000.0
            rows.loc[unknown, "predicted_pct"] = -10000.0
        after, _ = policy._policy_scores(oof, cutoff)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
