"""Ten frozen aggregation policies over existing category OOF predictions.

No models are refitted and no first-stage files are changed. This second-stage
experiment was designed after examining the first retuning results. Every
replay is retrospective exploratory evidence, never a fresh untouched test.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .category_models import _json_value, _metrics, _write_json
from .category_tuning import _inner_scores

POLICY_OOF_START = pd.Timestamp("2021-01-01", tz="UTC")
OUTER_START = pd.Timestamp("2024-01-01", tz="UTC")
POLICY_WINDOW_MONTHS = 36
MIN_POLICY_ERRORS = 12
WEIGHT_MAE_FLOOR = 0.000001


def policy_catalog() -> list[dict[str, Any]]:
    policies = [
        {"policy_id": "best1", "aggregation": "mean", "top_k": 1, "shrink_to_zero": 1.0},
        {"policy_id": "mean_top3", "aggregation": "mean", "top_k": 3, "shrink_to_zero": 1.0},
        {"policy_id": "median_top3", "aggregation": "median", "top_k": 3, "shrink_to_zero": 1.0},
        {"policy_id": "inverse_mae_top3", "aggregation": "inverse_mae", "top_k": 3, "shrink_to_zero": 1.0},
        {"policy_id": "mean_top5", "aggregation": "mean", "top_k": 5, "shrink_to_zero": 1.0},
        {"policy_id": "median_top5", "aggregation": "median", "top_k": 5, "shrink_to_zero": 1.0},
        {"policy_id": "best1_shrink075", "aggregation": "mean", "top_k": 1, "shrink_to_zero": 0.75},
        {"policy_id": "best1_recent12", "aggregation": "mean", "top_k": 1, "shrink_to_zero": 1.0,
         "candidate_error_window_months": 12},
        {"policy_id": "best1_recent24", "aggregation": "mean", "top_k": 1, "shrink_to_zero": 1.0,
         "candidate_error_window_months": 24},
        {"policy_id": "zero", "aggregation": "zero", "top_k": 0, "shrink_to_zero": 1.0},
    ]
    return [{"candidate_error_window_months": 36, **policy} for policy in policies]


def _aggregate(policy: dict[str, Any], ranked_scores: list[dict[str, Any]],
               predictions: dict[str, float]) -> tuple[float | None, list[dict[str, Any]]]:
    if policy["aggregation"] == "zero":
        return 0.0, []
    eligible = [score for score in ranked_scores if score["candidate_id"] in predictions
                and math.isfinite(predictions[score["candidate_id"]])]
    selected = eligible[:policy["top_k"]]
    if len(selected) < policy["top_k"]:
        return None, []
    values = np.array([predictions[s["candidate_id"]] for s in selected], dtype=float)
    if policy["aggregation"] == "median":
        value = float(np.median(values))
        weights = [None] * len(selected)
    elif policy["aggregation"] == "inverse_mae":
        w = 1 / np.maximum([s["mae_pp"] for s in selected], WEIGHT_MAE_FLOOR)
        w = w / np.sum(w)
        value = float(w @ values)
        weights = w.tolist()
    else:
        value = float(values.mean())
        weights = [1 / len(selected)] * len(selected)
    shrink = policy["shrink_to_zero"]
    components = [{"candidate_id": score["candidate_id"], "prediction_pct": float(prediction),
                   "past_mae_pp": score["mae_pp"],
                   "weight": None if weight is None else weight * shrink}
                  for score, prediction, weight in zip(selected, values, weights)]
    return value * shrink, components


def _candidate_scores(caches: dict[str, pd.DataFrame], cutoff: pd.Timestamp,
                      window: int = 36) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if window == 36:
        return _inner_scores(caches, cutoff)
    reference = caches.get("baseline_zero", next(iter(caches.values())))
    known = reference[(pd.to_datetime(reference.label_available_date, utc=True) <= cutoff)
                      & (pd.to_datetime(reference.forecast_cutoff, utc=True) < cutoff)]
    if known.empty:
        return [], {"n": 0, "max_label_available_date": None, "window_months": window}
    start = pd.to_datetime(known.target_month, utc=True).max() - pd.DateOffset(months=window - 1)
    trimmed = {key: rows[pd.to_datetime(rows.target_month, utc=True) >= start]
               for key, rows in caches.items()}
    scores, audit = _inner_scores(trimmed, cutoff)
    audit["window_months"] = window
    return scores, audit


def build_policy_oof(caches: dict[str, pd.DataFrame], targets: pd.DataFrame,
                     policies: list[dict[str, Any]] | None = None) -> dict[str, pd.DataFrame]:
    policies = policy_catalog() if policies is None else policies
    records = {p["policy_id"]: [] for p in policies}
    lookups = {candidate: data.set_index("target_month").predicted_pct.to_dict() for candidate, data in caches.items()}
    for _, row in targets.iterrows():
        target = str(row.target_month)[:10]
        cutoff = pd.Timestamp(row.forecast_cutoff)
        rankings = {window: _candidate_scores(caches, cutoff, window)
                    for window in sorted({p["candidate_error_window_months"] for p in policies})}
        values = {candidate: float(lookup[target]) for candidate, lookup in lookups.items() if target in lookup}
        for policy in policies:
            scores, audit = rankings[policy["candidate_error_window_months"]]
            if not scores and policy["aggregation"] != "zero":
                continue
            value, components = _aggregate(policy, scores, values)
            if value is None:
                continue
            records[policy["policy_id"]].append({
                "target_month": target, "forecast_cutoff": cutoff.isoformat(),
                "label_available_date": pd.Timestamp(row.label_available_date).isoformat(),
                "actual_pct": float(row.actual_pct), "predicted_pct": value,
                "baseline_pct": float(row.get("baseline_pct", 0.0)), "policy_id": policy["policy_id"],
                "components_json": json.dumps(_json_value(components), separators=(",", ":")),
                "zero_weight": 1.0 if policy["aggregation"] == "zero" else 1 - policy["shrink_to_zero"],
                "candidate_selection_max_label_available_date": audit["max_label_available_date"],
                "candidate_inner_validation_n": audit["n"],
                "candidate_error_window_months": policy["candidate_error_window_months"],
            })
    return {policy: pd.DataFrame(rows) for policy, rows in records.items()}


def _policy_scores(caches: dict[str, pd.DataFrame], cutoff: pd.Timestamp) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # The first-stage helper's frozen 36-month/min12 common-date rule is also
    # the explicitly predeclared second-stage rule, not another tuned choice.
    return _inner_scores(caches, cutoff)


def select_policies(policy_caches: dict[str, pd.DataFrame], targets: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in targets.iterrows():
        cutoff = pd.Timestamp(row.forecast_cutoff)
        scores, audit = _policy_scores(policy_caches, cutoff)
        if not scores:
            continue
        policy_id = scores[0]["candidate_id"]
        candidates = policy_caches[policy_id]
        chosen = candidates[candidates.target_month == str(row.target_month)[:10]]
        if chosen.empty:
            continue
        record = chosen.iloc[0].to_dict()
        record["components"] = json.loads(record["components_json"])
        record.update({"selected_policy_id": policy_id, "candidate_id": policy_id, "model_id": policy_id,
                       "feature_group": "adaptive_past_only", "policy_inner_validation_mae_pp": scores[0]["mae_pp"],
                       "policy_inner_validation_n": audit["n"],
                       "policy_selection_max_label_available_date": audit["max_label_available_date"]})
        records.append(record)
    return pd.DataFrame(records)


def _resolve_base(root: Path, base_run: Path | None) -> Path:
    if base_run is not None:
        base_run = Path(base_run)
        return base_run if base_run.is_absolute() else root / base_run
    pointer = root / "data/experiments/category_tuning/summary.json"
    summary = json.loads(pointer.read_text())
    return root / "data/experiments/category_tuning" / summary["run_id"]


def _load_base(base: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    summary_path, manifest_path = base / "summary.json", base / "search_manifest.json"
    summary, manifest = json.loads(summary_path.read_text()), json.loads(manifest_path.read_text())
    if summary.get("status") != "ready":
        raise ValueError("First-stage run must be complete before second-stage policy evaluation")
    categories, checksums = {}, {}
    for source in (summary_path, manifest_path):
        checksums[str(source.relative_to(base))] = hashlib.sha256(source.read_bytes()).hexdigest()
    allowed = {s["candidate_id"] for s in manifest["candidates"]}
    for category in summary["categories"]:
        category_id = category["category_id"]
        caches, live_values = {}, {}
        for path in sorted((base / category_id).glob("*/*/oof_predictions.csv")):
            candidate = path.parent.name
            if candidate not in allowed:
                continue
            checksums[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
            predictions = pd.read_csv(path)
            if predictions.empty:
                continue
            if predictions.duplicated("target_month").any():
                raise ValueError("OOF cache has duplicate target months")
            caches[candidate] = predictions
            live_path = path.parent / "live_forecast.json"
            checksums[str(live_path.relative_to(base))] = hashlib.sha256(live_path.read_bytes()).hexdigest()
            live = json.loads(live_path.read_text())
            if live["as_of"] != summary["as_of"] or live["target_month"] != category["forecast"]["target_month"]:
                raise ValueError("Saved component live forecasts have inconsistent issue dates or targets")
            if live["change_pct"] is not None:
                live_values[candidate] = float(live["change_pct"])
        if "baseline_zero" not in caches:
            raise ValueError("No frozen zero-change reference cache")
        reference = caches["baseline_zero"][["target_month", "forecast_cutoff", "label_available_date", "actual_pct", "baseline_pct"]]
        for candidate, predictions in caches.items():
            joined = predictions.merge(reference, on="target_month", suffixes=("", "_reference"), validate="one_to_one")
            if not np.allclose(joined.actual_pct, joined.actual_pct_reference, rtol=0, atol=1e-10):
                raise ValueError(f"Inconsistent actual outcomes in candidate cache {candidate}")
            for column in ("forecast_cutoff", "label_available_date"):
                if not (pd.to_datetime(joined[column], utc=True) == pd.to_datetime(joined[column + "_reference"], utc=True)).all():
                    raise ValueError(f"Inconsistent timing in candidate cache {candidate}")
        categories[category_id] = {"source": category, "caches": caches, "live_values": live_values,
                                   "targets": reference.sort_values("target_month")}
    return summary, manifest, categories, checksums


def _freeze(root: Path, base: Path, base_summary: dict[str, Any], checksums: dict[str, str]) -> tuple[Path, dict[str, Any]]:
    import shrinkflation.category_tuning as helper
    if helper.INNER_MONTHS != POLICY_WINDOW_MONTHS or helper.MIN_INNER != MIN_POLICY_ERRORS:
        raise ValueError("Frozen policy selection requires the declared36-month/min12 helper policy")
    manifest = {"schema_version": 1, "base_run": str(base), "base_run_id": base_summary["run_id"],
                "as_of": base_summary["as_of"], "evaluation_status": "exploratory_second_stage_after_initial_retuning",
                "warning": "Designed after examining initial retuning results; no untouched test remains. Category CPI only.",
                "policies": policy_catalog(), "candidate_cache_checksums": checksums,
                "policy_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "selection_helper_sha256": hashlib.sha256(Path(helper.__file__).read_bytes()).hexdigest(),
                "policy": {"policy_oof_start": "2021-01-01", "outer_start": "2024-01-01", "error_window_months": POLICY_WINDOW_MONTHS,
                           "minimum_published_errors": MIN_POLICY_ERRORS, "selection": "past-only common-date policy OOF MAE",
                           "inverse_mae_floor_pp": WEIGHT_MAE_FLOOR, "models_retrained": 0,
                           "policies_expanded_after_scores": False, "prediction_intervals": None},
                "runtime": {"numpy": np.__version__, "pandas": pd.__version__}}
    digest = hashlib.sha256(json.dumps(_json_value(manifest), sort_keys=True).encode()).hexdigest()[:16]
    manifest["run_id"] = digest
    output = root / "data/experiments/category_policy_tuning" / digest
    output.mkdir(parents=True, exist_ok=True)
    path = output / "search_manifest.json"
    if path.exists() and json.loads(path.read_text()) != _json_value(manifest):
        raise ValueError("Policy manifest cannot be changed after freezing")
    if not path.exists():
        _write_json(path, manifest)
    return output, manifest


def _plot(result: dict[str, Any], path: Path, root: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(root / "data/.cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = result["test_predictions"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    dates = pd.to_datetime([r["target_month"] for r in rows])
    ax.plot(dates, [r["actual_pct"] for r in rows], label="Observed category change", color="#202d35")
    ax.plot(dates, [r["predicted_pct"] for r in rows], label="Nested policy selector", color="#098c88")
    ax.axhline(0, color="#aaa", ls="--", lw=1)
    ax.set_title(result["category_name"] + ": exploratory second-stage replay")
    ax.set_ylabel("Monthly change (%)")
    ax.legend(fontsize=8)
    fig.text(.5, .01, "Policies designed after initial results; no fresh holdout or individual-product accuracy claim.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .03, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run_category_policy_tuning(root: Path, as_of: date | None = None,
                               base_run: Path | None = None) -> dict[str, Any]:
    root = Path(root)
    base = _resolve_base(root, base_run)
    base_summary, base_manifest, categories, checksums = _load_base(base)
    if as_of is not None and as_of.isoformat() != base_summary["as_of"]:
        raise ValueError("As-of must match frozen component live forecasts; refit in a new first-stage run for another date")
    output, manifest = _freeze(root, base, base_summary, checksums)
    summary = {"schema_version": 1, "run_id": manifest["run_id"], "as_of": base_summary["as_of"],
               "generated_at": datetime.now(timezone.utc).isoformat(), "scope": "category_CPI_monthly_change",
               "evaluation_status": manifest["evaluation_status"], "evaluation_label": manifest["warning"],
               "warning": manifest["warning"], "selection_basis": "Past-only nested policy selection using36 published monthly OOF errors",
               "search_manifest": str(output / "search_manifest.json"), "base_run_id": base_summary["run_id"],
               "policy_count": 10, "models_retrained": 0, "categories": []}
    for category_id, data in categories.items():
        print(f"[{category_id}] aggregating frozen candidate forecasts under10 fixed policies", flush=True)
        source, targets = data["source"], data["targets"]
        oof_targets = targets[pd.to_datetime(targets.target_month, utc=True) >= POLICY_OOF_START]
        policy_caches = build_policy_oof(data["caches"], oof_targets)
        outer = targets[pd.to_datetime(targets.target_month, utc=True) >= OUTER_START]
        selected = select_policies(policy_caches, outer)
        if selected.empty:
            raise ValueError("Not enough published prior policy errors for outer selection")
        original = pd.DataFrame(source.get("original_predictions", []))
        base_predictions = pd.DataFrame(source["test_predictions"])
        common = set(selected.target_month) & set(base_predictions.target_month)
        if not original.empty:
            common &= set(original.target_month)
        selected = selected[selected.target_month.isin(common)].copy()
        if selected.empty:
            raise ValueError("No common outer dates for policy/original comparison")
        leaderboard = []
        category_dir = output / category_id
        for policy in policy_catalog():
            policy_id = policy["policy_id"]
            predictions = policy_caches[policy_id]
            directory = category_dir / "policies" / policy_id
            directory.mkdir(parents=True, exist_ok=True)
            predictions.to_csv(directory / "oof_predictions.csv", index=False)
            evaluated = predictions[predictions.target_month.isin(common)]
            if set(evaluated.target_month) != common:
                raise ValueError("Fixed policy comparison requires identical outer months")
            metrics = _metrics(evaluated)
            evaluated.to_csv(directory / "outer_predictions.csv", index=False)
            _write_json(directory / "config.json", {**policy, "models_retrained": 0, "manifest": "../../../search_manifest.json"})
            _write_json(directory / "metrics.json", {"outer_exploratory": metrics, "warning": manifest["warning"]})
            leaderboard.append({"candidate_id": policy_id, "model_id": policy_id, "feature_group": "aggregation_policy",
                                "test_mae_pp": metrics["mae_pp"], "test_rmse_pp": metrics["rmse_pp"], "test_n": metrics["n"],
                                "test_directional_accuracy": metrics["directional_accuracy"],
                                "comparison_status": "fixed_policy_descriptive_not_used_for_posthoc_choice"})
        live_cutoff = pd.Timestamp(source["forecast"]["forecast_cutoff"])
        policy_scores, selection_audit = _policy_scores(policy_caches, live_cutoff)
        if not policy_scores:
            raise ValueError("Not enough known policy errors for the live selector")
        live_policy_id = policy_scores[0]["candidate_id"]
        live_policy = next(p for p in policy_catalog() if p["policy_id"] == live_policy_id)
        candidate_scores, candidate_audit = _candidate_scores(data["caches"], live_cutoff,
                                                             live_policy["candidate_error_window_months"])
        value, components = _aggregate(live_policy, candidate_scores, data["live_values"])
        if value is None:
            raise ValueError("Missing saved live forecasts for selected policy components")
        selected_metrics = _metrics(selected)
        zero = data["caches"]["baseline_zero"]
        zero = zero[zero.target_month.isin(common)]
        baseline_metrics = _metrics(zero)
        original = original[original.target_month.isin(common)] if not original.empty else original
        original_metrics = _metrics(original) if not original.empty else None
        base_metrics = _metrics(base_predictions[base_predictions.target_month.isin(common)])
        leaderboard.append({"candidate_id": "nested_policy_selector", "model_id": "nested_policy_selector",
                            "feature_group": "adaptive_past_only", "selected": True, "test_mae_pp": selected_metrics["mae_pp"],
                            "test_rmse_pp": selected_metrics["rmse_pp"], "test_n": selected_metrics["n"],
                            "test_directional_accuracy": selected_metrics["directional_accuracy"],
                            "comparison_status": "predeclared_nested_policy_strategy_exploratory"})
        result = {"category_id": category_id, "category_name": source["category_name"],
                  "selected_model_id": "nested_policy_selector", "selected_feature_group": "adaptive_past_only",
                  "selected_candidate_id": live_policy_id, "selection_basis": summary["selection_basis"],
                  "selection_audit": selection_audit, "candidate_selection_audit": candidate_audit,
                  "validation_metrics": {"n": policy_scores[0]["n"], "mae_pp": policy_scores[0]["mae_pp"], "rmse_pp": policy_scores[0]["rmse_pp"]},
                  "test_metrics": selected_metrics, "baseline_metrics": baseline_metrics,
                  "original_metrics": original_metrics, "first_tuning_metrics": base_metrics,
                  "test_mae_improvement_vs_original_pp": None if original_metrics is None else original_metrics["mae_pp"] - selected_metrics["mae_pp"],
                  "test_mae_improvement_vs_first_tuning_pp": base_metrics["mae_pp"] - selected_metrics["mae_pp"],
                  "forecast": {"as_of": source["forecast"]["as_of"], "forecast_cutoff": live_cutoff.isoformat(),
                               "target_month": source["forecast"]["target_month"], "change_pct": value, "scope": "category_index", "interval": None,
                               "current_model_id": live_policy_id, "current_candidate_id": live_policy_id,
                               "current_feature_group": "aggregation_policy", "components": components,
                               "zero_weight": 1.0 if live_policy["aggregation"] == "zero" else 1 - live_policy["shrink_to_zero"]},
                  "leaderboard": sorted(leaderboard, key=lambda p: p["test_mae_pp"]), "live_selection_ranking": policy_scores,
                  "test_predictions": selected.to_dict("records"), "warning": manifest["warning"]}
        selected.to_csv(category_dir / "nested_policy_predictions.csv", index=False)
        _write_json(category_dir / "summary.json", result)
        _plot(result, category_dir / "comparison.png", root)
        summary["categories"].append(result)
        print(f"[{category_id}] nestedpolicy exploratory MAE {selected_metrics['mae_pp']:.4f}pp; livepolicy {live_policy_id}", flush=True)
    summary["status"] = "ready" if summary["categories"] else "unavailable"
    _write_json(output / "summary.json", summary)
    latest = root / "data/experiments/category_policy_tuning"
    _write_json(latest / "summary.json", summary)
    lines = ["# Second-stage aggregation-policy experiment", "", manifest["warning"], "",
             "Ten policies and the36-month/min12 past-policy-error selection rule were frozen before computing this experiment's outer metrics. No model was retrained.",
             "Each historical forecast records both policy-selection availability and candidate-ranking availability. Fixed policy scores are descriptive; they do not choose the live policy.", "",
             "| Category | Months | Nested policy MAE pp | First tuning MAE pp | Original MAE pp |",
             "|---|---:|---:|---:|---:|"]
    for c in summary["categories"]:
        old = "unavailable" if c["original_metrics"] is None else f"{c['original_metrics']['mae_pp']:.4f}"
        lines.append(f"| {c['category_name']} | {c['test_metrics']['n']} | {c['test_metrics']['mae_pp']:.4f} | {c['first_tuning_metrics']['mae_pp']:.4f} | {old} |")
    lines += ["", "This is a retrospective second-stage replay after earlier results were examined. There is no fresh holdout, calibrated interval, or individual-product accuracy claim.", ""]
    (output / "report.md").write_text("\n".join(lines))
    (latest / "report.md").write_text("\n".join(lines))
    return _json_value(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--base-run", type=Path)
    parser.add_argument("--offline", action="store_true", help="Accepted for the shared runner; policy experiments always use frozen local files")
    args = parser.parse_args()
    summary = run_category_policy_tuning(args.root, args.as_of, args.base_run)
    print(json.dumps({"status": summary["status"], "run_id": summary["run_id"], "models_retrained": 0}))


if __name__ == "__main__":
    main()
