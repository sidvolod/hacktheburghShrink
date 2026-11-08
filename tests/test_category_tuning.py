"""Synthetic chronology fixtures; none are real grocery evidence."""
from datetime import date
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

STAGED = Path(__file__).resolve().parents[1] / "src/shrinkflation/category_tuning.py"
if STAGED.exists():
    spec = importlib.util.spec_from_file_location("shrinkflation.category_tuning_under_test", STAGED)
    tuning = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tuning)
else:
    from shrinkflation import category_tuning as tuning


def frame_fixture():
    rows = []
    for i, month in enumerate(pd.date_range("2016-01-01", "2025-04-01", freq="MS", tz="UTC")):
        live = month == pd.Timestamp("2025-04-01", tz="UTC")
        rows.append({"category_id": "fixture", "category_name": "Synthetic fixture",
                     "target_month": month, "forecast_cutoff": month - pd.DateOffset(months=1) + pd.Timedelta(days=7),
                     "label_available_date": month + pd.DateOffset(months=2),
                     "target_change_pct": np.nan if live else float(np.sin(i / 4)), "is_live": live,
                     "baseline_zero": 0.0, "baseline_recent": 0.1, "baseline_trailing_mean": 0.2,
                     "baseline_seasonal": 0.3, "baseline_seasonal_mean3": 0.2,
                     "baseline_seasonal_median3": 0.1, "baseline_seasonal_mean5": 0.15,
                     "history_signal": float(np.sin((i - 3) / 4)), "season_sin": float(np.sin(month.month / 12 * 2 * np.pi))})
    return pd.DataFrame(rows)


def prediction_fixture():
    rows = []
    for month in pd.date_range("2020-01-01", "2024-03-01", freq="MS", tz="UTC"):
        rows.append({"target_month": month.strftime("%Y-%m-%d"),
                     "forecast_cutoff": (month - pd.DateOffset(months=1) + pd.Timedelta(days=7)).isoformat(),
                     "label_available_date": (month + pd.DateOffset(months=2)).isoformat(),
                     "actual_pct": 0.0, "predicted_pct": 0.1})
    return pd.DataFrame(rows)


class CategoryTuningTests(unittest.TestCase):
    def test_catalog_is_bounded_and_has_windows_and_robust_losses(self):
        catalog = tuning._catalog()
        self.assertEqual(len(catalog), 59)
        self.assertEqual(len({s["candidate_id"] for s in catalog}), len(catalog))
        self.assertEqual({s["training_window_months"] for s in catalog}, {None, 36, 60})
        self.assertTrue({"absolute_error", "huber", "squared_error"}
                        <= {s["params"].get("loss") for s in catalog})
        hgb = next(s for s in catalog if s["model_id"] == "hist_gradient_boosting")
        self.assertFalse(tuning._make_estimator(hgb).named_steps["model"].early_stopping)

    def test_train_window_and_publication_cutoff(self):
        frame = tuning._prepare_frame(frame_fixture())
        train = tuning._train_rows(frame[~frame.is_live], pd.Timestamp("2023-12-08", tz="UTC"), 36)
        self.assertEqual(len(train), 36)
        self.assertEqual(train.target_month.max(), pd.Timestamp("2023-10-01", tz="UTC"))
        self.assertEqual(train.target_month.min(), pd.Timestamp("2020-11-01", tz="UTC"))
        self.assertTrue((train.label_available_date <= pd.Timestamp("2023-12-08", tz="UTC")).all())

    def test_inner_selection_cannot_see_unpublished_prior_month_or_future_errors(self):
        a, b = prediction_fixture(), prediction_fixture()
        b["predicted_pct"] = 0.2
        cutoff = pd.Timestamp("2023-12-08", tz="UTC")
        scores, audit = tuning._inner_scores({"a": a, "b": b}, cutoff)
        self.assertEqual(scores[0]["candidate_id"], "a")
        self.assertEqual(audit["max_target_month"], "2023-10-01")
        self.assertEqual(audit["n"], 36)
        b.loc[b.target_month >= "2023-11-01", "predicted_pct"] = 0.0
        a.loc[a.target_month >= "2023-11-01", "predicted_pct"] = 10000.0
        changed, _ = tuning._inner_scores({"a": a, "b": b}, cutoff)
        self.assertEqual(scores, changed)

    def test_residual_fit_uses_known_baseline_and_fold_only_preprocessing(self):
        frame = tuning._prepare_frame(frame_fixture())
        row = frame[frame.target_month == pd.Timestamp("2024-01-01", tz="UTC")].iloc[0]
        spec = {"kind": "learned", "model_id": "residual_ridge", "params": {"alpha": 10.0},
                "training_window_months": None, "residual_baseline": "baseline_seasonal_mean3"}
        value, pipeline, audit = tuning._fit_predict(frame[~frame.is_live], row, spec, ["history_signal"])
        train = tuning._train_rows(frame[~frame.is_live], row.forecast_cutoff, None)
        self.assertAlmostEqual(pipeline.named_steps["scaler"].mean_[0], train.history_signal.mean())
        expected = pipeline.predict(pd.DataFrame({"history_signal": [row.history_signal]}))[0] + row.baseline_seasonal_mean3
        self.assertAlmostEqual(value, expected)
        self.assertEqual(audit["max_train_target_month"], "2023-10-01")

    def test_manifest_is_frozen_and_build_time_does_not_invalidate_cache(self):
        frame = tuning._prepare_frame(frame_fixture())
        metadata = {"generated_at": "first", "synthetic_fixture": True,
                    "feature_groups": {"fixture": {"seasonal_history": ["history_signal"]}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir, first = tuning._freeze_manifest(root, frame, metadata, tuning._catalog(), date(2025, 3, 8))
            metadata["generated_at"] = "second"
            second_dir, second = tuning._freeze_manifest(root, frame, metadata, tuning._catalog(), date(2025, 3, 8))
            self.assertEqual(first_dir, second_dir)
            self.assertEqual(first, second)
            frame.loc[0, "history_signal"] += 1
            changed_dir, _ = tuning._freeze_manifest(root, frame, metadata, tuning._catalog(), date(2025, 3, 8))
            self.assertNotEqual(first_dir, changed_dir)
            self.assertTrue((first_dir / "search_manifest.json").exists())

    def test_end_to_end_strategy_identity_and_original_files_preserved(self):
        catalog = [s for s in tuning._catalog() if s["candidate_id"] in ("baseline_zero", "baseline_recent", "ridge_seasonal_history_a10")]
        metadata = {"synthetic_fixture": True, "feature_groups": {"fixture": {"seasonal_history": ["history_signal", "season_sin"]}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_path = root / "data/experiments/category_forecast/summary.json"
            original_path.parent.mkdir(parents=True)
            original = {"categories": [{"category_id": "fixture", "selected_model_id": "previous_model",
                                       "selected_feature_group": "previous_features", "test_predictions": []}]}
            original_path.write_text(json.dumps(original))
            before = original_path.read_bytes()
            # An empty historical reference is allowed and must not invent scores.
            with patch.object(tuning, "_plot"):
                summary = tuning.run_tuning_frame(root, frame_fixture(), metadata, date(2025, 3, 8), catalog)
            self.assertEqual(before, original_path.read_bytes())
            self.assertEqual(summary["evaluation_status"], "retrospective_exploratory")
            result = summary["categories"][0]
            self.assertEqual(result["selected_model_id"], "nested_selector")
            self.assertEqual(result["selected_feature_group"], "adaptive_past_only")
            self.assertIn("current_candidate_id", result["forecast"])
            self.assertIn("current_model_id", result["forecast"])
            self.assertTrue(any(r["candidate_id"] == "nested_selector" for r in result["leaderboard"]))
            for prediction in result["test_predictions"]:
                self.assertIn("candidate_id", prediction)
                self.assertIn("model_id", prediction)
                self.assertIn("feature_group", prediction)
                self.assertLessEqual(pd.Timestamp(prediction["selection_max_label_available_date"]), pd.Timestamp(prediction["forecast_cutoff"]))


if __name__ == "__main__":
    unittest.main()
