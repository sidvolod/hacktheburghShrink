"""Chronological category-index forecasting experiments, never SKU shrink labels.

Issue day is supplied by category_data: the eighth of the month before the
target. Every training label must have been published by that issue instant.
The final test is frozen at January 2024 onward; its outcomes never select a
model, a hyperparameter, a feature, an imputer or a scaler.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

MIN_TRAIN = 24
VALIDATION_START = pd.Timestamp("2021-01-01", tz="UTC")
TEST_START = pd.Timestamp("2024-01-01", tz="UTC")
SELECTION_CUTOFF = pd.Timestamp("2023-12-08", tz="Europe/London").tz_convert("UTC")
BASELINES = {
    "no_change": "baseline_zero",
    "seasonal": "baseline_seasonal",
    "recent": "baseline_recent",
    "trailing_mean": "baseline_trailing_mean",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(value), indent=2, allow_nan=False) + "\n")


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"category_id", "category_name", "target_month", "forecast_cutoff",
                "label_available_date", "target_change_pct", "is_live", *BASELINES.values()}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing category data columns: {sorted(missing)}")
    frame = frame.copy()
    for col in ("target_month", "forecast_cutoff", "label_available_date"):
        frame[col] = pd.to_datetime(frame[col], utc=True, errors="raise")
    numeric = [c for c in frame if c.startswith(("history_", "season_", "commodity_", "baseline_"))]
    for col in ["target_change_pct", *numeric]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    frame["is_live"] = frame["is_live"].astype(bool)
    if frame.duplicated(["category_id", "target_month"]).any():
        raise ValueError("Duplicate category/target_month rows are not independent outcomes")
    historical = frame.loc[~frame.is_live]
    if historical.label_available_date.isna().any():
        raise ValueError("Historical labels require a conservative availability date")
    if (historical.label_available_date < historical.target_month).any():
        raise ValueError("A monthly outcome cannot be available before its target month")
    return frame.sort_values(["category_id", "target_month"]).reset_index(drop=True)


def _metrics(predictions: pd.DataFrame) -> dict[str, Any]:
    if predictions.empty:
        return {"n": 0, "mae_pp": None, "rmse_pp": None, "directional_accuracy": None}
    actual = predictions.actual_pct.to_numpy(float)
    predicted = predictions.predicted_pct.to_numpy(float)
    errors = predicted - actual
    signs = lambda x: np.where(np.abs(x) < 1e-9, 0, np.sign(x))
    return {"n": len(actual), "mae_pp": float(np.mean(np.abs(errors))),
            "rmse_pp": float(np.sqrt(np.mean(errors ** 2))),
            "directional_accuracy": float(np.mean(signs(actual) == signs(predicted)))}


def _model_specs() -> dict[str, list[dict[str, Any]]]:
    # Fixed before looking at the test. No random internal holdout/early stopping.
    return {
        "ridge": [{"alpha": a} for a in (0.1, 10.0, 100.0)],
        "hist_gradient_boosting": [
            {"max_iter": 80, "max_leaf_nodes": 5, "min_samples_leaf": 10, "l2_regularization": 10.0},
            {"max_iter": 120, "max_leaf_nodes": 7, "min_samples_leaf": 15, "l2_regularization": 20.0},
        ],
    }


def _make_model(model_id: str, config: dict[str, Any]) -> Pipeline:
    steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median", keep_empty_features=True))]
    if model_id == "ridge":
        steps += [("scaler", StandardScaler()), ("model", Ridge(**config))]
    elif model_id == "hist_gradient_boosting":
        steps += [("model", HistGradientBoostingRegressor(
            learning_rate=0.05, early_stopping=False, random_state=42, **config))]
    else:
        raise ValueError(f"Unknown learned model: {model_id}")
    return Pipeline(steps)


def _training_rows(history: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    return history.loc[(history.label_available_date <= cutoff)
                       & (history.forecast_cutoff < cutoff)
                       & history.target_change_pct.notna()]


def _prediction_record(row: pd.Series, prediction: float, train: pd.DataFrame) -> dict[str, Any]:
    return {"target_month": row.target_month.strftime("%Y-%m-%d"),
            "forecast_cutoff": row.forecast_cutoff.isoformat(),
            "label_available_date": row.label_available_date.isoformat(),
            "actual_pct": float(row.target_change_pct), "predicted_pct": float(prediction),
            "baseline_pct": float(row.baseline_zero), "train_n": len(train),
            "max_train_label_available_date": None if train.empty else train.label_available_date.max().isoformat(),
            "max_train_target_month": None if train.empty else train.target_month.max().strftime("%Y-%m-%d")}


def _predict_rows(history: pd.DataFrame, targets: pd.DataFrame, model_id: str,
                  features: list[str], config: dict[str, Any]) -> pd.DataFrame:
    records = []
    for _, row in targets.iterrows():
        train = _training_rows(history, row.forecast_cutoff)
        if model_id in BASELINES:
            prediction = row[BASELINES[model_id]]
            if pd.isna(prediction):
                continue
        else:
            if len(train) < MIN_TRAIN or not features:
                continue
            model = _make_model(model_id, config)
            model.fit(train[features], train.target_change_pct)
            prediction = model.predict(row.to_frame().T[features].astype(float))[0]
        if np.isfinite(prediction):
            records.append(_prediction_record(row, prediction, train))
    return pd.DataFrame(records)


def _feature_groups(category: pd.DataFrame, validation: pd.DataFrame,
                    metadata: dict[str, Any], category_id: str) -> tuple[dict[str, list[str]], dict[str, Any]]:
    history_features = [c for c in category if c.startswith(("history_", "season_"))]
    permitted = metadata.get("category_commodity_features", {}).get(category_id)
    candidates = permitted if permitted is not None else [c for c in category if c.startswith("commodity_")]
    coverage = {c: float(validation[c].notna().mean()) for c in candidates if c in category}
    commodities = [c for c, fraction in coverage.items() if fraction >= 0.8]
    groups = {"history_only": history_features} if history_features else {}
    if commodities and history_features:
        groups["history_plus_weekly_commodities"] = history_features + commodities
    return groups, {"commodity_feature_validation_coverage": coverage,
                    "coverage_threshold": 0.8,
                    "coverage_selection_uses_test": False,
                    "commodity_group_status": "included" if commodities else "skipped_insufficient_pretest_coverage"}


def _common_targets(predictions: list[pd.DataFrame]) -> set[str]:
    if not predictions or any(p.empty for p in predictions):
        return set()
    return set.intersection(*(set(p.target_month) for p in predictions))


def _on_targets(predictions: pd.DataFrame, targets: set[str]) -> pd.DataFrame:
    return predictions.loc[predictions.target_month.isin(targets)].copy() if not predictions.empty else predictions


def _fit_final(history: pd.DataFrame, live: pd.Series, model_id: str,
               features: list[str], config: dict[str, Any]) -> tuple[Any, float | None, pd.DataFrame]:
    train = _training_rows(history, live.forecast_cutoff)
    if model_id in BASELINES:
        value = live[BASELINES[model_id]]
        return None, float(value) if pd.notna(value) else None, train
    if len(train) < MIN_TRAIN:
        return None, None, train
    model = _make_model(model_id, config)
    model.fit(train[features], train.target_change_pct)
    value = float(model.predict(live.to_frame().T[features].astype(float))[0])
    return model, value if math.isfinite(value) else None, train


def _plot_category(category: dict[str, Any], output: Path, root: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(root / "data/.cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    records = category["test_predictions"]
    if not records:
        return
    dates = pd.to_datetime([r["target_month"] for r in records])
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(dates, [r["actual_pct"] for r in records], label="Observed category change", color="#192734", lw=2)
    axes[0].plot(dates, [r["predicted_pct"] for r in records], label="Validation-selected forecast", color="#087f8c", lw=2)
    axes[0].axhline(0, color="#b5b5b5", ls="--", label="No-change baseline")
    axes[0].set_ylabel("Monthly change (%)")
    axes[0].set_title(f"{category['category_name']}: chronological category-index test")
    axes[0].legend(fontsize=8)
    leaderboard = category["leaderboard"]
    labels = [r["model_id"] + (" + commodities" if r["feature_group"].endswith("commodities") else "") for r in leaderboard]
    axes[1].barh(labels, [r["test_mae_pp"] for r in leaderboard], color="#087f8c")
    axes[1].set_xlabel("Held-out MAE (percentage points; lower is better)")
    axes[1].tick_params(axis="y", labelsize=8)
    fig.text(0.5, 0.01, "ONS category index: not a validated forecast for an individual product, pack size or recipe.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.025, 1, 1))
    fig.savefig(output, dpi=150)
    plt.close(fig)


def run_frame_experiments(root: Path, frame: pd.DataFrame, metadata: dict[str, Any],
                          as_of: date) -> dict[str, Any]:
    """Evaluate supplied real category data; synthetic callers must mark metadata."""
    root = Path(root)
    out = root / "data/experiments/category_forecast"
    out.mkdir(parents=True, exist_ok=True)
    frame = _prepare_frame(frame)
    as_of_ts = pd.Timestamp(as_of, tz="Europe/London").tz_convert("UTC")
    summary: dict[str, Any] = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(), "scope": "UK grocery category CPI monthly change, not individual SKU unit price or shrink events",
        "target": "100 * (category_index[target_month] / category_index[previous_month] - 1)",
        "selection_basis": "Lowest pretest validation MAE on common dates; test outcomes never select the winner",
        "test_start": "2024-01-01", "selection_labels_available_by": SELECTION_CUTOFF.isoformat(),
        "minimum_training_labels": MIN_TRAIN, "thread_limit": 4,
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__,
                    "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                    "joblib": joblib.__version__},
        "source_metadata": metadata, "categories": [], "skipped": [],
        "limitations": ["Category indices cannot identify a manufacturer's shrink/price/recipe mechanism.",
                        "Historical archives may contain corrections; source availability assumptions are documented, not recovered original vintages.",
                        "No calibrated SKU probabilities or causal ingredient cost pass-through claims.",
                        "No prediction intervals emitted: independent post-selection calibration is not established."],
    }
    _write_json(out / "provenance.json", metadata)
    with threadpool_limits(limits=4):
        for category_id, category in frame.groupby("category_id", sort=True):
            category_id = str(category_id)
            history = category.loc[(~category.is_live) & category.target_change_pct.notna()
                                   & (category.label_available_date <= as_of_ts)].copy()
            validation = history.loc[(history.target_month >= VALIDATION_START)
                                     & (history.target_month < TEST_START)
                                     & (history.label_available_date <= SELECTION_CUTOFF)]
            test = history.loc[history.target_month >= TEST_START]
            live_rows = category.loc[category.is_live]
            if validation.empty or test.empty or len(live_rows) != 1:
                summary["skipped"].append({"category_id": category_id, "reason": "Need pretest labels, later test labels and exactly one live target"})
                continue
            if live_rows.iloc[0].forecast_cutoff > as_of_ts:
                summary["skipped"].append({"category_id": category_id, "reason": "Live forecast cutoff is later than the requested as-of date"})
                continue
            groups, audit = _feature_groups(category, validation, metadata, category_id)
            experiments = []
            for model_id, column in BASELINES.items():
                val = _predict_rows(history, validation, model_id, [], {})
                if not val.empty:
                    experiments.append({"model_id": model_id, "feature_group": "baseline", "features": [],
                                        "config": {"source_column": column}, "validation": val,
                                        "validation_candidates": []})
            for group, features in groups.items():
                for model_id, configurations in _model_specs().items():
                    candidates = []
                    for config in configurations:
                        predictions = _predict_rows(history, validation, model_id, features, config)
                        if not predictions.empty:
                            candidates.append({"config": config, "predictions": predictions})
                    common = _common_targets([c["predictions"] for c in candidates])
                    if len(common) < 12:
                        continue
                    for candidate in candidates:
                        candidate["metrics"] = _metrics(_on_targets(candidate["predictions"], common))
                    best = min(candidates, key=lambda c: c["metrics"]["mae_pp"])
                    experiments.append({"model_id": model_id, "feature_group": group,
                                        "features": features, "config": best["config"],
                                        "validation": best["predictions"],
                                        "validation_candidates": [{"config": c["config"], "metrics": c["metrics"]} for c in candidates]})
            common_validation = _common_targets([e["validation"] for e in experiments])
            if len(common_validation) < 12:
                summary["skipped"].append({"category_id": category_id, "reason": "Fewer than 12 common pretest validation outcomes"})
                continue
            for experiment in experiments:
                experiment["validation"] = _on_targets(experiment["validation"], common_validation)
                experiment["validation_metrics"] = _metrics(experiment["validation"])
            # Winner freezes here, before any test predictions or test metrics exist.
            winner = min(experiments, key=lambda e: e["validation_metrics"]["mae_pp"])
            for experiment in experiments:
                experiment["test"] = _predict_rows(history, test, experiment["model_id"], experiment["features"], experiment["config"])
            common_test = _common_targets([e["test"] for e in experiments])
            if not common_test:
                summary["skipped"].append({"category_id": category_id, "reason": "No common held-out predictions"})
                continue
            leaderboard = []
            live = live_rows.iloc[0]
            for experiment in experiments:
                experiment["test"] = _on_targets(experiment["test"], common_test)
                experiment["test_metrics"] = _metrics(experiment["test"])
                model, live_value, train = _fit_final(history, live, experiment["model_id"], experiment["features"], experiment["config"])
                experiment["live_value"] = live_value
                directory = out / category_id / experiment["model_id"] / experiment["feature_group"]
                directory.mkdir(parents=True, exist_ok=True)
                selected = experiment is winner
                _write_json(directory / "config.json", {
                    "model_id": experiment["model_id"], "feature_group": experiment["feature_group"],
                    "features": experiment["features"], "selected_hyperparameters": experiment["config"],
                    "hyperparameter_selection": "pretest validation MAE only", "selected_overall": selected,
                    "validation_candidates": experiment["validation_candidates"],
                    "first_test_target": "2024-01-01", "selection_cutoff": SELECTION_CUTOFF,
                    "min_train": MIN_TRAIN, "preprocessing": "imputer and scaler fit inside each chronological training fold",
                    "final_model_fit_label_available_by": live.forecast_cutoff,
                    "final_model_training_rows": len(train), "random_seed": 42, "thread_limit": 4,
                    "runtime": summary["runtime"],
                    "provenance": "../../../provenance.json", "feature_coverage_audit": audit,
                })
                _write_json(directory / "metrics.json", {"validation": experiment["validation_metrics"], "test": experiment["test_metrics"]})
                experiment["validation"].to_csv(directory / "validation_predictions.csv", index=False)
                experiment["test"].to_csv(directory / "test_predictions.csv", index=False)
                if model is not None:
                    joblib.dump({"model": model, "features": experiment["features"], "category_id": category_id,
                                 "as_of": as_of.isoformat(), "scope": summary["scope"]}, directory / "model.joblib")
                leaderboard.append({"model_id": experiment["model_id"], "feature_group": experiment["feature_group"],
                                    "selected": selected, "validation_mae_pp": experiment["validation_metrics"]["mae_pp"],
                                    "validation_n": experiment["validation_metrics"]["n"],
                                    "test_mae_pp": experiment["test_metrics"]["mae_pp"],
                                    "test_rmse_pp": experiment["test_metrics"]["rmse_pp"],
                                    "test_directional_accuracy": experiment["test_metrics"]["directional_accuracy"],
                                    "test_n": experiment["test_metrics"]["n"],
                                    "hyperparameters": experiment["config"]})
            baseline = next(e for e in experiments if e["model_id"] == "no_change")
            result = {
                "category_id": category_id, "category_name": str(category.iloc[0].category_name),
                "selected_model_id": winner["model_id"], "selected_feature_group": winner["feature_group"],
                "selection_basis": summary["selection_basis"], "selection_cutoff": SELECTION_CUTOFF.isoformat(),
                "validation_metrics": winner["validation_metrics"], "test_metrics": winner["test_metrics"],
                "baseline_metrics": baseline["test_metrics"],
                "test_mae_improvement_vs_zero_pp": baseline["test_metrics"]["mae_pp"] - winner["test_metrics"]["mae_pp"],
                "forecast": {"as_of": as_of.isoformat(), "forecast_cutoff": live.forecast_cutoff.isoformat(),
                             "target_month": live.target_month.strftime("%Y-%m-%d"),
                             "change_pct": winner["live_value"], "scope": "category_index", "interval": None},
                "leaderboard": sorted(leaderboard, key=lambda e: e["validation_mae_pp"]),
                "test_predictions": winner["test"].to_dict("records"), "feature_coverage_audit": audit,
            }
            _plot_category(result, out / category_id / "comparison.png", root)
            summary["categories"].append(result)
    summary["status"] = "ready" if summary["categories"] else "unavailable"
    _write_json(out / "summary.json", summary)
    lines = ["# Category forecast experiments", "", summary["scope"], "",
             "Models are chosen on pre-2024 validation outcomes available by 8 December 2023. Test outcomes never choose the winner.",
             "Each expanding training fold includes only labels available by that forecast's cutoff. Weekly commodity features retain documented source-availability assumptions.", "",
             "| Category | Validation-selected model | Test months | MAE pp | Zero-change MAE pp |", "|---|---|---:|---:|---:|"]
    for c in summary["categories"]:
        lines.append(f"| {c['category_name']} | {c['selected_model_id']} / {c['selected_feature_group']} | {c['test_metrics']['n']} | {c['test_metrics']['mae_pp']:.4f} | {c['baseline_metrics']['mae_pp']:.4f} |")
    lines += ["", "The forecast is a monthly category-index percentage change. It does not predict an individual brand's shelf price, price per gram, shrink mechanism or recipe change.",
              "No prediction intervals are emitted because independent post-selection calibration is not established.",
              "If a baseline wins validation, that baseline remains the selected forecast, including when another model scores better on the later test.",
              "", "Full per-model configuration, validation/test predictions, metrics and fitted learned-model artifacts are in separate model/feature-group folders.", ""]
    (out / "report.md").write_text("\n".join(lines))
    return _json_value(summary)


def run_category_experiments(root: Path, as_of: date, offline: bool = False) -> dict[str, Any]:
    from .category_data import prepare_category_data
    frame, metadata = prepare_category_data(Path(root), as_of, offline=offline)
    return run_frame_experiments(Path(root), frame, metadata, as_of)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    summary = run_category_experiments(args.root, args.as_of, args.offline)
    print(json.dumps({"status": summary["status"], "categories": len(summary["categories"]),
                      "summary": str(args.root / "data/experiments/category_forecast/summary.json")}))


if __name__ == "__main__":
    main()
