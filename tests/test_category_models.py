"""Synthetic fixtures exercise chronology; never exported as real evidence."""
from datetime import date
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

MODULE = Path(__file__).resolve().parents[1] / "src/shrinkflation/category_models.py"
if MODULE.exists():
    spec = importlib.util.spec_from_file_location("category_models_under_test", MODULE)
    models = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(models)
else:
    from shrinkflation import category_models as models


def synthetic_frame():
    rows = []
    for i, month in enumerate(pd.date_range("2016-01-01", "2025-04-01", freq="MS", tz="UTC")):
        cutoff = month - pd.DateOffset(months=1) + pd.Timedelta(days=7)
        live = month == pd.Timestamp("2025-04-01", tz="UTC")
        rows.append({
            "category_id": "fixture", "category_name": "Synthetic test fixture",
            "target_month": month, "forecast_cutoff": cutoff,
            "label_available_date": month + pd.DateOffset(months=2),
            "target_change_pct": np.nan if live else float(np.sin(i / 5) + 0.2),
            "is_live": live, "baseline_zero": 0.0, "baseline_recent": float(np.sin((i - 3) / 5) + 0.2),
            "baseline_seasonal": float(np.sin((i - 12) / 5) + 0.2), "baseline_trailing_mean": 0.2,
            "history_lag3": float(np.sin((i - 3) / 5)), "season_sin": float(np.sin(2 * np.pi * month.month / 12)),
            "commodity_real_test_feature": float(np.cos(i / 6)),
        })
    return pd.DataFrame(rows)


class CategoryModelTests(unittest.TestCase):
    def test_training_obeys_release_not_just_target_order(self):
        frame = models._prepare_frame(synthetic_frame())
        cutoff = pd.Timestamp("2023-12-08", tz="UTC")
        train = models._training_rows(frame[~frame.is_live], cutoff)
        self.assertTrue((train.label_available_date <= cutoff).all())
        self.assertEqual(train.target_month.max(), pd.Timestamp("2023-10-01", tz="UTC"))
        self.assertNotIn(pd.Timestamp("2023-11-01", tz="UTC"), set(train.target_month))

    def test_validation_excludes_unavailable_november_and_december(self):
        frame = models._prepare_frame(synthetic_frame())
        validation = frame[(frame.target_month >= models.VALIDATION_START)
                           & (frame.target_month < models.TEST_START)
                           & (frame.label_available_date <= models.SELECTION_CUTOFF)]
        self.assertEqual(validation.target_month.max(), pd.Timestamp("2023-10-01", tz="UTC"))

    def test_preprocessing_is_fit_per_fold_and_hgb_has_no_random_holdout(self):
        ridge = models._make_model("ridge", {"alpha": 10.0})
        self.assertIn("imputer", ridge.named_steps)
        self.assertIn("scaler", ridge.named_steps)
        hgb = models._make_model("hist_gradient_boosting", {"max_iter": 5})
        self.assertFalse(hgb.named_steps["model"].early_stopping)
        frame = models._prepare_frame(synthetic_frame())
        targets = frame.loc[frame.target_month == pd.Timestamp("2024-01-01", tz="UTC")]
        fits = []
        original = ridge.fit
        def record_fit(x, y):
            fits.append((x.copy(), y.copy()))
            return original(x, y)
        with patch.object(models, "_make_model", return_value=ridge), patch.object(ridge, "fit", side_effect=record_fit):
            predictions = models._predict_rows(frame[~frame.is_live], targets, "ridge", ["history_lag3"], {"alpha": 10.0})
        self.assertEqual(len(fits), 1)
        train = models._training_rows(frame[~frame.is_live], targets.iloc[0].forecast_cutoff)
        self.assertEqual(list(fits[0][0].index), list(train.index))
        self.assertAlmostEqual(ridge.named_steps["scaler"].mean_[0], train.history_lag3.mean())
        self.assertEqual(predictions.iloc[0].max_train_target_month, "2023-10-01")

    def test_future_coverage_does_not_enable_commodity_group(self):
        frame = models._prepare_frame(synthetic_frame())
        frame.loc[frame.target_month < models.TEST_START, "commodity_real_test_feature"] = np.nan
        validation = frame[(frame.target_month >= models.VALIDATION_START) & (frame.target_month < models.TEST_START)]
        groups, audit = models._feature_groups(frame, validation, {}, "fixture")
        self.assertNotIn("history_plus_weekly_commodities", groups)
        self.assertEqual(audit["commodity_group_status"], "skipped_insufficient_pretest_coverage")

    def test_selection_ignores_final_test_values_and_writes_auditable_artifacts(self):
        metadata = {"synthetic_fixture": True, "category_commodity_features": {"fixture": []}}
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            frame = synthetic_frame()
            with patch.object(models, "_model_specs", return_value={"ridge": [{"alpha": 10.0}]}), patch.object(models, "_plot_category"):
                first = models.run_frame_experiments(Path(tmp1), frame, metadata, date(2025, 3, 8))
                frame.loc[frame.target_month >= models.TEST_START, "target_change_pct"] = 100.0
                second = models.run_frame_experiments(Path(tmp2), frame, metadata, date(2025, 3, 8))
            c1, c2 = first["categories"][0], second["categories"][0]
            self.assertEqual(c1["selected_model_id"], c2["selected_model_id"])
            self.assertEqual(c1["selected_feature_group"], c2["selected_feature_group"])
            self.assertEqual(c1["validation_metrics"], c2["validation_metrics"])
            self.assertNotEqual(c1["test_metrics"]["mae_pp"], c2["test_metrics"]["mae_pp"])
            base = Path(tmp1) / "data/experiments/category_forecast/fixture/ridge/history_only"
            for name in ("config.json", "metrics.json", "validation_predictions.csv", "test_predictions.csv", "model.joblib"):
                self.assertTrue((base / name).exists(), name)
            predictions = pd.read_csv(base / "test_predictions.csv")
            self.assertTrue((pd.to_datetime(predictions.max_train_label_available_date, utc=True)
                             <= pd.to_datetime(predictions.forecast_cutoff, utc=True)).all())
            self.assertIsNone(c1["forecast"]["interval"])

    def test_duplicate_outcomes_rejected(self):
        frame = synthetic_frame()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            models._prepare_frame(pd.concat([frame, frame.iloc[[0]]]))

    def test_metrics_use_percentage_points_and_signed_direction(self):
        predictions = pd.DataFrame({"actual_pct": [-2.0, 0.0, 2.0], "predicted_pct": [-1.0, 1.0, 3.0]})
        metrics = models._metrics(predictions)
        self.assertEqual(metrics["mae_pp"], 1.0)
        self.assertEqual(metrics["rmse_pp"], 1.0)
        self.assertAlmostEqual(metrics["directional_accuracy"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
