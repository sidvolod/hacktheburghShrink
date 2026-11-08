"""Bounded, retrospective nested monthly tuning of UK category CPI forecasts.

The 2024+ period was already examined before this experiment was designed. It
is an exploratory replay, NOT a fresh untouched holdout or SKU accuracy claim.
All inner forecasts and outer selections nevertheless obey publication dates.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import warnings
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, HuberRegressor, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .category_models import _json_value, _metrics, _prepare_frame, _write_json

OUTER_START = pd.Timestamp("2024-01-01", tz="UTC")
OOF_START = pd.Timestamp("2020-01-01", tz="UTC")
MIN_TRAIN = 24
INNER_MONTHS = 36
MIN_INNER = 12
MAX_CANDIDATES = 60


def _catalog() -> list[dict[str, Any]]:
    """Predeclared catalog; changing it creates a new hash-addressed run."""
    specs: list[dict[str, Any]] = []
    def add(candidate_id, family, group="baseline", **kwargs):
        specs.append({"candidate_id": candidate_id, "model_id": family, "feature_group": group,
                      "params": {}, "training_window_months": None, "residual_baseline": None, **kwargs})
    for name, column in [("zero", "baseline_zero"), ("recent", "baseline_recent"),
                         ("trailing_mean", "baseline_trailing_mean"), ("seasonal", "baseline_seasonal"),
                         ("seasonal_mean3", "baseline_seasonal_mean3"),
                         ("seasonal_median3", "baseline_seasonal_median3"),
                         ("seasonal_mean5", "baseline_seasonal_mean5")]:
        add("baseline_" + name, "baseline_" + name, kind="baseline", column=column)
    add("baseline_seasonal_smoothed", "baseline_seasonal_smoothed", kind="baseline_blend",
        columns=["baseline_seasonal_mean3", "baseline_trailing_mean"], weights=[0.5, 0.5])
    groups = ("compactseasonal", "seasonal_history", "seasonal_history_commodities")
    for group in groups:
        for alpha in (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0):
            add(f"ridge_{group}_a{alpha:g}", "ridge", group, kind="learned", params={"alpha": alpha})
    for group in groups[1:]:
        for alpha in (1.0, 10.0, 100.0):
            add(f"residual_ridge_{group}_a{alpha:g}", "residual_ridge", group, kind="learned",
                params={"alpha": alpha}, residual_baseline="baseline_seasonal_mean3")
        for window in (36, 60):
            for alpha in (10.0, 100.0):
                add(f"ridge_{group}_a{alpha:g}_w{window}", "ridge", group, kind="learned",
                    params={"alpha": alpha}, training_window_months=window)
        for loss in ("squared_error", "huber", "absolute_error"):
            add(f"gbr_{group}_{loss}", "gradient_boosting", group, kind="learned",
                params={"loss": loss, "n_estimators": 80, "learning_rate": 0.04,
                        "max_depth": 2, "min_samples_leaf": 8})
        for leaves, l2 in ((5, 10.0), (7, 20.0)):
            add(f"hgb_{group}_l{leaves}", "hist_gradient_boosting", group, kind="learned",
                params={"max_iter": 80, "learning_rate": 0.05, "max_leaf_nodes": leaves,
                        "min_samples_leaf": 10, "l2_regularization": l2})
        add(f"gbr_{group}_absolute_w60", "gradient_boosting", group, kind="learned",
            params={"loss": "absolute_error", "n_estimators": 80, "learning_rate": 0.04,
                    "max_depth": 2, "min_samples_leaf": 8}, training_window_months=60)
    for alpha, l1 in ((0.05, 0.2), (0.2, 0.8)):
        add(f"elastic_net_a{alpha:g}_l{l1:g}", "elastic_net", "seasonal_history", kind="learned",
            params={"alpha": alpha, "l1_ratio": l1, "max_iter": 3000, "tol": 0.0001})
    add("huber_history", "huber", "seasonal_history", kind="learned",
        params={"epsilon": 1.35, "alpha": 0.1, "max_iter": 300, "tol": 0.0001})
    for group in groups[1:]:
        for toward, column in (("zero", "baseline_zero"), ("seasonal", "baseline_seasonal_mean3")):
            add(f"ensemble_{group}_toward_{toward}", "ensemble", group, kind="ensemble",
                base_candidate=f"ridge_{group}_a10", baseline_column=column, learned_weight=0.5)
    if len(specs) > MAX_CANDIDATES:
        raise ValueError("Catalog exceeds the frozen candidate limit")
    return specs


def _make_estimator(spec: dict[str, Any]) -> Pipeline:
    family, params = spec["model_id"], spec["params"]
    steps = [("imputer", SimpleImputer(strategy="median", keep_empty_features=True))]
    if family in ("ridge", "residual_ridge", "elastic_net", "huber"):
        steps.append(("scaler", StandardScaler()))
    if family in ("ridge", "residual_ridge"):
        estimator = Ridge(**params)
    elif family == "elastic_net":
        estimator = ElasticNet(random_state=42, **params)
    elif family == "huber":
        estimator = HuberRegressor(**params)
    elif family == "gradient_boosting":
        estimator = GradientBoostingRegressor(random_state=42, **params)
    elif family == "hist_gradient_boosting":
        estimator = HistGradientBoostingRegressor(early_stopping=False, random_state=42, **params)
    else:
        raise ValueError(f"Unknown estimator: {family}")
    return Pipeline(steps + [("model", estimator)])


def _train_rows(history: pd.DataFrame, cutoff: pd.Timestamp, window: int | None) -> pd.DataFrame:
    train = history[(history.label_available_date <= cutoff)
                    & (history.forecast_cutoff < cutoff) & history.target_change_pct.notna()]
    if window and not train.empty:
        start = train.target_month.max() - pd.DateOffset(months=window - 1)
        train = train[train.target_month >= start]
    return train


def _safe_features(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    return frame[features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _fit_predict(history: pd.DataFrame, row: pd.Series, spec: dict[str, Any],
                 features: list[str]) -> tuple[float | None, Any, dict[str, Any]]:
    train = _train_rows(history, row.forecast_cutoff, spec.get("training_window_months"))
    audit = {"train_n": len(train), "max_train_label_available_date": None if train.empty else train.label_available_date.max().isoformat(),
             "max_train_target_month": None if train.empty else train.target_month.max().strftime("%Y-%m-%d"),
             "min_train_target_month": None if train.empty else train.target_month.min().strftime("%Y-%m-%d"), "convergence_warnings": 0}
    kind = spec["kind"]
    if kind == "baseline":
        value = row.get(spec["column"], np.nan)
        return (float(value) if pd.notna(value) else None), None, audit
    if kind == "baseline_blend":
        values = [row.get(c, np.nan) for c in spec["columns"]]
        value = np.dot(values, spec["weights"]) if all(pd.notna(v) for v in values) else np.nan
        return (float(value) if pd.notna(value) else None), None, audit
    residual = spec.get("residual_baseline")
    if residual:
        train = train[train[residual].notna()]
        audit["train_n"] = len(train)
        if pd.isna(row.get(residual, np.nan)):
            return None, None, audit
    if len(train) < MIN_TRAIN or not features:
        return None, None, audit
    target = train.target_change_pct - train[residual] if residual else train.target_change_pct
    estimator = _make_estimator(spec)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(_safe_features(train, features), target)
        value = float(estimator.predict(_safe_features(row.to_frame().T, features))[0])
    audit["convergence_warnings"] = sum(issubclass(w.category, ConvergenceWarning) for w in caught)
    if residual:
        value += float(row[residual])
    return (value if math.isfinite(value) else None), estimator, audit


def _record(row: pd.Series, value: float, audit: dict[str, Any]) -> dict[str, Any]:
    return {"target_month": row.target_month.strftime("%Y-%m-%d"), "forecast_cutoff": row.forecast_cutoff.isoformat(),
            "label_available_date": row.label_available_date.isoformat(), "actual_pct": float(row.target_change_pct),
            "predicted_pct": float(value), "baseline_pct": float(row.baseline_zero), **audit}


def _candidate_oof(history: pd.DataFrame, targets: pd.DataFrame, spec: dict[str, Any],
                   features: list[str]) -> pd.DataFrame:
    records = []
    for _, row in targets.iterrows():
        value, _, audit = _fit_predict(history, row, spec, features)
        if value is not None:
            records.append(_record(row, value, audit))
    return pd.DataFrame(records)


def _inner_scores(caches: dict[str, pd.DataFrame], cutoff: pd.Timestamp) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select using only previous OOF errors whose outcomes were known then."""
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    eligible: dict[str, pd.DataFrame] = {}
    for candidate, predictions in caches.items():
        if predictions.empty:
            continue
        labels = pd.to_datetime(predictions.label_available_date, utc=True)
        issues = pd.to_datetime(predictions.forecast_cutoff, utc=True)
        targets = pd.to_datetime(predictions.target_month, utc=True)
        known = predictions[(labels <= cutoff) & (issues < cutoff)]
        if known.empty:
            continue
        latest_target = pd.to_datetime(known.target_month, utc=True).max()
        window_start = latest_target - pd.DateOffset(months=INNER_MONTHS - 1)
        known = known[pd.to_datetime(known.target_month, utc=True) >= window_start]
        if len(known) >= MIN_INNER:
            eligible[candidate] = known
    # Evaluate every eligible model on identical months; no easy-period ranking.
    common = set.intersection(*(set(p.target_month) for p in eligible.values())) if eligible else set()
    if len(common) < MIN_INNER:
        return [], {"n": len(common), "max_label_available_date": None, "window_months": INNER_MONTHS}
    scores = []
    all_dates = []
    for candidate, predictions in eligible.items():
        shared = predictions[predictions.target_month.isin(common)]
        metrics = _metrics(shared)
        max_available = pd.to_datetime(shared.label_available_date, utc=True).max()
        all_dates.append(max_available)
        scores.append({"candidate_id": candidate, "mae_pp": metrics["mae_pp"], "rmse_pp": metrics["rmse_pp"],
                       "n": metrics["n"], "max_label_available_date": max_available.isoformat()})
    scores.sort(key=lambda s: (s["mae_pp"], s["candidate_id"]))
    return scores, {"n": len(common), "max_label_available_date": max(all_dates).isoformat(),
                    "window_months": INNER_MONTHS, "min_target_month": min(common), "max_target_month": max(common)}


def _select_outer(caches: dict[str, pd.DataFrame], targets: pd.DataFrame,
                  allowed: set[str] | None = None) -> pd.DataFrame:
    records = []
    selected_caches = {k: p for k, p in caches.items() if allowed is None or k in allowed}
    for _, row in targets.iterrows():
        scores, audit = _inner_scores(selected_caches, row.forecast_cutoff)
        if not scores:
            continue
        selected = scores[0]["candidate_id"]
        predictions = selected_caches[selected]
        prediction = predictions[predictions.target_month == row.target_month.strftime("%Y-%m-%d")]
        if prediction.empty:
            continue
        record = prediction.iloc[0].to_dict()
        record.update({"selected_candidate_id": selected, "inner_validation_mae_pp": scores[0]["mae_pp"],
                       "inner_validation_n": audit["n"], "selection_max_label_available_date": audit["max_label_available_date"],
                       "inner_min_target_month": audit["min_target_month"], "inner_max_target_month": audit["max_target_month"]})
        records.append(record)
    return pd.DataFrame(records)


def _original_reference(root: Path, category_id: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = root / "data/experiments/category_forecast/summary.json"
    if not path.exists():
        return pd.DataFrame(), {"status": "missing_original_run"}
    data = json.loads(path.read_text())
    entry = next((c for c in data.get("categories", []) if c["category_id"] == category_id), None)
    if not entry:
        return pd.DataFrame(), {"status": "missing_original_category"}
    records = pd.DataFrame(entry["test_predictions"])
    return records, {"status": "original_frozen_run_read_only", "path": str(path),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "model_id": entry["selected_model_id"], "feature_group": entry["selected_feature_group"]}


def _feature_map(metadata: dict[str, Any], category_id: str) -> dict[str, list[str]]:
    groups = metadata["feature_groups"]
    if category_id in groups:
        groups = groups[category_id]
    return {k: list(v) for k, v in groups.items()}


def _freeze_manifest(root: Path, frame: pd.DataFrame, metadata: dict[str, Any],
                     catalog: list[dict[str, Any]], as_of: date) -> tuple[Path, dict[str, Any]]:
    data_hash = hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()
    manifest = {
        "schema_version": 1, "as_of": as_of.isoformat(), "data_sha256": data_hash,
        "model_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "data_code_sha256": hashlib.sha256((root / "src/shrinkflation/category_tuning_data.py").read_bytes()).hexdigest()
        if (root / "src/shrinkflation/category_tuning_data.py").exists() else None,
        "scope": "retrospective_exploratory_category_CPI_forecast",
        "warning": "2024+ outcomes were examined before this design; this is not a fresh untouched test.",
        "policy": {"outer_start": "2024-01-01", "oof_start": "2020-01-01", "minimum_training_rows": MIN_TRAIN,
                   "inner_window_months": INNER_MONTHS, "minimum_inner_outcomes": MIN_INNER,
                   "inner_comparison": "common monthly outcomes with label_available_date <= outer forecast_cutoff",
                   "selection_objective": "MAE; deterministic candidate-id tie break", "candidate_limit": MAX_CANDIDATES,
                   "thread_limit": 4, "imputer_scaler": "fit within every inner chronological training fold",
                   "test_driven_search_expansion": False, "prediction_intervals": "not emitted; no independent calibration"},
        "candidates": catalog, "feature_groups": metadata["feature_groups"],
        # Enhancement build time is not a source change; frozen retrieval times
        # and source hashes remain. Identical reruns can reuse cached forecasts.
        "source_metadata": {key: value for key, value in metadata.items() if key != "generated_at"},
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "scikit_learn": sklearn.__version__, "joblib": joblib.__version__},
    }
    digest = hashlib.sha256(json.dumps(_json_value(manifest), sort_keys=True).encode()).hexdigest()
    manifest["run_id"] = digest[:16]
    directory = root / "data/experiments/category_tuning" / manifest["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "search_manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != _json_value(manifest):
            raise ValueError("A frozen manifest must never be changed in place")
    else:
        _write_json(path, manifest)
    return directory, manifest


def _plot(category: dict[str, Any], path: Path, root: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(root / "data/.cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    predictions = category["test_predictions"]
    if not predictions:
        return
    dates = pd.to_datetime([r["target_month"] for r in predictions])
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(dates, [r["actual_pct"] for r in predictions], color="#202d35", label="Observed monthly category change")
    ax.plot(dates, [r["predicted_pct"] for r in predictions], color="#098c88", label="Past-only nested selector")
    reference = category.get("original_predictions", [])
    if reference:
        ax.plot(pd.to_datetime([r["target_month"] for r in reference]), [r["predicted_pct"] for r in reference],
                color="#c58a29", alpha=0.7, label="Original frozen approach")
    ax.axhline(0, color="#aaaaaa", ls="--", lw=1)
    ax.set_ylabel("Monthly change (%)")
    ax.set_title(category["category_name"] + ": retrospective exploratory replay")
    ax.legend(fontsize=8)
    fig.text(0.5, 0.01, "Previously examined period; category index, not a validated individual-product forecast.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_tuning_frame(root: Path, frame: pd.DataFrame, metadata: dict[str, Any],
                      as_of: date, catalog: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = Path(root)
    frame = _prepare_frame(frame)
    catalog = _catalog() if catalog is None else catalog
    if len(catalog) > MAX_CANDIDATES:
        raise ValueError("Candidate limit exceeded")
    directory, manifest = _freeze_manifest(root, frame, metadata, catalog, as_of)
    as_of_ts = pd.Timestamp(as_of, tz="Europe/London").tz_convert("UTC")
    summary = {"schema_version": 1, "run_id": manifest["run_id"], "as_of": as_of.isoformat(),
               "generated_at": datetime.now(timezone.utc).isoformat(), "scope": manifest["scope"],
               "evaluation_status": "retrospective_exploratory",
               "evaluation_label": "Previously examined 2024+ period; exploratory past-only nested replay, not fresh holdout accuracy",
               "warning": manifest["warning"], "selection_basis": "Nested past-only rolling36-month OOF MAE; all baselines eligible",
               "search_manifest": str(directory / "search_manifest.json"), "candidate_count": len(catalog),
               "categories": [], "skipped": [], "prediction_intervals": None}
    with threadpool_limits(limits=4):
        for category_id, category in frame.groupby("category_id", sort=True):
            category_id = str(category_id)
            print(f"[{category_id}] frozen {len(catalog)} candidates; computing cached chronological forecasts", flush=True)
            features_by_group = _feature_map(metadata, category_id)
            history = category[(~category.is_live) & category.target_change_pct.notna()
                               & (category.label_available_date <= as_of_ts)].copy()
            targets = history[history.target_month >= OOF_START]
            outer = history[history.target_month >= OUTER_START]
            live_rows = category[category.is_live]
            if len(live_rows) != 1 or live_rows.iloc[0].forecast_cutoff > as_of_ts:
                summary["skipped"].append({"category_id": category_id, "reason": "Need one live row with a past/current issue cutoff"})
                continue
            live = live_rows.iloc[0]
            caches, live_values, specs_by_id = {}, {}, {}
            category_dir = directory / category_id
            for i, spec in enumerate(catalog):
                candidate_id = spec["candidate_id"]
                group = spec["feature_group"]
                features = features_by_group.get(group, [])
                if spec["kind"] == "learned" and not features:
                    continue
                model_dir = category_dir / spec["model_id"] / candidate_id
                model_dir.mkdir(parents=True, exist_ok=True)
                cache_path = model_dir / "oof_predictions.csv"
                if cache_path.exists():
                    try:
                        predictions = pd.read_csv(cache_path)
                    except pd.errors.EmptyDataError:
                        predictions = pd.DataFrame()
                elif spec["kind"] == "ensemble":
                    base = caches.get(spec["base_candidate"], pd.DataFrame())
                    if base.empty:
                        predictions = pd.DataFrame()
                    else:
                        predictions = base.copy()
                        lookup = category.set_index(category.target_month.dt.strftime("%Y-%m-%d"))[spec["baseline_column"]]
                        baseline = predictions.target_month.map(lookup)
                        predictions["predicted_pct"] = (spec["learned_weight"] * predictions.predicted_pct
                                                         + (1 - spec["learned_weight"]) * baseline)
                        predictions = predictions[predictions.predicted_pct.notna()]
                    predictions.to_csv(cache_path, index=False)
                else:
                    predictions = _candidate_oof(history, targets, spec, features)
                    predictions.to_csv(cache_path, index=False)
                if predictions.empty:
                    continue
                caches[candidate_id], specs_by_id[candidate_id] = predictions, spec
                if spec["kind"] == "ensemble":
                    base_value = live_values.get(spec["base_candidate"])
                    baseline = live.get(spec["baseline_column"], np.nan)
                    live_value = (spec["learned_weight"] * base_value + (1 - spec["learned_weight"]) * float(baseline)
                                  if base_value is not None and pd.notna(baseline) else None)
                    estimator, audit = None, {"derived_from": spec["base_candidate"]}
                else:
                    live_value, estimator, audit = _fit_predict(history, live, spec, features)
                live_values[candidate_id] = live_value
                _write_json(model_dir / "config.json", {**spec, "features": features, "run_id": manifest["run_id"],
                                                       "live_fit_audit": audit, "manifest": "../../../search_manifest.json"})
                _write_json(model_dir / "live_forecast.json", {"as_of": as_of.isoformat(), "target_month": live.target_month.strftime("%Y-%m-%d"),
                                                               "change_pct": live_value, "scope": "category_index"})
                if estimator is not None:
                    joblib.dump({"pipeline": estimator, "features": features, "residual_baseline": spec.get("residual_baseline"),
                                 "candidate_id": candidate_id, "as_of": as_of.isoformat(), "run_id": manifest["run_id"]}, model_dir / "model.joblib")
                if (i + 1) % 10 == 0:
                    print(f"[{category_id}] {i + 1}/{len(catalog)} candidates cached", flush=True)
            selector = _select_outer(caches, outer)
            if selector.empty:
                summary["skipped"].append({"category_id": category_id, "reason": "No outer forecasts with sufficient prior OOF outcomes"})
                continue
            selector["candidate_id"] = selector.selected_candidate_id
            selector["model_id"] = selector.candidate_id.map(lambda key: specs_by_id[key]["model_id"])
            selector["feature_group"] = selector.candidate_id.map(lambda key: specs_by_id[key]["feature_group"])
            reference, reference_info = _original_reference(root, category_id)
            common = set(selector.target_month)
            if not reference.empty:
                common &= set(reference.target_month)
            # All candidate and selector comparisons use this identical outer panel.
            comparable_ids = [k for k, p in caches.items() if common <= set(p.target_month)]
            selector = selector[selector.target_month.isin(common)].copy()
            reference = reference[reference.target_month.isin(common)].copy() if not reference.empty else reference
            leaderboard = []
            for candidate_id, predictions in caches.items():
                evaluated = predictions[predictions.target_month.isin(common)]
                if set(evaluated.target_month) != common:
                    continue
                metrics = _metrics(evaluated)
                spec = specs_by_id[candidate_id]
                leaderboard.append({"candidate_id": candidate_id, "model_id": spec["model_id"],
                                    "feature_group": spec["feature_group"], "test_mae_pp": metrics["mae_pp"],
                                    "test_rmse_pp": metrics["rmse_pp"], "test_n": metrics["n"],
                                    "test_directional_accuracy": metrics["directional_accuracy"],
                                    "comparison_status": "exploratory_not_selection_metric"})
                model_dir = category_dir / spec["model_id"] / candidate_id
                _write_json(model_dir / "metrics.json", {"outer_exploratory": metrics,
                                                         "warning": manifest["warning"]})
                evaluated.to_csv(model_dir / "outer_predictions.csv", index=False)
            # Family/group selectors also choose configurations using past errors only.
            selector_variants = []
            for family in sorted({s["model_id"] for s in specs_by_id.values() if s["kind"] == "learned"}):
                allowed = {k for k, s in specs_by_id.items() if s["model_id"] == family}
                predictions = _select_outer(caches, outer, allowed)
                if not predictions.empty:
                    selector_variants.append(("family_" + family, predictions))
            for group in ("compactseasonal", "seasonal_history", "seasonal_history_commodities"):
                allowed = {k for k, s in specs_by_id.items() if s["feature_group"] in (group, "baseline")}
                predictions = _select_outer(caches, outer, allowed)
                if not predictions.empty:
                    selector_variants.append(("group_" + group, predictions))
            for variant_id, predictions in selector_variants:
                predictions = predictions[predictions.target_month.isin(common)]
                if set(predictions.target_month) != common:
                    continue
                metrics = _metrics(predictions)
                predictions["candidate_id"] = predictions.selected_candidate_id
                predictions["model_id"] = predictions.candidate_id.map(lambda key: specs_by_id[key]["model_id"])
                predictions["feature_group"] = predictions.candidate_id.map(lambda key: specs_by_id[key]["feature_group"])
                variant_dir = category_dir / "nested_selectors" / variant_id
                variant_dir.mkdir(parents=True, exist_ok=True)
                predictions.to_csv(variant_dir / "outer_predictions.csv", index=False)
                _write_json(variant_dir / "metrics.json", metrics)
                leaderboard.append({"candidate_id": variant_id, "model_id": variant_id, "feature_group": "nested_selector",
                                    "test_mae_pp": metrics["mae_pp"], "test_rmse_pp": metrics["rmse_pp"],
                                    "test_n": metrics["n"], "test_directional_accuracy": metrics["directional_accuracy"],
                                    "comparison_status": "exploratory_not_selection_metric"})
            scores, inner_audit = _inner_scores(caches, live.forecast_cutoff)
            if not scores:
                summary["skipped"].append({"category_id": category_id, "reason": "No prospective selector score"})
                continue
            live_winner = scores[0]["candidate_id"]
            zero = caches["baseline_zero"]
            zero = zero[zero.target_month.isin(common)]
            selector_metrics, baseline_metrics = _metrics(selector), _metrics(zero)
            original_metrics = _metrics(reference) if not reference.empty else None
            leaderboard.append({"candidate_id": "nested_selector", "model_id": "nested_selector",
                                "feature_group": "adaptive_past_only", "selected": True,
                                "test_mae_pp": selector_metrics["mae_pp"], "test_rmse_pp": selector_metrics["rmse_pp"],
                                "test_n": selector_metrics["n"], "test_directional_accuracy": selector_metrics["directional_accuracy"],
                                "comparison_status": "predeclared_strategy_exploratory_replay"})
            result = {"category_id": category_id, "category_name": str(category.iloc[0].category_name),
                      "selected_model_id": "nested_selector", "selected_candidate_id": live_winner,
                      "selected_feature_group": "adaptive_past_only",
                      "selection_basis": summary["selection_basis"], "selection_audit": inner_audit,
                      "validation_metrics": {"n": scores[0]["n"], "mae_pp": scores[0]["mae_pp"], "rmse_pp": scores[0]["rmse_pp"]},
                      "test_metrics": selector_metrics, "baseline_metrics": baseline_metrics,
                      "original_metrics": original_metrics, "original_reference": reference_info,
                      "test_mae_improvement_vs_original_pp": None if original_metrics is None else original_metrics["mae_pp"] - selector_metrics["mae_pp"],
                      "forecast": {"as_of": as_of.isoformat(), "forecast_cutoff": live.forecast_cutoff.isoformat(),
                                   "target_month": live.target_month.strftime("%Y-%m-%d"), "change_pct": live_values[live_winner],
                                   "current_candidate_id": live_winner,
                                   "current_model_id": specs_by_id[live_winner]["model_id"],
                                   "current_feature_group": specs_by_id[live_winner]["feature_group"],
                                   "scope": "category_index", "interval": None},
                      "leaderboard": sorted(leaderboard, key=lambda e: e["test_mae_pp"]),
                      "live_selection_ranking": scores, "test_predictions": selector.to_dict("records"),
                      "original_predictions": reference.to_dict("records"), "warning": manifest["warning"]}
            selector.to_csv(category_dir / "nested_predictions.csv", index=False)
            if not reference.empty:
                reference.to_csv(category_dir / "original_frozen_predictions.csv", index=False)
            _write_json(category_dir / "summary.json", result)
            _plot(result, category_dir / "comparison.png", root)
            summary["categories"].append(result)
            print(f"[{category_id}] nested exploratory MAE {selector_metrics['mae_pp']:.4f}pp; live {live_winner}", flush=True)
    summary["status"] = "ready" if summary["categories"] else "unavailable"
    _write_json(directory / "summary.json", summary)
    _write_json(root / "data/experiments/category_tuning/summary.json", summary)
    lines = ["# Retrospective category tuning", "", manifest["warning"], "",
             "The nested policy, search limits, source hashes and candidates were frozen before this run produced any scores.",
             "Each inner fit uses only labels available at its issue; each outer choice uses only past OOF errors published by the outer issue.",
             "No final outer scores choose the next live model. The live selector uses the same fixed trailing36-month policy.", "",
             "| Category | Outer months | Nested MAE pp | Original MAE pp | Improvement pp |", "|---|---:|---:|---:|---:|"]
    for c in summary["categories"]:
        original = "unavailable" if c["original_metrics"] is None else f"{c['original_metrics']['mae_pp']:.4f}"
        improvement = "unavailable" if c["test_mae_improvement_vs_original_pp"] is None else f"{c['test_mae_improvement_vs_original_pp']:.4f}"
        lines.append(f"| {c['category_name']} | {c['test_metrics']['n']} | {c['test_metrics']['mae_pp']:.4f} | {original} | {improvement} |")
    lines += ["", "A negative improvement means the new nested selector performed worse. Individual candidate rankings are descriptive exploratory comparisons, not a post-hoc winner selection.",
              "Forecasts concern category CPI changes, not individual products, shrink events or recipes. No calibrated prediction intervals are emitted.", ""]
    (directory / "report.md").write_text("\n".join(lines))
    (root / "data/experiments/category_tuning/report.md").write_text("\n".join(lines))
    return _json_value(summary)


def run_category_tuning(root: Path, as_of: date, offline: bool = True) -> dict[str, Any]:
    from .category_tuning_data import build_enhanced_frame
    frame, metadata = build_enhanced_frame(Path(root), as_of)
    return run_tuning_frame(Path(root), frame, metadata, as_of)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--offline", action="store_true", help="All enhanced inputs are frozen local data")
    args = parser.parse_args()
    summary = run_category_tuning(args.root, args.as_of, args.offline)
    print(json.dumps({"status": summary["status"], "run_id": summary["run_id"], "categories": len(summary["categories"])}))


if __name__ == "__main__":
    main()
