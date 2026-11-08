"""Observed monthly retail outcomes. Missing months are never filled."""
from __future__ import annotations

from pathlib import Path

from .common import connect, export_query, sql_literal, write_json


def prepare_monthly(conn, prices: Path) -> None:
    conn.execute(f"CREATE OR REPLACE TEMP VIEW prices AS SELECT * FROM read_parquet({sql_literal(prices)})")
    conn.execute("""CREATE OR REPLACE TEMP VIEW unit_prices AS
        SELECT source_product_id,retailer,observation_date,price_basis,mass_unit_price_basis AS unit_price_basis,
            'mass_g' AS dimension,price_per_100g_gbp AS unit_price
        FROM prices WHERE unit_price_eligible AND price_per_100g_gbp>0
        UNION ALL
        SELECT source_product_id,retailer,observation_date,price_basis,volume_unit_price_basis AS unit_price_basis,
            'volume_ml' AS dimension,price_per_100ml_gbp AS unit_price
        FROM prices WHERE unit_price_eligible AND price_per_100ml_gbp>0""")
    conn.execute("""CREATE OR REPLACE TEMP TABLE monthly_observations AS
        WITH daily AS (
          SELECT source_product_id,retailer,observation_date,price_basis,unit_price_basis,dimension,
            median(unit_price) AS daily_unit_price,count(*) AS observations
          FROM unit_prices GROUP BY ALL
        ), bounds AS (SELECT min(observation_date) AS source_first,max(observation_date) AS source_last FROM prices),
        aggregated AS (SELECT source_product_id,retailer,price_basis,unit_price_basis,dimension,
          date_trunc('month',observation_date)::DATE AS month,
          median(daily_unit_price) AS median_price_per_100,
          min(daily_unit_price) AS min_price_per_100,max(daily_unit_price) AS max_price_per_100,
          count(*) AS observed_days,sum(observations)::BIGINT AS observations,
          min(observation_date) AS first_observed_date,max(observation_date) AS last_observed_date
          FROM daily GROUP BY source_product_id,retailer,price_basis,unit_price_basis,dimension,month)
        SELECT *,source_first<=month AND source_last>=last_day(month) AS dataset_covers_full_calendar_month,
          first_observed_date<=month+6 AND last_observed_date>=last_day(month)-6 AS observed_near_both_month_boundaries,
          'retailer_exact_name_provisional_not_reconstructed_family' AS identity_scope,
          'median_of_observed_daily_unit_prices_no_imputation' AS aggregation
        FROM aggregated CROSS JOIN bounds""")
    conn.execute("""CREATE OR REPLACE TEMP VIEW monthly_targets AS
        SELECT a.source_product_id,a.retailer,a.price_basis,a.unit_price_basis,a.dimension,
          a.month AS history_month,(a.month+INTERVAL '1 month')::DATE AS forecast_cutoff_date,
          (a.month+INTERVAL '1 month')::DATE AS target_month,
          a.median_price_per_100 AS history_median_price_per_100,
          b.median_price_per_100 AS target_median_price_per_100,
          CASE WHEN b.median_price_per_100 IS NOT NULL
            THEN b.median_price_per_100/a.median_price_per_100-1 END AS next_month_unit_price_change_fraction,
          a.observed_days AS history_observed_days,b.observed_days AS target_observed_days,
          b.source_product_id IS NOT NULL AS target_observed,
          a.dataset_covers_full_calendar_month AS history_full_calendar_month,
          coalesce(b.dataset_covers_full_calendar_month,false) AS target_full_calendar_month,
          a.dataset_covers_full_calendar_month AND coalesce(b.dataset_covers_full_calendar_month,false)
            AND a.observed_days>=3 AND coalesce(b.observed_days,0)>=3
            AND a.observed_near_both_month_boundaries
            AND coalesce(b.observed_near_both_month_boundaries,false) AS eligible_for_sampled_monthly_price_evaluation,
          'monthly_sampled_median_change_not_verified_shrink_event' AS target_definition,
          'no_automatic_cross_size_or_cross_barcode_bridge' AS identity_scope
        FROM monthly_observations a LEFT JOIN monthly_observations b
          ON a.source_product_id=b.source_product_id AND a.retailer=b.retailer
          AND a.price_basis=b.price_basis AND a.unit_price_basis=b.unit_price_basis AND a.dimension=b.dimension
          AND b.month=(a.month+INTERVAL '1 month')::DATE""")


def run(root: Path, fetch: bool = True) -> dict:
    prices = root / "data/processed/retail_prices.parquet"
    if not prices.exists():
        raise FileNotFoundError("Prepare retail data before monthly outcomes")
    conn = connect(root)
    try:
        prepare_monthly(conn, prices)
        export_query(conn, "SELECT * FROM monthly_observations", root / "data/processed/retail_monthly.parquet")
        export_query(conn, "SELECT * FROM monthly_targets", root / "data/processed/monthly_targets.parquet")
        report = {"target_cadence": "calendar_month", "input_cadence": "weekly_commodities",
            "aggregation": "Median of observed daily unit prices within month, separately by dimension and price basis",
            "monthly_rows": conn.execute("SELECT count(*) FROM monthly_observations").fetchone()[0],
            "next_month_observed_rows": conn.execute("SELECT count(*) FROM monthly_targets WHERE target_observed").fetchone()[0],
            "eligible_sampled_monthly_pairs": conn.execute("SELECT count(*) FROM monthly_targets WHERE eligible_for_sampled_monthly_price_evaluation").fetchone()[0],
            "distinct_eligible_target_months": conn.execute("SELECT count(DISTINCT target_month) FROM monthly_targets WHERE eligible_for_sampled_monthly_price_evaluation").fetchone()[0],
            "eligibility_rule": "Adjacent calendar months; dataset spans both full months; at least 3 observed days per month and observations in first/last 7 days; same listing, price basis and dimension.",
            "limitations": ["Sampled monthly medians do not imply daily continuous coverage.",
                "January and April are partial dataset boundary months, excluded by default.",
                "A large product panel still supplies few independent calendar-month commodity shocks.",
                "Same retailer/name listings are provisional; family reconstruction remains a separate evidence-review task.",
                "No commodity feature or future outcome is used to create history-only inputs.",
                "Missing next-month observations remain null, never zero change."]}
        rows = conn.execute("""SELECT target_month::VARCHAR,count(*) AS pairs,
            count(*) FILTER(WHERE next_month_unit_price_change_fraction>0) AS rises,
            count(*) FILTER(WHERE next_month_unit_price_change_fraction<0) AS falls,
            count(*) FILTER(WHERE next_month_unit_price_change_fraction=0) AS flat
            FROM monthly_targets WHERE eligible_for_sampled_monthly_price_evaluation GROUP BY 1 ORDER BY 1""").fetchall()
        report["eligible_pairs_by_target_month"] = [dict(zip(("target_month","pairs","rises","falls","flat"), row)) for row in rows]
        write_json(root / "data/reports/monthly-audit.json", report)
        return report
    finally:
        conn.close()
