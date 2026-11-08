"""Check generated synthetic statements against saved, observed ONS indices.

These tests distinguish the real price-index inputs from fabricated transaction
scenarios. All numerical expectations below are independent, hand-computed
arithmetic rather than the feature's own parsing or weighting helpers.
"""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from shrinkflation.personal_inflation import personal_inflation

ROOT = Path(__file__).resolve().parents[1]
CHOCOLATE_RATE = Decimal("153.8") / Decimal("154.9") - 1
CRISPS_RATE = Decimal("161.4") / Decimal("154.4") - 1
BENCHMARK_RATE = (CHOCOLATE_RATE + CRISPS_RATE) / 2
HEADLINE_CPI_RATE = Decimal(".035")
HEADLINE_CPIH_RATE = Decimal(".036")


def expected_rate(chocolate, crisps, other="0"):
    chocolate, crisps, other = map(Decimal, (chocolate, crisps, other))
    return float((chocolate * CHOCOLATE_RATE + crisps * CRISPS_RATE + other * HEADLINE_CPI_RATE) / (chocolate + crisps + other))


class PersonalDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle_path = ROOT / "data/curated/personal-inflation-demo.json"
        cls.bundle = json.loads(cls.bundle_path.read_text())
        cls.samples = ROOT / "data/synthetic/personal-inflation"

    def test_all_282_observed_index_values_and_checksums_match_raw_snapshots(self):
        months = {name: number for number, name in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
        count = 0
        for category in self.bundle["categories"]:
            with self.subTest(category=category["id"]):
                source = ROOT / category["source_file"]
                self.assertTrue(source.resolve().is_relative_to(ROOT.resolve()))
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), category["source_sha256"])
                observed = {}
                # Independently read the archived ONS CSV; annual/quarterly rows
                # must never be interpolated or copied into the monthly values.
                for row in csv.reader(io.StringIO(source.read_text(encoding="utf-8-sig"))):
                    if len(row) < 2:
                        continue
                    match = re.fullmatch(r"(\d{4}) ([A-Z]{3})", row[0])
                    if match and match[2] in months:
                        observed[f"{match[1]}-{months[match[2]]:02d}"] = float(Decimal(row[1]))
                self.assertEqual(category["data_kind"], "observed_ons")
                self.assertEqual(category["values"], observed)
                self.assertEqual(len(observed), 141)
                self.assertEqual(min(observed), "2015-01")
                self.assertEqual(max(observed), "2026-09")
                count += len(observed)
        self.assertEqual(count, 282)

    def test_synthetic_benchmark_is_rebased_and_never_claimed_official(self):
        self.assertEqual(self.bundle["mode"], "synthetic_demo")
        self.assertIsNone(self.bundle["headline"])
        self.assertIsNone(self.bundle["cpih"])
        benchmark = self.bundle["benchmark"]
        self.assertTrue(benchmark["synthetic"])
        self.assertEqual(benchmark["base_month"], "2025-09")
        self.assertEqual(benchmark["reference_weights"], {"chocolate": .5, "crisps": .5})
        for month, actual in benchmark["values"].items():
            expected = sum(Decimal("50") * Decimal(str(category["values"][month])) / Decimal(str(category["values"]["2025-09"])) for category in self.bundle["categories"])
            self.assertAlmostEqual(actual, float(expected), places=11)
        self.assertAlmostEqual(benchmark["values"]["2026-09"] / benchmark["values"]["2025-09"] - 1, float(BENCHMARK_RATE))
        self.assertTrue(any("synthetic" in warning.lower() for warning in self.bundle["limitations"]))

    def test_official_annual_reference_has_matching_period_and_source(self):
        reference = self.bundle["headline_reference"]
        self.assertEqual((reference["start_month"], reference["end_month"]), ("2025-09", "2026-09"))
        self.assertEqual(reference["cpi_rate"], float(HEADLINE_CPI_RATE))
        self.assertEqual(reference["cpih_rate"], float(HEADLINE_CPIH_RATE))
        self.assertEqual(reference["release_date"], "2026-10-21")
        self.assertEqual(reference["source_url"], "https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/september2026")
        self.assertIsNone(self.bundle["headline"])
        self.assertIsNone(self.bundle["cpih"])

    def test_every_sample_is_explicitly_synthetic_and_public_copy_is_identical(self):
        self.assertEqual({sample["id"] for sample in self.bundle["samples"]}, {"snack-club", "mixed-household", "short-statement"})
        for sample in self.bundle["samples"]:
            with self.subTest(sample=sample["id"]):
                self.assertTrue(sample["synthetic"])
                path = self.samples / (sample["id"] + ".csv")
                public = ROOT / "data/app-public" / sample["path"].lstrip("/")
                self.assertEqual(path.read_bytes(), public.read_bytes())
                text = path.read_text(encoding="utf-8-sig")
                delimiter = ";" if sample["id"] == "short-statement" else ","
                rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
                self.assertTrue(rows)
                self.assertTrue(all(row["Synthetic"] == "true" for row in rows))
                result = personal_inflation(path, self.bundle_path)
                self.assertTrue(result["input_is_synthetic"])
                self.assertEqual(result["headline_rate"], float(HEADLINE_CPI_RATE))
                self.assertEqual(result["cpih_rate"], float(HEADLINE_CPIH_RATE))

    def test_snack_club_hand_computed_oracle_and_separate_observed_increase(self):
        result = personal_inflation(self.samples / "snack-club.csv", self.bundle_path)
        categories = {item["category_id"]: item for item in result["categories"]}
        # Twelve £2.75 payments plus one £3.30; thirteen £1.50 payments.
        self.assertEqual(result["total_spending_gbp"], 55.8)
        self.assertEqual(categories["chocolate"]["spending_gbp"], 36.3)
        self.assertEqual(categories["crisps"]["spending_gbp"], 19.5)
        self.assertAlmostEqual(categories["chocolate"]["weight"], 36.3 / 55.8)
        self.assertAlmostEqual(result["personal_rate"], expected_rate("36.3", "19.5"))
        self.assertAlmostEqual(result["benchmark_rate"], float(BENCHMARK_RATE))
        self.assertEqual(result["other_share"], 0)
        self.assertEqual(result["csv_period"]["calendar_months"], 13)
        self.assertEqual(result["exclusions"]["income"], {"count": 13, "amount_gbp": 31200})
        self.assertEqual(result["exclusions"]["refund"], {"count": 1, "amount_gbp": 1.5})
        self.assertEqual(result["exclusions"]["own_transfer"], {"count": 13, "amount_gbp": 2600})
        self.assertEqual(result["exclusions"]["savings"], {"count": 13, "amount_gbp": 3900})
        self.assertEqual(result["exclusions"]["cash_withdrawal"], {"count": 13, "amount_gbp": 260})
        observed = {item["merchant"]: item for item in result["observed_price_changes"]}
        self.assertEqual(set(observed), {"DEMO CHOCOLATE CLUB", "DEMO CRISPS CLUB"})
        self.assertAlmostEqual(observed["DEMO CHOCOLATE CLUB"]["change"], .2)
        self.assertEqual(observed["DEMO CRISPS CLUB"]["change"], 0)
        self.assertTrue(all(item["occurrences"] == 13 for item in observed.values()))
        self.assertTrue(all((item["from_month"], item["to_month"]) == ("2025-09", "2026-09") for item in observed.values()))

    def test_mixed_household_hand_computed_oracle_keeps_rent_and_generic_supermarket_other(self):
        result = personal_inflation(self.samples / "mixed-household.csv", self.bundle_path)
        categories = {item["category_id"]: item for item in result["categories"]}
        # Twelve months × (£925 rent + £80 supermarket + £85 energy).
        self.assertEqual(result["total_spending_gbp"], 13137.6)
        self.assertEqual(categories["other"]["spending_gbp"], 13080)
        self.assertEqual(categories["chocolate"]["spending_gbp"], 39.6)
        self.assertEqual(categories["crisps"]["spending_gbp"], 18)
        self.assertAlmostEqual(result["other_share"], 13080 / 13137.6)
        self.assertAlmostEqual(result["personal_rate"], expected_rate("39.6", "18", "13080"))
        self.assertTrue(any("unreliable" in warning.lower() for warning in result["warnings"]))
        self.assertEqual(result["observed_price_changes"], [])
        self.assertEqual(result["exclusions"]["own_transfer"], {"count": 12, "amount_gbp": 3000})
        self.assertEqual(result["exclusions"]["income"], {"count": 12, "amount_gbp": 37200})
        self.assertEqual(result["exclusions"]["cash_withdrawal"], {"count": 12, "amount_gbp": 360})

    def test_short_statement_hand_computed_oracle_and_warning(self):
        result = personal_inflation(self.samples / "short-statement.csv", self.bundle_path)
        categories = {item["category_id"]: item for item in result["categories"]}
        self.assertEqual(result["total_spending_gbp"], 16.3)
        self.assertEqual(categories["other"]["spending_gbp"], 10)
        self.assertEqual(categories["chocolate"]["spending_gbp"], 3.3)
        self.assertEqual(categories["crisps"]["spending_gbp"], 3)
        self.assertAlmostEqual(result["personal_rate"], expected_rate("3.3", "3", "10"))
        self.assertEqual(result["exclusions"]["savings"]["count"], 0)
        self.assertEqual(result["exclusions"]["income"], {"count": 1, "amount_gbp": 1500})
        self.assertTrue(any("three" in warning.lower() for warning in result["warnings"]))
        self.assertEqual(result["observed_price_changes"], [])

    def _cli(self, path):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-B", "-m", "shrinkflation.cli", "personal-inflation", str(path),
            "--json", "--indices", str(self.bundle_path), "--root", str(ROOT)], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30, check=False)

    def test_cli_returns_structured_result(self):
        process = self._cli(self.samples / "snack-club.csv")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        result = json.loads(process.stdout)
        self.assertAlmostEqual(result["personal_rate"], expected_rate("36.3", "19.5"))
        self.assertIn("demo", result["summary"].lower())
        self.assertIn("3.5% headline CPI", result["summary"])
        self.assertNotIn("DEMO EMPLOYER", process.stdout)
        self.assertNotIn("Traceback", process.stdout)

    def test_cli_empty_csv_fails_clearly_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            path.write_text("")
            process = self._cli(path)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("CSV is empty", process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_cli_malformed_csv_error_does_not_leak_description(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.csv"
            path.write_text("Date,Description,Amount\nBAD,PRIVATE SENTINEL MUST NEVER LEAK,-10\n")
            process = self._cli(path)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("invalid date", process.stderr)
        self.assertNotIn("PRIVATE SENTINEL", process.stderr)
        self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()
