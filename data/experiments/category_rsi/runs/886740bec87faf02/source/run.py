"""Removable fixed-model RSI ablation on frozen monthly category outcomes.

This design follows previously inspected results. All comparisons are
retrospective exploratory, even though every fit uses only published labels.
No existing experiment, website data or source file is written by this runner.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(PROJECT / "src"))

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from shrinkflation.category_data import _parse_ons, _weekly_inputs
from shrinkflation.category_models import (
    _fit_final, _json_value, _metrics, _predict_rows, _prepare_frame,
    _training_rows, _write_json,
)
from rsi_features import build_rsi_features

ARMS = {
    "unchanged": "Original boosted trees + weekly inputs",
    "weekly_rsi": "Add weekly commodity RSI",
    "cpi_rsi": "Add monthly category RSI",
    "both_rsi": "Add both RSI groups",
}
WARNING = "Retrospective exploratory comparison: the 2024–2026 outcomes were already inspected before this feature experiment."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(folder: Path) -> dict:
    return {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def load_frozen(project: Path):
    original = project / "data/experiments/category_forecast"
    meta = json.loads((original / "metadata.json").read_text())
    if sha(original / "dataset.parquet") != meta["dataset_sha256"]:
        raise ValueError("Frozen original dataset checksum mismatch")
    frame = pd.read_parquet(original / "dataset.parquet")
    indices = {}
    source_hashes = {}
    for category, source in meta["sources"]["ons"].items():
        path = project / source["snapshot_path"]
        if sha(path) != source["sha256"]:
            raise ValueError(f"Frozen ONS source changed: {category}")
        indices[category], _ = _parse_ons(path)
        source_hashes[str(path.relative_to(project))] = sha(path)
    inputs, weekly_meta = _weekly_inputs(project)
    if weekly_meta["sha256"] != meta["sources"]["weekly"]["sha256"]:
        raise ValueError("Weekly input archive differs from the frozen model data")
    source_hashes[weekly_meta["path"]] = weekly_meta["sha256"]
    configs = {}
    for category in sorted(frame.category_id.unique()):
        path = original / category / "hist_gradient_boosting/history_plus_weekly_commodities/config.json"
        configs[category] = json.loads(path.read_text())
    return original, frame, meta, indices, inputs, source_hashes, configs


def make_manifest(original, meta, source_hashes, configs, groups, frozen_hashes):
    source_paths = [HERE / "run.py", HERE / "rsi_features.py", HERE / "run.sh"]
    helper_paths = [PROJECT / "src/shrinkflation" / name for name in ["category_models.py", "category_data.py", "common.py"]]
    code = {str(p.relative_to(PROJECT)): sha(p) for p in source_paths + helper_paths}
    manifest = {
        "schema_version": 1, "as_of": meta["as_of"], "warning": WARNING,
        "scope": "Monthly UK category CPI changes; not product-level prices or shrinkflation probabilities",
        "selection": "No hyperparameter or arm selection on new scores; four predeclared fixed-model comparisons per category",
        "baseline": "Exact saved history_plus_weekly_commodities HistGradientBoostingRegressor configuration and feature order",
        "estimator_defaults": {"learning_rate": 0.05, "early_stopping": False, "random_state": 42},
        "preprocessing": "Original fold-local median imputation, keep_empty_features=True; no rows dropped for missing RSI",
        "feature_policy": {
            "weekly_periods": 14, "monthly_periods": 6,
            "smoothing": "Initial simple average of n gains/losses followed by Wilder recursion alpha=1/n on raw level differences",
            "flat": 50, "only_gains": 100, "only_losses": 0,
            "missing_periods": "Break/reset the chain; no filling or bridging calendar gaps",
            "weekly_lag": "Three calendar months before each actual issue date; buffers and staleness reapplied at that earlier issue",
            "availability": "Original 7/14-day weekly buffers and 35-day staleness; CPI ends at latest_known_cpi_month",
        },
        "arms": ARMS, "feature_groups": groups,
        "configs": {c: {"features": v["features"], "hyperparameters": v["selected_hyperparameters"]} for c, v in configs.items()},
        "evaluation_dates": "Exactly the saved original validation34 and test33 target months per category",
        "reproduction_tolerance": 1e-10,
        "original_experiment": str(original.relative_to(PROJECT)),
        "original_file_hashes": frozen_hashes, "input_hashes": source_hashes, "code_hashes": code,
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__, "joblib": joblib.__version__},
    }
    run_id = hashlib.sha256(json.dumps(_json_value(manifest), sort_keys=True).encode()).hexdigest()[:16]
    manifest["run_id"] = run_id
    output = HERE / "runs" / run_id
    output.mkdir(parents=True, exist_ok=True)
    path = output / "manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != _json_value(manifest):
            raise ValueError("A frozen run manifest cannot be changed")
    else:
        _write_json(path, manifest)
    sources = output / "source"
    sources.mkdir(exist_ok=True)
    for p in source_paths + helper_paths:
        shutil.copy2(p, sources / p.name)
    return output, manifest


def compare_reference(predicted: pd.DataFrame, original_path: Path) -> dict:
    saved = pd.read_csv(original_path).sort_values("target_month").reset_index(drop=True)
    actual = predicted.sort_values("target_month").reset_index(drop=True)
    if saved.target_month.tolist() != actual.target_month.tolist():
        raise AssertionError(f"Baseline target dates changed: {original_path}")
    for column in ["actual_pct", "predicted_pct", "baseline_pct", "train_n"]:
        np.testing.assert_allclose(actual[column].astype(float), saved[column].astype(float), atol=1e-10, rtol=0, err_msg=f"Baseline reproduction failed: {column}")
    for column in ["forecast_cutoff", "label_available_date", "max_train_label_available_date", "max_train_target_month"]:
        if not (pd.to_datetime(actual[column], utc=True).to_numpy() == pd.to_datetime(saved[column], utc=True).to_numpy()).all():
            raise AssertionError(f"Baseline audit dates changed: {column}")
    return {"matched": True, "n": len(actual), "max_absolute_prediction_difference": float(np.max(np.abs(actual.predicted_pct - saved.predicted_pct)))}


def paired_changes(base: pd.DataFrame, variant: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    paired = base[["target_month", "actual_pct", "predicted_pct"]].merge(
        variant[["target_month", "predicted_pct"]], on="target_month", suffixes=("_baseline", "_rsi"), validate="one_to_one")
    paired["baseline_absolute_error_pp"] = (paired.actual_pct - paired.predicted_pct_baseline).abs()
    paired["rsi_absolute_error_pp"] = (paired.actual_pct - paired.predicted_pct_rsi).abs()
    paired["error_reduction_pp"] = paired.baseline_absolute_error_pp - paired.rsi_absolute_error_pp
    delta = paired.error_reduction_pp
    return paired, {"n": len(paired), "mean_error_reduction_pp": float(delta.mean()),
                    "median_error_reduction_pp": float(delta.median()),
                    "months_improved": int((delta > 1e-10).sum()), "months_worsened": int((delta < -1e-10).sum()),
                    "months_tied": int((delta.abs() <= 1e-10).sum())}


def plots(result: dict, output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [2, 1]})
    for arm, color in zip(ARMS, ["#334155", "#108c8a", "#8a6cac", "#df6040"]):
        records = result["arms"][arm]["test_predictions"]
        dates = pd.to_datetime([p["target_month"] for p in records])
        axes[0].plot(dates, [p["predicted_pct"] for p in records], color=color, label=ARMS[arm], lw=1.5)
    axes[0].plot(dates, [p["actual_pct"] for p in records], color="#222", label="Observed change", lw=2, linestyle="--")
    axes[0].set(title=f"{result['category_name']}: fixed boosted trees, RSI feature experiment", ylabel="Monthly category change (%)")
    axes[0].legend(fontsize=8, ncol=2)
    labels = [ARMS[a] for a in ARMS]
    axes[1].barh(labels, [result["arms"][a]["test_metrics"]["mae_pp"] for a in ARMS], color=["#334155", "#108c8a", "#8a6cac", "#df6040"])
    axes[1].axvline(result["no_change_metrics"]["mae_pp"], color="#555", linestyle="--", label="No change")
    axes[1].set_xlabel("MAE in percentage points; lower is better")
    axes[1].legend(fontsize=8)
    fig.text(.5, .012, "Exploratory: these years were already examined. Same 33 months; settings fixed; no RSI arm deployed.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .035, 1, 1))
    fig.savefig(output, dpi=150)
    plt.close(fig)


def report(summary: dict) -> str:
    lines = ["# Fixed boosted-tree RSI experiment", "", WARNING, "", summary["scope"], "",
             "All new files stay inside `data/experiments/category_rsi/`. Delete that folder to remove this experiment. The website does not read it.", "",
             "Each category keeps its original saved boosted-tree configuration and original history-plus-weekly inputs. Only RSI inputs change; no retuning, row dropping or promotion of a test winner.", "",
             "| Category | Arm | Validation MAE pp | Later 33-month MAE pp | Reduction vs identical tree without RSI |", "|---|---|---:|---:|---:|"]
    for c in summary["categories"]:
        for arm, a in c["arms"].items():
            lines.append(f"| {c['category_name']} | {ARMS[arm]} | {a['validation_metrics']['mae_pp']:.4f} | {a['test_metrics']['mae_pp']:.4f} | {a['error_reduction_vs_unchanged_pct']:+.2f}% |")
    lines += ["", "## Context", ""]
    for c in summary["categories"]:
        lines.append(f"- {c['category_name']}: currently displayed original model MAE {c['original_deployed_metrics']['mae_pp']:.4f} pp; no-change MAE {c['no_change_metrics']['mae_pp']:.4f} pp. The crisps original winner is Ridge, so an RSI gain over a boosted-tree control is not automatically a gain over the displayed model.")
    lines += ["", "## How this was checked", "",
              "The no-RSI model is refitted and must reproduce every saved original validation/test prediction within 1e-10. Every fit retains original publication-aware training rows and fold-local imputation. RSI gaps stay missing and do not remove target months.", "",
              "Weekly Wilder RSI uses 14 level differences, an initial arithmetic-mean seed and alpha=1/14 recursion. Each applicable benchmark is computed at the current issue and three calendar months earlier, reapplying publication buffers and staleness. Category-level RSI uses six monthly differences and ends at the latest published CPI observation. Flat sequences use 50. Missing periods reset the chain; no filling.", "",
              "The manifest is frozen before this run computes new scores. This does not turn previously seen outcomes into a new holdout. Forecasts remain category-index changes rather than specific product prices, pack sizes or shrink probabilities. Current-archive and availability-buffer assumptions remain.", "",
              "Each arm has saved configuration, validation/test CSVs, paired monthly error changes, yearly metrics and a fitted live model. There is no newly selected live winner or calibrated prediction interval.", ""]
    return "\n".join(lines)


def run() -> dict:
    original, raw, meta, indices, inputs, hashes, configs = load_frozen(PROJECT)
    frozen = tree_hashes(original)
    enhanced, audit, groups = build_rsi_features(raw, indices, inputs)
    pd.testing.assert_frame_equal(raw, enhanced[raw.columns], check_exact=True)
    output, manifest = make_manifest(original, meta, hashes, configs, groups, frozen)
    enhanced.to_parquet(output / "dataset.parquet", index=False)
    audit.to_csv(output / "feature_availability_audit.csv", index=False)
    frame = _prepare_frame(enhanced)
    original_summary = json.loads((original / "summary.json").read_text())
    summary = {"schema_version": 1, "run_id": manifest["run_id"], "generated_at": datetime.now(timezone.utc).isoformat(),
               "as_of": meta["as_of"], "status": "running", "warning": WARNING, "scope": manifest["scope"],
               "model_settings_fixed": True, "website_changed": False, "selected_arm": None,
               "manifest": str((output / "manifest.json").relative_to(HERE)), "categories": []}
    with threadpool_limits(limits=4):
        for category_id, category in frame.groupby("category_id", sort=True):
            print(f"[{category_id}] frozen HGB settings; four RSI arms", flush=True)
            reference = original / category_id / "hist_gradient_boosting/history_plus_weekly_commodities"
            history = category.loc[~category.is_live].copy()
            live = category.loc[category.is_live].iloc[0]
            targets = {}
            for split in ["validation", "test"]:
                dates = pd.read_csv(reference / f"{split}_predictions.csv").target_month
                targets[split] = history.loc[history.target_month.isin(pd.to_datetime(dates, utc=True))]
                if len(targets[split]) != len(dates):
                    raise ValueError("Evaluation target coverage changed")
            current = next(c for c in original_summary["categories"] if c["category_id"] == category_id)
            result = {"category_id": category_id, "category_name": current["category_name"],
                      "original_deployed_model": current["selected_model_id"], "original_deployed_metrics": current["test_metrics"],
                      "no_change_metrics": current["baseline_metrics"], "baseline_reproduction": {}, "arms": {}}
            config = configs[category_id]["selected_hyperparameters"]
            base_features = configs[category_id]["features"]
            arm_features = {"unchanged": base_features,
                            "weekly_rsi": base_features + groups[category_id]["rsi_commodities"],
                            "cpi_rsi": base_features + groups[category_id]["rsi_cpi"],
                            "both_rsi": base_features + groups[category_id]["rsi_only"]}
            base_test = None
            for arm, features in arm_features.items():
                directory = output / category_id / arm
                directory.mkdir(parents=True, exist_ok=True)
                predictions = {split: _predict_rows(history, target, "hist_gradient_boosting", features, config) for split, target in targets.items()}
                if arm == "unchanged":
                    for split, prediction in predictions.items():
                        result["baseline_reproduction"][split] = compare_reference(prediction, reference / f"{split}_predictions.csv")
                    base_test = predictions["test"]
                else:
                    for split, prediction in predictions.items():
                        expected = targets[split].target_month.dt.strftime("%Y-%m-%d").tolist()
                        if prediction.target_month.tolist() != expected:
                            raise AssertionError("Missing RSI cannot alter evaluation months")
                model, live_value, train = _fit_final(history, live, "hist_gradient_boosting", features, config)
                paired, paired_metrics = paired_changes(base_test, predictions["test"])
                paired.to_csv(directory / "paired_test_errors.csv", index=False)
                metrics = {split + "_metrics": _metrics(p) for split, p in predictions.items()}
                base_error = result["arms"]["unchanged"]["test_metrics"]["mae_pp"] if arm != "unchanged" else metrics["test_metrics"]["mae_pp"]
                arm_result = {"features": features, **metrics, "paired_test_comparison": paired_metrics,
                              "error_reduction_vs_unchanged_pct": 100 * (base_error - metrics["test_metrics"]["mae_pp"]) / base_error,
                              "yearly_test_metrics": {str(year): _metrics(p) for year, p in predictions["test"].groupby(predictions["test"].target_month.str[:4])},
                              "feature_coverage": {split: {f: float(t[f].notna().mean()) for f in features if f not in base_features} for split, t in targets.items()},
                              "forecast": {"as_of": meta["as_of"], "target_month": live.target_month.strftime("%Y-%m-%d"), "change_pct": live_value,
                                           "train_n": len(train), "max_train_label_available_date": train.label_available_date.max().isoformat(), "selected_for_website": False},
                              "test_predictions": predictions["test"].to_dict("records")}
                _write_json(directory / "config.json", {"arm": arm, "features": features, "fixed_hyperparameters": config, "manifest": "../../manifest.json"})
                _write_json(directory / "metrics.json", {k: v for k, v in arm_result.items() if k != "test_predictions"})
                for split, prediction in predictions.items():
                    prediction.to_csv(directory / f"{split}_predictions.csv", index=False)
                joblib.dump({"model": model, "features": features, "category_id": category_id, "as_of": meta["as_of"], "warning": WARNING}, directory / "model.joblib")
                result["arms"][arm] = arm_result
                print(f"[{category_id}] {arm}: MAE {metrics['test_metrics']['mae_pp']:.4f} pp ({arm_result['error_reduction_vs_unchanged_pct']:+.2f}% reduction)", flush=True)
            summary["categories"].append(result)
            plots(result, output / f"{category_id}-comparison.png")
    after = tree_hashes(original)
    if after != frozen:
        raise AssertionError("Original experiment changed during RSI run")
    summary.update(status="ready", original_files_unchanged=len(frozen))
    _write_json(output / "summary.json", summary)
    _write_json(HERE / "summary.json", summary)
    text = report(summary)
    (output / "report.md").write_text(text)
    (HERE / "report.md").write_text(text)
    print(json.dumps({"status": summary["status"], "run_id": manifest["run_id"], "original_files_unchanged": len(frozen)}), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    run()
