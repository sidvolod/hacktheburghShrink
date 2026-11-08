"""Synthetic fixtures only: these tests are not observations or backtest data."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rsi_features import CPI_FEATURE, build_rsi_features, subtract_calendar_months, wilder_rsi


def weekly(values, start="2024-01-07"):
    return pd.DataFrame({"week_end": pd.date_range(start, periods=len(values), freq="7D").date,
                         "value": np.asarray(values, dtype=float)})


def monthly(values, start="2023-01-01"):
    return dict(zip(pd.date_range(start, periods=len(values), freq="MS").date,
                    np.asarray(values, dtype=float)))


def base(cutoff="2024-04-21", category="chocolate", latest="2024-02-01"):
    return pd.DataFrame({"category_id": pd.Series([category], dtype="category"),
                         "target_month": ["2024-05-01"],
                         "forecast_cutoff": [cutoff + "T00:00:00+01:00"],
                         "latest_known_cpi_month": [latest],
                         "target_change_pct": [np.nan],
                         "is_live": pd.Series([True], dtype="boolean"),
                         "untouched_int": pd.Series([7], dtype="Int64")}, index=[0])


def feature_audit(audit, name):
    return audit.loc[audit.feature_name == name].iloc[0]


class WilderRsiTests(unittest.TestCase):
    def test_known_sma_seed_and_wilder_numerical_fixture(self):
        # Fixed illustrative prices; expected values independently specify the
        # SMA seed and subsequent Wilder recurrence, rather than pandas ewm.
        values = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10,
                  45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
                  46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21]
        levels = pd.Series(values, index=pd.date_range("2020-01-05", periods=len(values), freq="7D"))
        result = wilder_rsi(levels, 14, "weekly")
        self.assertTrue(result.iloc[:14].isna().all())
        expected = [70.46413502109705, 66.24961855355505, 66.48094183471265,
                    69.34685316290866, 66.29471265892624, 57.91502067008556,
                    62.8807183099624]
        np.testing.assert_allclose(result.iloc[14:], expected, rtol=1e-12, atol=1e-12)

    def test_prefix_future_invariance(self):
        levels = pd.Series([100 + i + (i % 3) * 2 for i in range(30)],
                           index=pd.date_range("2020-01-05", periods=30, freq="7D"))
        result = wilder_rsi(levels, 14, "weekly")
        prefix = wilder_rsi(levels.iloc[:20], 14, "weekly")
        pd.testing.assert_series_equal(result.iloc[:20], prefix)
        changed = levels.copy()
        changed.iloc[20:] *= 1000
        pd.testing.assert_series_equal(wilder_rsi(changed, 14, "weekly").iloc[:20], prefix)

    def test_weekly_gap_resets_entire_chain(self):
        dates = pd.date_range("2024-01-07", periods=31, freq="7D")
        levels = pd.Series(np.arange(100, 131), index=dates).drop(dates[15])
        result = wilder_rsi(levels, 14, "weekly")
        self.assertEqual(result.loc[dates[14]], 100)
        self.assertTrue(result.loc[dates[16]:dates[29]].isna().all())
        self.assertEqual(result.loc[dates[30]], 100)

    def test_irregular_week_is_not_treated_as_contiguous(self):
        dates = list(pd.date_range("2024-01-07", periods=16, freq="7D"))
        dates[-1] += pd.Timedelta(days=1)
        result = wilder_rsi(pd.Series(np.arange(100, 116), index=dates), 14, "weekly")
        self.assertEqual(result.iloc[-2], 100)
        self.assertTrue(pd.isna(result.iloc[-1]))

    def test_monthly_gap_and_invalid_value_reset(self):
        dates = pd.date_range("2023-01-01", periods=15, freq="MS")
        levels = pd.Series(np.arange(100, 115, dtype=float), index=dates).drop(dates[7])
        result = wilder_rsi(levels, 6, "monthly")
        self.assertEqual(result.loc[dates[6]], 100)
        self.assertTrue(result.loc[dates[8]:dates[13]].isna().all())
        self.assertEqual(result.loc[dates[14]], 100)
        levels = pd.Series(np.arange(100, 115, dtype=float), index=dates)
        levels.iloc[7] = np.nan
        result = wilder_rsi(levels, 6, "monthly")
        self.assertTrue(result.iloc[7:14].isna().all())
        self.assertEqual(result.iloc[14], 100)

    def test_flat_rising_falling_and_minimum_samples(self):
        dates = pd.date_range("2024-01-07", periods=15, freq="7D")
        for values, expected in [(np.repeat(100, 15), 50),
                                 (np.arange(100, 115), 100),
                                 (np.arange(115, 100, -1), 0)]:
            result = wilder_rsi(pd.Series(values, index=dates), 14, "weekly")
            self.assertTrue(result.iloc[:14].isna().all())
            self.assertEqual(result.iloc[-1], expected)

    def test_duplicate_dates_and_invalid_parameters_rejected(self):
        duplicate = pd.Series([100, 101], index=["2024-01-07", "2024-01-07"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            wilder_rsi(duplicate, 14, "weekly")
        with self.assertRaises(ValueError):
            wilder_rsi(pd.Series(dtype=float), 0, "weekly")


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.cpi = {"chocolate": monthly(np.arange(100, 114)),
                    "crisps": monthly(np.arange(100, 114))}
        self.source = weekly(np.arange(100, 115))  # Final week ends 14 Apr.

    def test_seven_and_fourteen_day_publication_buffers(self):
        name = "commodity_cocoa_gbp_rsi_14w"
        before, audit, _ = build_rsi_features(base("2024-04-20"), self.cpi, {"cocoa_gbp": self.source})
        self.assertTrue(pd.isna(before.loc[0, name]))
        self.assertEqual(feature_audit(audit, name).contiguous_samples, 14)
        at_release, audit, _ = build_rsi_features(base("2024-04-21"), self.cpi, {"cocoa_gbp": self.source})
        self.assertEqual(at_release.loc[0, name], 100)
        self.assertEqual(feature_audit(audit, name).source_available_date, "2024-04-21")
        maize = "commodity_maize_us_gulf_rsi_14w"
        before, _, _ = build_rsi_features(base("2024-04-27", "crisps"), self.cpi,
                                          {"maize_us_gulf": self.source})
        after, audit, _ = build_rsi_features(base("2024-04-28", "crisps"), self.cpi,
                                            {"maize_us_gulf": self.source})
        self.assertTrue(pd.isna(before.loc[0, maize]))
        self.assertEqual(after.loc[0, maize], 100)
        self.assertEqual(feature_audit(audit, maize).availability_buffer_days, 14)

    def test_staleness_boundary_and_audit(self):
        name = "commodity_cocoa_gbp_rsi_14w"
        okay, _, _ = build_rsi_features(base("2024-05-19"), self.cpi, {"cocoa_gbp": self.source})
        stale, audit, _ = build_rsi_features(base("2024-05-20"), self.cpi, {"cocoa_gbp": self.source})
        self.assertEqual(okay.loc[0, name], 100)
        self.assertTrue(pd.isna(stale.loc[0, name]))
        record = feature_audit(audit, name)
        self.assertEqual(record.status, "stale")
        self.assertEqual(record.observation_end, "2024-04-14")
        self.assertEqual(record.source_age_days, 36)

    def test_lagged_issue_rechecks_earlier_buffer_not_current_data(self):
        source = weekly([100 + i + (i % 3) * 3 for i in range(29)])
        enhanced, audit, _ = build_rsi_features(base("2024-07-21"), self.cpi, {"cocoa_gbp": source})
        name = "commodity_cocoa_gbp_rsi_14w_issue_lag3m"
        record = feature_audit(audit, name)
        self.assertEqual(record.effective_cutoff, "2024-04-21")
        self.assertEqual(record.observation_end, "2024-04-14")
        self.assertEqual(record.source_available_date, "2024-04-21")
        earlier, _, _ = build_rsi_features(base("2024-04-21"), self.cpi, {"cocoa_gbp": source})
        self.assertEqual(enhanced.loc[0, name], earlier.loc[0, "commodity_cocoa_gbp_rsi_14w"])
        self.assertEqual(subtract_calendar_months(date(2024, 5, 31), 3), date(2024, 2, 29))

    def test_utc_and_london_same_instant_have_same_cutoff_features(self):
        london = base("2024-04-21")
        utc = london.copy(deep=True)
        utc["forecast_cutoff"] = pd.Series([pd.Timestamp("2024-04-20T23:00:00Z")], index=utc.index)
        first, first_audit, _ = build_rsi_features(london, self.cpi, {"cocoa_gbp": self.source})
        second, second_audit, _ = build_rsi_features(utc, self.cpi, {"cocoa_gbp": self.source})
        features = [name for name in first if name not in london]
        pd.testing.assert_frame_equal(first[features], second[features])
        # The original cutoff representations stay untouched in their frames
        # and audit columns; all derived availability decisions are equivalent.
        columns = [name for name in first_audit if name != "forecast_cutoff"]
        pd.testing.assert_frame_equal(first_audit[columns], second_audit[columns])
        self.assertEqual(feature_audit(second_audit, "commodity_cocoa_gbp_rsi_14w").effective_cutoff,
                         "2024-04-21")

    def test_live_cpi_ceiling_ignores_unreleased_future_levels(self):
        indices = {"chocolate": monthly(np.arange(100, 124), "2025-01-01")}
        row = base("2026-12-08", latest="2026-12-01")  # Deliberately overclaims latest.
        original, audit, _ = build_rsi_features(row, indices, {})
        self.assertEqual(original.loc[0, CPI_FEATURE], 100)
        record = feature_audit(audit, CPI_FEATURE)
        self.assertEqual(record.observation_end, "2026-10-01")
        self.assertEqual(record.source_available_date, "2026-12-01")
        self.assertEqual(record.cpi_ceiling_month, "2026-10-01")
        indices["chocolate"][date(2026, 11, 1)] = 1e9
        indices["chocolate"][date(2026, 12, 1)] = 1
        changed, changed_audit, _ = build_rsi_features(row, indices, {})
        pd.testing.assert_frame_equal(original, changed)
        pd.testing.assert_frame_equal(audit, changed_audit)

    def test_future_weekly_data_and_target_label_cannot_change_features(self):
        source = weekly(np.arange(100, 125))
        row = base()
        before, audit, _ = build_rsi_features(row, self.cpi, {"cocoa_gbp": source})
        changed_source = source.copy()
        changed_source.loc[changed_source.week_end > date(2024, 4, 14), "value"] *= 1000
        row["target_change_pct"] = 9999.0
        after, audit_after, _ = build_rsi_features(row, self.cpi, {"cocoa_gbp": changed_source})
        new_names = [name for name in before if name not in row]
        pd.testing.assert_frame_equal(before[new_names], after[new_names])
        pd.testing.assert_frame_equal(audit, audit_after)

    def test_preserves_every_base_column_dtype_index_and_missing_row(self):
        row = base()
        row.index = pd.Index([17], name="original_index")
        frozen = row.copy(deep=True)
        enhanced, audit, groups = build_rsi_features(row, self.cpi, {})
        pd.testing.assert_frame_equal(enhanced[frozen.columns], frozen, check_exact=True)
        pd.testing.assert_frame_equal(row, frozen, check_exact=True)
        self.assertEqual(len(enhanced), 1)
        self.assertEqual(len(audit), len(enhanced.columns) - len(frozen.columns))
        self.assertTrue(all(name in enhanced for name in groups["chocolate"]["rsi_only"]))
        self.assertNotIn("commodity_maize_us_gulf_rsi_14w", groups["chocolate"]["rsi_only"])
        self.assertEqual(feature_audit(audit, "commodity_maize_us_gulf_rsi_14w").status, "inapplicable")

    def test_missing_cpi_endpoint_is_missing_not_stale_fallback(self):
        del self.cpi["chocolate"][date(2024, 2, 1)]
        enhanced, audit, _ = build_rsi_features(base(), self.cpi, {})
        self.assertTrue(pd.isna(enhanced.loc[0, CPI_FEATURE]))
        self.assertEqual(feature_audit(audit, CPI_FEATURE).status, "missing_cpi_endpoint")


if __name__ == "__main__":
    unittest.main()
