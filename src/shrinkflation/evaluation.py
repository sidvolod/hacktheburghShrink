"""Audit whether the real panel supports a chronological forecast comparison.

The current panel cannot support one. No fitted-model metrics are emitted. The
zero-change error below is a descriptive check of observed mass-price outcomes,
not a held-out backtest, a skill claim, or a next-month forecast.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import connect, sql_literal, utc_now, write_json


def feasibility_reasons(coverage: dict) -> list[dict]:
    """Minimum comparison policy, separately from feature/evidence availability."""
    months = coverage["eligible_target_months"]
    reasons = []
    if len(months) < 4:
        reasons.append({
            "code": "insufficient_chronological_periods",
            "title": "Only one fully covered target month" if len(months) == 1 else "Too few fully covered target months",
            "detail": f"{coverage['eligible_mass_pairs']:,} eligible mass-price pairs cover {len(months)} distinct target month(s). "
                "The minimum comparison policy requires three training target months and one later test target month. "
                "Splitting products from the same month would not test future calendar periods.",
        })
    if coverage["strict_commodity_feature_rows_at_eligible_cutoffs"] == 0:
        reasons.append({
            "code": "commodity_publication_timing_unknown",
            "title": "Weekly inputs lack verified historical availability",
            "detail": "Real weekly commodity histories exist, but no strict publication-aware feature row is eligible at the "
                "retail forecast cutoffs. Observation dates and current archives do not establish original release or revision-vintage timing.",
        })
    if coverage["price_linked_verified_response_events"] == 0:
        reasons.append({
            "code": "response_history_not_linked",
            "title": "Previous response patterns cannot yet be evaluated",
            "detail": "Reported changes and one reviewed cross-barcode replacement are retained, but the retailer panel has no "
                "verified dated family-response sequence linked to these monthly price rows. Candidate matches are not training labels.",
        })
    return reasons


def zero_change_metrics(values: list[float]) -> dict | None:
    """Errors in percentage points of fractional unit-price change; never accuracy."""
    if not values:
        return None
    if any(not math.isfinite(value) for value in values):
        raise ValueError("No-change reference requires finite observed outcomes")
    absolute = sorted(abs(value) for value in values)
    count = len(values)
    midpoint = count // 2
    median = absolute[midpoint] if count % 2 else (absolute[midpoint - 1] + absolute[midpoint]) / 2
    return {
        "observations": count,
        "prediction_change_fraction": 0.0,
        "mae_percentage_points": 100 * math.fsum(absolute) / count,
        "rmse_percentage_points": 100 * math.sqrt(math.fsum(value * value for value in values) / count),
        "median_absolute_error_percentage_points": 100 * median,
        "mean_actual_change_percentage_points": 100 * math.fsum(values) / count,
        "mean_signed_error_percentage_points": -100 * math.fsum(values) / count,
        "rises": sum(value > 0 for value in values),
        "falls": sum(value < 0 for value in values),
        "flat": sum(value == 0 for value in values),
        "min_actual_change_percentage_points": 100 * min(values),
        "max_actual_change_percentage_points": 100 * max(values),
    }


def run(root: Path, fetch: bool = False) -> dict:
    """Read the frozen prepared data and emit a transparent unavailable result."""
    processed = root / "data/processed"
    conn = connect(root)
    try:
        for view, name in (
            ("targets", "monthly_targets"), ("weekly", "commodity_weekly"),
            ("features", "commodity_monthly_features"), ("monthly", "retail_monthly"),
            ("members", "family_members"), ("candidates", "retail_catalogue_candidates"),
            ("reported", "reported_changes"),
        ):
            path = processed / f"{name}.parquet"
            if not path.exists():
                raise FileNotFoundError(f"Prepare {name} before evaluating forecast feasibility: {path}")
            conn.execute(f"CREATE TEMP VIEW {view} AS SELECT * FROM read_parquet({sql_literal(path)})")
        conn.execute("""CREATE TEMP VIEW eligible_mass AS
            SELECT * FROM targets WHERE eligible_for_sampled_monthly_price_evaluation
              AND dimension='mass_g' AND next_month_unit_price_change_fraction IS NOT NULL""")
        months = [str(row[0]) for row in conn.execute("SELECT DISTINCT target_month FROM eligible_mass ORDER BY 1").fetchall()]
        source_first, source_last = conn.execute("SELECT min(source_first), max(source_last) FROM monthly").fetchone()
        reviewed_pairs = conn.execute("""SELECT count(*) FROM (
            SELECT family_id FROM members GROUP BY family_id
              HAVING count(*) FILTER(WHERE role='old')>0 AND count(*) FILTER(WHERE role='new')>0)""").fetchone()[0]
        # The prepared family-members table has no retailer-listing IDs or dated
        # transition boundaries; candidate links are deliberately not promoted.
        dated_memberships = conn.execute("""SELECT count(*) FROM members
            WHERE valid_from IS NOT NULL AND valid_to IS NOT NULL""").fetchone()[0]
        exact_event_labels = conn.execute("SELECT count(*) FROM reported WHERE eligible_monthly_training_label").fetchone()[0]
        coverage = {
            "retail_date_start": str(source_first), "retail_date_end": str(source_last),
            "retail_calendar_months": conn.execute("SELECT count(DISTINCT month) FROM monthly").fetchone()[0],
            "eligible_mass_pairs": conn.execute("SELECT count(*) FROM eligible_mass").fetchone()[0],
            "eligible_volume_pairs": conn.execute("SELECT count(*) FROM targets WHERE eligible_for_sampled_monthly_price_evaluation AND dimension='volume_ml'").fetchone()[0],
            "eligible_target_months": months,
            "strict_commodity_feature_rows_at_eligible_cutoffs": conn.execute("""SELECT count(*) FROM features
                WHERE feature_mode='strict_known_publication' AND eligible_for_backtest
                AND cutoff_date IN (SELECT DISTINCT forecast_cutoff_date FROM eligible_mass)""").fetchone()[0],
            "weekly_commodity_rows": conn.execute("SELECT count(*) FROM weekly").fetchone()[0],
            "reviewed_barcode_replacement_pairs": reviewed_pairs,
            "retail_catalogue_candidate_pairs": conn.execute("SELECT count(*) FROM candidates").fetchone()[0],
            "dated_barcode_memberships": dated_memberships,
            "exact_reported_monthly_event_labels": exact_event_labels,
            "price_linked_verified_response_events": 0,
            "response_event_link_status": "no_reviewed_retail_listing_to_family_join_in_prepared_schema",
            "identity_scope": "retailer and exact raw name, not fully reconstructed product families",
        }
        reasons = feasibility_reasons(coverage)
        # This module deliberately does not claim that adding rows automatically
        # supplies a validated model. A future modelling step must implement and
        # audit the actual folds, fits and feature availability before this changes.
        if not reasons:
            reasons.append({"code":"comparison_not_run", "title":"Chronological comparison has not been run",
                "detail":"The coverage audit alone does not establish model performance. Fit and audit chronological models before enabling a forecast."})
        values = [row[0] for row in conn.execute("SELECT next_month_unit_price_change_fraction FROM eligible_mass").fetchall()]
        reference = zero_change_metrics(values)
        if reference:
            reference.update({
                "status": "descriptive_only", "is_chronological_backtest": False,
                "label": "Observed no-change reference, not a held-out model result",
                "target_months": months,
                "scope": "Only eligible mass-price monthly pairs; volume outcomes are excluded",
                "interpretation": "Predicting zero change for every observed pair produces these errors. "
                    "This is a single-period data reference and does not measure future skill or model accuracy.",
                "limitations": ["Provisional retailer/name identities, not reviewed family histories.",
                    "Prices may include loyalty discounts; per-row offer conditions are unknown.",
                    "Large source-observed changes remain and are not adjudicated shrink-event labels.",
                    "No training, tuning, interval calibration or chronological held-out comparison was performed."],
            })
        model_reason = "No chronological training/test split: only one eligible target month is available."
        report = {
            "schema_version": 1, "generated_at": utc_now(), "status": "unavailable",
            "title": "Monthly forecasting unavailable",
            "reason": [item["detail"] for item in reasons], "reasons": reasons,
            "target_definition": {
                "cadence": "monthly", "commodity_input_cadence": "weekly",
                "quantity": "next-calendar-month change in price per gram",
                "formula": "next_month_median_price_per_100g / current_month_median_price_per_100g - 1",
                "aggregation": "Median of observed daily unit prices within each calendar month; no filling",
                "forecast_cutoff": "00:00 Europe/London on the first day of the target month",
                "error_unit": "percentage points of unit-price change", "missing_target_policy": "unknown, never zero change",
            },
            "coverage": coverage,
            "chronological_split": {"status":"not_constructed", "training_target_months":[], "test_target_months":[],
                "minimum_training_target_months":3, "minimum_later_test_target_months":1,
                "note":"All labels used for training must finish and be available before a later forecast cutoff. No random product-day split."},
            "models": [{"id":model_id,"name":name,"status":"not_run",
                "mae_percentage_points":None,"rmse_percentage_points":None,"reason":model_reason}
                for model_id,name in (("no_change","No change"),("linear_regression","Linear regression"),("boosted_tree","Gradient-boosted trees"))],
            "selected_model": None, "forecast": None,
            "observed_nochange_reference": reference,
            "feature_ablations": [
                {"id":"history_only","name":"Product-price history only","status":"unavailable","improvement_percentage_points":None,
                    "reason":"No earlier eligible training target period exists before March 2024."},
                {"id":"weekly_commodities","name":"History plus weekly commodity movements","status":"unavailable","improvement_percentage_points":None,
                    "reason":"No valid chronological comparison and no verified publication-aware commodity features at eligible cutoffs."},
                {"id":"response_patterns","name":"History, commodities and previous response patterns","status":"unavailable","improvement_percentage_points":None,
                    "reason":"No price-linked verified family-response sequence. Alternation between shrinking and raising price remains an untested hypothesis."},
            ],
            "data_needed": [
                {"id":"longer_retail_history","title":"More complete retail months",
                    "detail":"For even one minimal chronological comparison, collect at least three additional distinct eligible target months "
                        "after/before the existing March 2024 period, with complete adjacent-month sampling and labels available before each test cutoff. "
                        "More periods are needed to assess commodity lags and performance stability."},
                {"id":"dated_family_links","title":"Reviewed dated family histories",
                    "detail":"Connect retailer listings to reviewed old/new barcodes and document replacement timing, pack mass/count, "
                        "prices, offer conditions and raw ingredient evidence. Distinguish concurrent variants."},
                {"id":"publication_vintages","title":"Commodity release and revision timing",
                    "detail":"Retain daily/weekly release timestamps or defensible historical availability policies and original vintages. "
                        "Current archive observation dates alone are insufficient for historical cutoffs."},
                {"id":"remaining_weekly_inputs","title":"Weekly sugar, edible oils and dairy",
                    "detail":"Acquire genuine weekly/daily feeds for the missing relevant inputs; do not interpolate monthly World Bank values or substitute oilseeds for crude edible oils."},
            ],
            "source_files": ["data/processed/monthly_targets.parquet","data/processed/retail_monthly.parquet",
                "data/processed/commodity_weekly.parquet","data/processed/commodity_monthly_features.parquet",
                "data/processed/family_members.parquet","data/processed/reported_changes.parquet",
                "data/processed/retail_catalogue_candidates.parquet"],
        }
        write_json(root / "data/reports/evaluation.json",report)
        mae = f"{reference['mae_percentage_points']:.4f}" if reference else "unavailable"
        rmse = f"{reference['rmse_percentage_points']:.4f}" if reference else "unavailable"
        text = "# Forecast feasibility and evaluation\n\n"
        text += "**Forecast unavailable. No chronological model comparison was run.**\n\n"
        text += "The target is next-calendar-month price-per-gram change; commodity inputs are weekly. "
        text += "The retail panel spans " + str(source_first) + " to " + str(source_last) + ".\n\n"
        text += "\n".join("- " + item["detail"] for item in reasons) + "\n\n"
        text += "## Model comparison\n\n| Model | Status | Held-out MAE | Held-out RMSE |\n| --- | --- | --- | --- |\n"
        text += "\n".join(f"| {model['name']} | Not run | Unavailable | Unavailable |" for model in report["models"]) + "\n\n"
        text += "Commodity and previous-response feature improvements are **unknown**, not zero. No model was selected and no next-month forecast is emitted.\n\n"
        text += "## Descriptive reference from real observations\n\n"
        text += f"For the {coverage['eligible_mass_pairs']:,} eligible **mass-price** pairs targeting March 2024, "
        text += f"a zero-change prediction has MAE **{mae} percentage points** and RMSE **{rmse} percentage points**. "
        text += "These are observed single-period errors, **not held-out backtest results, forecast accuracy, or evidence of future skill**. "
        text += "Volume outcomes are separate. Identities are provisional, prices may include loyalty discounts, and large observed changes remain.\n\n"
        text += "## Data needed\n\n" + "\n".join("- **"+item["title"]+".** "+item["detail"] for item in report["data_needed"]) + "\n\n"
        text += "The one reviewed barcode replacement and unverified candidates are separate evidence assets. "
        text += "A same-barcode repeat count is not a measurement of all possible reconstructed-family coverage.\n\n"
        text += "Reproduce with `PYTHONPATH=src .venv/bin/python -c \"from pathlib import Path; from shrinkflation.evaluation import run; run(Path.cwd())\"`. "
        text += "Exact metrics, scope, coverage and source-file lineage are in `data/reports/evaluation.json`.\n"
        (root / "data/reports/evaluation.md").write_text(text)
        return report
    finally:
        conn.close()
