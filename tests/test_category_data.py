"""Meaningful temporal and source-integrity checks, using synthetic fixtures."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from shrinkflation.category_data import _add_months, _build_category_frame, _parse_ons, _snapshot, _weekly_features


class CategoryDataTests(unittest.TestCase):
    def index_fixture(self):
        return {_add_months(date(2015, 1, 1), offset): 100 + offset for offset in range(144)}

    def test_historical_features_ignore_unpublished_and_future_values(self):
        index = self.index_fixture()
        before = _build_category_frame({"chocolate": index}, {}, date(2026, 11, 8))
        target = "2024-01-01"
        row = before.loc[before.target_month == target].iloc[0]
        self.assertEqual(row.forecast_cutoff, "2023-12-08T00:00:00+00:00")
        self.assertEqual(row.latest_known_cpi_month, "2023-10-01")
        changed = {month: (value * 20 if month >= date(2023, 11, 1) else value) for month, value in index.items()}
        after = _build_category_frame({"chocolate": changed}, {}, date(2026, 11, 8))
        other = after.loc[after.target_month == target].iloc[0]
        columns = [column for column in before if column.startswith(("history_", "season_", "baseline_"))]
        pd.testing.assert_series_equal(row[columns], other[columns])
        self.assertEqual(row.label_available_date, "2024-03-01")

    def test_weekly_buffer_and_irrelevant_category(self):
        cutoff = date(2024, 2, 8)
        ends = [date(2023, 8, 4) + timedelta(weeks=number) for number in range(27)]
        values = pd.DataFrame({"week_end": ends, "value": np.arange(100, 127, dtype=float)})
        inputs = {"cocoa_gbp": values}
        before, maximum = _weekly_features(inputs, "chocolate", cutoff)
        self.assertLessEqual(date.fromisoformat(maximum), cutoff - timedelta(days=7))
        future = values.copy()
        future.loc[future.week_end > cutoff - timedelta(days=7), "value"] = 100000
        after, _ = _weekly_features({"cocoa_gbp": future}, "chocolate", cutoff)
        for name, value in before.items():
            self.assertTrue((np.isnan(value) and np.isnan(after[name])) or value == after[name])
        irrelevant, _ = _weekly_features(inputs, "crisps", cutoff)
        self.assertTrue(all(np.isnan(value) for name, value in irrelevant.items() if "cocoa" in name))

    def test_live_month_and_label_missing(self):
        frame = _build_category_frame({"chocolate": self.index_fixture()}, {}, date(2026, 11, 8))
        live = frame.loc[frame.is_live]
        self.assertEqual(len(live), 1)
        self.assertEqual(live.iloc[0].target_month, "2026-12-01")
        self.assertEqual(live.iloc[0].latest_known_cpi_month, "2026-09-01")
        self.assertTrue(np.isnan(live.iloc[0].target_change_pct))
        observed = frame.loc[~frame.is_live]
        self.assertTrue((observed.label_available_date <= "2026-11-08").all())

    def test_csv_excludes_annual_quarter_and_does_not_fill_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"
            path.write_text('"Title","fixture"\n"2015","100"\n"2015 Q1","100"\n"2015 JAN","100"\n"2015 MAR","110"\n')
            index, fields = _parse_ons(path)
            self.assertEqual(len(index), 2)
            frame = _build_category_frame({"chocolate": index}, {}, date(2016, 4, 8))
            self.assertTrue(np.isnan(frame.iloc[-1].baseline_recent))

    def test_immutable_cache_detects_tampering_and_offline_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(FileNotFoundError):
                _snapshot(root, "l79x", True)
            incoming = root / "data/raw/ons-category/incoming/l79x.csv"
            incoming.parent.mkdir(parents=True)
            incoming.write_text('"Title","synthetic fixture"\n"2015 JAN","100"\n')
            snapshot, meta = _snapshot(root, "l79x", True)
            self.assertIn(meta["sha256"], snapshot.name)
            snapshot.write_text("tampered")
            with self.assertRaises(ValueError):
                _snapshot(root, "l79x", True)


if __name__ == "__main__":
    unittest.main()
