import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from shrinkflation.commodities import excel_date, friday_bucket, number, parse_icco


class CommodityTests(unittest.TestCase):
    def test_friday_buckets_never_anticipate_sunday_information(self):
        self.assertEqual(friday_bucket(date(2024, 1, 3)), (date(2023, 12, 30), date(2024, 1, 5)))
        self.assertEqual(friday_bucket(date(2024, 1, 5)), (date(2023, 12, 30), date(2024, 1, 5)))
        self.assertEqual(friday_bucket(date(2024, 1, 7)), (date(2024, 1, 6), date(2024, 1, 12)))

    def test_missing_quotes_are_not_zero_or_interpolated(self):
        for value in (None, "", "n.q.", "#N/A", "…", "nan", "inf"):
            self.assertIsNone(number(value))
        self.assertEqual(number("1,466.24"), 1466.24)
        self.assertEqual(excel_date("45292"), date(2024, 1, 1))

    def test_icco_duplicates_blank_dates_and_publication_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            data = {"data": [["1", "03/01/2024", "1,000", "1200", "1300", "1100"], ["2", "", "", "", "", ""]]}
            for table in (14, 26):
                (folder / f"icco-daily-prices-table{table}.json").write_text(json.dumps(data))
            (folder / "icco-daily-prices-table14.json.metadata.json").write_text('{"sha256":"example"}')
            rows, audit = parse_icco(folder)
            self.assertEqual(len(rows), 4)
            self.assertEqual(audit["duplicate_observations_removed"], 4)
            self.assertEqual(len(audit["invalid_date_rows"]), 2)
            self.assertTrue(all(row["available_at"] is None and not row["eligible_for_backtest"] for row in rows))
            data["data"][0][2] = "999"
            (folder / "icco-daily-prices-table26.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "Conflicting ICCO"):
                parse_icco(folder)


if __name__ == "__main__":
    unittest.main()
