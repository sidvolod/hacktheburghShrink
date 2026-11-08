"""Separate, past-information-only seasonal features for exploratory tuning.

Reads frozen category experiment inputs; never refreshes or rewrites them.
Changing models after seeing original test results is exploratory, not a new
untouched-test claim. Feature availability assumptions remain those recorded in
the original experiment, including the limitations of current source archives.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil.easter import easter

from .category_data import CATEGORIES, SERIES, _add_months, _parse_ons, _weekly_features, _weekly_inputs
from .common import sha256_file, utc_now, write_json

SAME_MONTH_NAMES = [f"history_same_month_lag{year}y_pct" for year in (1, 2, 3)] + [
    "history_same_month_mean3y_pct", "history_same_month_median3y_pct", "history_same_month_mean5y_pct"]
CALENDAR_NAMES = [f"season_month_{month:02d}" for month in range(1, 13)]
EASTER_NAMES = ["season_easter_month", "season_before_easter_month", "season_after_easter_month"]
EXTRA_HISTORY = ["history_baseline_seasonal", "history_pastyear_mean_pct", "history_trend_6m_pct"]


def _finite_mean(values: list[float]) -> float:
    valid = [value for value in values if math.isfinite(value)]
    return float(np.mean(valid)) if valid else np.nan


def _same_month_features(changes: dict[date, float], target: date, cutoff: date) -> dict:
    """Only earlier same-calendar-month labels available at the current issue."""
    values = {}
    for years in range(1, 6):
        month = _add_months(target, -12 * years)
        values[years] = changes.get(month, np.nan) if month < target and _add_months(month, 2) <= cutoff else np.nan
    three = [values[year] for year in (1, 2, 3) if math.isfinite(values[year])]
    return {**{f"history_same_month_lag{year}y_pct": values[year] for year in (1, 2, 3)},
        "history_same_month_mean3y_pct": float(np.mean(three)) if three else np.nan,
        "history_same_month_median3y_pct": float(np.median(three)) if three else np.nan,
        "history_same_month_mean5y_pct": _finite_mean(list(values.values()))}


def _long_weekly_features(inputs: dict[str, pd.DataFrame], category: str, cutoff: date) -> dict:
    result = {}
    for key, spec in SERIES.items():
        name = f"commodity_{key}_return_52w_pct"
        result[name] = np.nan
        if category not in spec["categories"] or key not in inputs:
            continue
        available = inputs[key].loc[inputs[key].week_end <= cutoff - timedelta(days=spec["buffer"])]
        if available.empty:
            continue
        latest = available.iloc[-1]
        if (cutoff - latest.week_end).days > 35:
            continue
        boundary = latest.week_end - timedelta(weeks=52)
        older = available.loc[available.week_end <= boundary]
        if not older.empty and (boundary - older.iloc[-1].week_end).days <= 10:
            result[name] = 100 * (latest.value / older.iloc[-1].value - 1)
    return result


def _enhance_frame(base: pd.DataFrame, indices: dict[str, dict[date, float]], inputs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Pure feature transformation; preserves original targets and cutoffs."""
    original_history = [column for column in base if column.startswith(("history_", "season_"))]
    original_commodities = [column for column in base if column.startswith("commodity_")]
    rows = []
    for _, source in base.iterrows():
        row = source.to_dict()
        category = row["category_id"]
        index = indices[category]
        changes = {month: 100 * (value / index[_add_months(month, -1)] - 1)
                   for month, value in index.items() if _add_months(month, -1) in index}
        target = date.fromisoformat(row["target_month"])
        cutoff = datetime.fromisoformat(row["forecast_cutoff"]).date()
        row.update({name: float(target.month == month) for month, name in enumerate(CALENDAR_NAMES, 1)})
        easter_month = easter(target.year).replace(day=1)
        row.update({name: float(category == "chocolate" and target == _add_months(easter_month, offset))
                    for name, offset in zip(EASTER_NAMES, (0, -1, 1))})
        row.update(_same_month_features(changes, target, cutoff))
        row["history_baseline_seasonal"] = row["baseline_seasonal"]
        row["baseline_seasonal_mean3"] = row["history_same_month_mean3y_pct"]
        row["baseline_seasonal_median3"] = row["history_same_month_median3y_pct"]
        row["baseline_seasonal_mean5"] = row["history_same_month_mean5y_pct"]
        known_month = date.fromisoformat(row["latest_known_cpi_month"]) if row.get("latest_known_cpi_month") else None
        trailing = [changes.get(_add_months(known_month, -lag), np.nan) for lag in range(12)] if known_month else []
        row["history_pastyear_mean_pct"] = float(np.mean(trailing)) if len(trailing) == 12 and all(math.isfinite(value) for value in trailing) else np.nan
        row["history_trend_6m_pct"] = float(np.mean(trailing[:3]) - np.mean(trailing[3:6])) if len(trailing) >= 6 and all(math.isfinite(value) for value in trailing[:6]) else np.nan
        row.update(_long_weekly_features(inputs, category, cutoff))
        # Reconstruct earlier issue-time source features even when the earlier
        # target has no observed label (e.g. Oct/Nov before the live Dec target).
        # No future target labels or later issue information are used.
        for lag in (1, 3, 6):
            earlier_issue = _add_months(target, -lag - 1).replace(day=8)
            if earlier_issue > cutoff:
                raise ValueError("Lagged issue would occur after forecast cutoff")
            past, _ = _weekly_features(inputs, category, earlier_issue)
            past.update(_long_weekly_features(inputs, category, earlier_issue))
            for name, value in past.items():
                row[f"{name}_issue_lag{lag}m"] = value
        rows.append(row)
    enhanced = pd.DataFrame(rows, index=base.index)
    groups = {}
    for category in CATEGORIES:
        compact = CALENDAR_NAMES + ["history_same_month_lag1y_pct", "history_same_month_mean3y_pct", "history_same_month_median3y_pct", "history_same_month_mean5y_pct"]
        if category == "chocolate":
            compact += EASTER_NAMES
        history = list(dict.fromkeys(compact + original_history + SAME_MONTH_NAMES + EXTRA_HISTORY))
        applicable = [column for column in enhanced if column.startswith("commodity_") and any(
            column.startswith(f"commodity_{key}_") and category in spec["categories"] for key, spec in SERIES.items())]
        groups[category] = {"compactseasonal": compact, "seasonal_history": history,
            "seasonal_history_commodities": history + applicable, "original_history": original_history.copy()}
    # The pre-existing numeric columns, labels, dates and live flags are an
    # immutable contract. Check rather than trusting accidental assignments.
    pd.testing.assert_frame_equal(enhanced[base.columns], base, check_dtype=False)
    return enhanced, groups


def build_enhanced_frame(root: Path, as_of: date) -> tuple[pd.DataFrame, dict]:
    root = root.resolve()
    original = root / "data/experiments/category_forecast"
    original_dataset = original / "dataset.parquet"
    original_metadata = original / "metadata.json"
    meta = json.loads(original_metadata.read_text())
    if meta.get("as_of") != as_of.isoformat():
        raise ValueError("as_of must match the frozen original experiment; no original live row is rewritten")
    original_hash = sha256_file(original_dataset)
    if meta.get("dataset_sha256") != original_hash:
        raise ValueError("Frozen original dataset hash differs from its metadata")
    frame = pd.read_parquet(original_dataset)
    indices = {}
    for category, info in meta["sources"]["ons"].items():
        path = root / info["snapshot_path"]
        if sha256_file(path) != info["sha256"]:
            raise ValueError(f"Frozen ONS source hash differs: {category}")
        indices[category], _ = _parse_ons(path)
    inputs, weekly_meta = _weekly_inputs(root)
    if weekly_meta.get("sha256") != meta["sources"]["weekly"].get("sha256"):
        raise ValueError("Weekly source changed since the original experiment")
    enhanced, groups = _enhance_frame(frame, indices, inputs)
    output = root / "data/experiments/category_tuning"
    output.mkdir(parents=True, exist_ok=True)
    dataset_path = output / "dataset.parquet"
    enhanced.to_parquet(dataset_path, index=False)
    metadata = {"schema_version": 1, "generated_at": utc_now(), "as_of": as_of.isoformat(),
        "experiment_status": "exploratory_followup_after_original_test_results_were_seen",
        "scope": meta["scope"], "target_frequency": "monthly", "commodity_input_frequency": meta["commodity_input_frequency"],
        "original_dataset": str(original_dataset.relative_to(root)), "original_dataset_sha256": original_hash,
        "original_metadata_sha256": sha256_file(original_metadata), "dataset_sha256": sha256_file(dataset_path),
        "sources": meta["sources"], "availability_status": meta["availability_status"],
        "feature_groups": groups, "new_baselines": ["baseline_seasonal_mean3", "baseline_seasonal_median3", "baseline_seasonal_mean5"],
        "features_fixed_before_new_test_scoring": True,
        "same_calendar_policy": "Prior one/two/three years and past3/5year mean/median; only target-month returns with label_available_date<=issue cutoff; aggregate available years, no filling",
        "known_calendar_policy": "Target-month onehot plus deterministic Gregorian Easter month, preceding and following month indicators for chocolate; calendar dates known ahead of issue, no external data acquisition",
        "lagged_commodity_policy": "Fixed earlier issue snapshots at target-calendar lags1/3/6months, each with original7/14day buffers; also actual52week returns; no monthly interpolation",
        "preserved_contract_columns": ["category_id", "category_name", "target_month", "forecast_cutoff", "label_available_date", "target_change_pct", "is_live"],
        "rows": len(enhanced), "columns": len(enhanced.columns),
        "limitations": meta["limitations"] + ["New feature design follows inspection of original results; later-period gains are exploratory and require a new untouched period for confirmation.",
            "Same-month aggregates use fewer than3/5years early in the archive when only fewer years are available.",
            "Historical weekly lagged features are reconstructed from the frozen current archive with assumed release buffers; original vintages are not recovered."]}
    write_json(output / "metadata.json", metadata)
    return enhanced, metadata
