"""Weekly commodity summaries at monthly cutoffs, with strict timing kept separate."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import connect, export_query, sql_literal, write_json


def prepare_features(conn, weekly: Path, cutoffs: list[str]) -> None:
    conn.execute(f"CREATE OR REPLACE TEMP VIEW weekly AS SELECT * FROM read_parquet({sql_literal(weekly)})")
    conn.execute("CREATE OR REPLACE TEMP TABLE cutoffs(cutoff_date DATE)")
    conn.executemany("INSERT INTO cutoffs VALUES (?)", [(value,) for value in sorted(set(cutoffs))])
    conn.execute("""CREATE OR REPLACE TEMP TABLE feature_values AS
        WITH modes AS (
          SELECT 'exploratory_observation_dates_only' AS feature_mode
          UNION ALL SELECT 'strict_known_publication'
        ), combinations AS (
          SELECT * FROM cutoffs CROSS JOIN (SELECT DISTINCT series_id,commodity,unit,currency FROM weekly) s CROSS JOIN modes
        ), accepted AS (
          SELECT c.cutoff_date,c.feature_mode,w.* FROM combinations c JOIN weekly w
            ON c.series_id=w.series_id AND w.week_end<c.cutoff_date
            AND (c.feature_mode='exploratory_observation_dates_only' OR
              (w.publication_known AND w.eligible_for_backtest AND w.available_at IS NOT NULL
                AND w.available_at<=c.cutoff_date::TIMESTAMP AT TIME ZONE 'Europe/London'))
        ), accepted_changes AS (
          SELECT a.*,CASE WHEN b.value>0 THEN 100*(a.value/b.value-1) END AS cohort_weekly_change_pct
          FROM accepted a LEFT JOIN accepted b ON a.cutoff_date=b.cutoff_date AND a.feature_mode=b.feature_mode
            AND a.series_id=b.series_id AND b.week_end=a.week_end-7
        ), latest AS (
          SELECT cutoff_date,feature_mode,series_id,max(week_end) AS latest_week_end
          FROM accepted GROUP BY ALL
        ), statistics AS (
          SELECT a.cutoff_date,a.feature_mode,a.series_id,l.latest_week_end,
            max(a.value) FILTER(WHERE a.week_end=l.latest_week_end) AS latest_weekly_value,
            max(a.value) FILTER(WHERE a.week_end=l.latest_week_end-28) AS value_four_weeks_before,
            avg(a.value) FILTER(WHERE a.week_end>a.cutoff_date-28) AS mean_4w,
            stddev_samp(a.cohort_weekly_change_pct) FILTER(WHERE a.week_end>a.cutoff_date-84) AS weekly_change_stddev_pct_12w,
            count(*) FILTER(WHERE a.week_end>a.cutoff_date-28) AS observed_weeks_4w,
            count(*) FILTER(WHERE a.week_end>a.cutoff_date-84) AS observed_weeks_12w
          FROM accepted_changes a JOIN latest l USING(cutoff_date,feature_mode,series_id) GROUP BY ALL
        )
        SELECT c.*,c.cutoff_date::TIMESTAMP AT TIME ZONE 'Europe/London' AS cutoff_at,
          s.latest_week_end,s.latest_weekly_value,s.mean_4w,
          CASE WHEN s.value_four_weeks_before>0 AND s.latest_week_end>=c.cutoff_date-14
            THEN s.latest_weekly_value/s.value_four_weeks_before-1 END AS change_4w_fraction,
          s.weekly_change_stddev_pct_12w,
          coalesce(s.observed_weeks_4w,0) AS observed_weeks_4w,
          coalesce(s.observed_weeks_12w,0) AS observed_weeks_12w,
          c.feature_mode='strict_known_publication' AND s.latest_week_end>=c.cutoff_date-14
            AND coalesce(s.observed_weeks_4w,0)>=3 AS eligible_for_backtest,
          'weekly inputs at monthly cutoff; no product exposure weights inferred' AS feature_definition
        FROM combinations c LEFT JOIN statistics s USING(cutoff_date,feature_mode,series_id)""")


def run(root: Path, fetch: bool = True) -> dict:
    processed = root / "data/processed"
    conn = connect(root)
    try:
        cutoffs = [str(row[0]) for row in conn.execute(f"SELECT DISTINCT forecast_cutoff_date FROM read_parquet({sql_literal(processed / 'monthly_targets.parquet')})").fetchall()]
        cutoffs.append(datetime.now(ZoneInfo("Europe/London")).date().isoformat())
        prepare_features(conn,processed / "commodity_weekly.parquet",cutoffs)
        export_query(conn,"SELECT * FROM feature_values",processed / "commodity_monthly_features.parquet")
        report = {"cutoffs":sorted(set(cutoffs)),
            "rows":conn.execute("SELECT count(*) FROM feature_values").fetchone()[0],
            "strict_eligible_rows":conn.execute("SELECT count(*) FROM feature_values WHERE eligible_for_backtest").fetchone()[0],
            "exploratory_rows_with_observations":conn.execute("SELECT count(*) FROM feature_values WHERE feature_mode='exploratory_observation_dates_only' AND latest_weekly_value IS NOT NULL").fetchone()[0],
            "limitations":["Historical quotes do not establish their publication or revision-vintage timing.",
                "Exploratory rows must not be reported as leakage-safe backtest features.",
                "Strict rows stay empty/null when documented availability is unknown.",
                "Features retain series units/currencies; no assumed manufacturer cost weights.",
                "Oilseed prices are not crude edible-oil prices; missing sugar/dairy weekly feeds are not interpolated from monthly data."]}
        write_json(root / "data/reports/features-audit.json",report)
        return report
    finally:
        conn.close()
