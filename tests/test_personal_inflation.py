"""Synthetic transactions and index fixtures; not consumer/CPI observations."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    from shrinkflation.personal_inflation import PersonalInflationError, analyse_csv_text, personal_inflation
except ImportError:
    spec = importlib.util.spec_from_file_location("personal_inflation", Path(__file__).parents[1] / "src/shrinkflation/personal_inflation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    PersonalInflationError, analyse_csv_text, personal_inflation = module.PersonalInflationError, module.analyse_csv_text, module.personal_inflation


def index_fixture(*, official=False):
    return {"categories": [
        {"id": "chocolate", "name": "Chocolate", "series_id": "fixture-chocolate", "values": {"2025-09": 100, "2026-09": 110}},
        {"id": "crisps", "name": "Crisps", "series_id": "fixture-crisps", "values": {"2025-09": 100, "2026-09": 120}},
    ], "benchmark": {"id": "fixture-benchmark", "name": "Synthetic 50/50 snack benchmark", "synthetic": True,
        "values": {"2025-09": 100, "2026-09": 115}},
        "headline": {"name": "Synthetic official-schema test fixture", "values": {"2025-09": 100, "2026-09": 115}} if official else None,
        "cpih": None}


def signed(rows):
    return "Date,Description,Amount\n" + "\n".join(",".join(row) for row in rows) + "\n"


class PersonalInflationTests(unittest.TestCase):
    def test_hand_computed_weights_and_contributions(self):
        result = analyse_csv_text(signed([("01/09/2026", "DEMO CHOCOLATE SHOP", "-80"), ("02/09/2026", "DEMO CRISPS SHOP", "-20")]), index_fixture())
        self.assertAlmostEqual(result["personal_rate"], .12)
        self.assertAlmostEqual(sum(item["weight"] for item in result["categories"]), 1)
        self.assertAlmostEqual(sum(item["contribution"] for item in result["categories"]), .12)
        self.assertEqual(result["start_month"], "2025-09")
        self.assertEqual(result["end_month"], "2026-09")
        self.assertEqual(result["total_spending_gbp"], 100)
        self.assertIsNone(result["headline_rate"])
        self.assertEqual(result["mode"], "synthetic_demo")

    def test_one_category_matches_its_index_rate(self):
        result = analyse_csv_text(signed([("01/09/2026", "DEMO CRISPS SHOP", "-30")]), index_fixture())
        self.assertAlmostEqual(result["personal_rate"], .2)
        self.assertEqual(result["categories"][0]["weight"], 1)

    def test_synthetic_reference_weights_match_synthetic_benchmark(self):
        # This validates the arithmetic with a toy bundle, not real CPI weights.
        result = analyse_csv_text(signed([("01/09/2026", "DEMO CRISPS SHOP", "-50"), ("02/09/2026", "DEMO CHOCOLATE SHOP", "-50")]), index_fixture())
        self.assertAlmostEqual(result["personal_rate"], result["benchmark_rate"])
        self.assertIsNone(result["headline_rate"])

    def test_future_official_bundle_schema_fallback(self):
        result = analyse_csv_text(signed([("01/09/2026", "TESCO GROCERIES", "-100")]), index_fixture(official=True))
        self.assertEqual(result["mode"], "official_indices")
        self.assertAlmostEqual(result["personal_rate"], result["headline_rate"])
        self.assertAlmostEqual(result["personal_rate"], .15)

    def test_other_is_in_denominator_and_synthetic_fallback(self):
        result = analyse_csv_text(signed([("01/09/2026", "DEMO CHOCOLATE SHOP", "-80"), ("02/09/2026", "TESCO GROCERIES", "-20")]), index_fixture())
        self.assertAlmostEqual(result["personal_rate"], .11)
        self.assertAlmostEqual(result["other_share"], .2)
        self.assertTrue(any("Other spending uses" in warning for warning in result["warnings"]))

    def test_income_refunds_savings_own_transfers_and_cash_excluded(self):
        rows = [("01/09/2026", "DEMO CHOCOLATE SHOP", "-10"), ("01/09/2026", "SALARY PAYROLL", "2000"),
            ("02/09/2026", "OWN ACCOUNT TRANSFER", "-500"), ("02/09/2026", "TRANSFER TO SAVINGS", "-200"),
            ("03/09/2026", "ATM CASH WITHDRAWAL", "-50"), ("03/09/2026", "REFUND", "10")]
        result = analyse_csv_text(signed(rows), index_fixture())
        self.assertEqual(result["total_spending_gbp"], 10)
        self.assertEqual(result["exclusions"]["own_transfer"]["count"], 1)
        self.assertEqual(result["exclusions"]["savings"]["count"], 1)
        self.assertEqual(result["exclusions"]["cash_withdrawal"]["amount_gbp"], 50)
        self.assertTrue(any("Cash withdrawals" in warning for warning in result["warnings"]))

    def test_rent_bank_transfer_is_not_own_account_and_savings_merchant_is_not_move(self):
        text = "Date,Description,Amount,Type\n01/09/2026,BANK TRANSFER DEMO RENT,-700,TRANSFER\n02/09/2026,SAVINGS SUPERMARKET,-20,CARD\n"
        result = analyse_csv_text(text, index_fixture())
        self.assertEqual(result["total_spending_gbp"], 720)
        self.assertEqual(result["other_share"], 1)
        self.assertEqual(result["exclusions"]["own_transfer"]["count"], 0)
        self.assertEqual(result["exclusions"]["savings"]["count"], 0)

    def test_uk_money_separate_columns_semicolon_and_bom(self):
        text = "\ufeffBooking Date;Payee;Money Out;Money In\n01/09/2026;DEMO CHOCOLATE SHOP;Â£1,234.56;\n02/09/2026;SALARY;;2,000.00\n"
        result = analyse_csv_text(text, index_fixture())
        self.assertEqual(result["total_spending_gbp"], 1234.56)
        self.assertEqual(result["exclusions"]["income"]["amount_gbp"], 2000)

    def test_signed_parentheses_type_and_dr_suffix(self):
        for value in ("(£10.00)", "10DR", "-10DR"):
            result = analyse_csv_text(signed([("2026-09-01", "DEMO CHOCOLATE SHOP", value)]), index_fixture())
            self.assertEqual(result["total_spending_gbp"], 10)
        result = analyse_csv_text("Date,Merchant,Amount,Type\n01/09/2026,DEMO CRISPS SHOP,10,DEB\n", index_fixture())
        self.assertEqual(result["total_spending_gbp"], 10)

    def test_positive_only_ambiguous_fails_readably(self):
        with self.assertRaisesRegex(PersonalInflationError, "Positive-only"):
            analyse_csv_text(signed([("01/09/2026", "PRIVATE SENTINEL", "10")]), index_fixture())

    def test_invalid_money_is_not_silently_reinterpreted(self):
        for value in ('"12,34"', "1.234", "1e3", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(PersonalInflationError, "invalid UK monetary"):
                analyse_csv_text(signed([("01/09/2026", "PRIVATE SENTINEL", value)]), index_fixture())

    def test_short_elapsed_coverage_warns_even_across_three_month_bins(self):
        result = analyse_csv_text(signed([("31/01/2026", "DEMO CRISPS SHOP", "-1"), ("01/03/2026", "DEMO CRISPS SHOP", "-1")]), index_fixture())
        self.assertTrue(any("fewer than three" in warning for warning in result["warnings"]))
        self.assertEqual(result["csv_period"]["calendar_months"], 3)

    def test_other_and_no_overlap_warnings(self):
        result = analyse_csv_text(signed([("01/01/2030", "PRIVATE SENTINEL", "-50")]), index_fixture())
        self.assertTrue(any("More than 25%" in warning for warning in result["warnings"]))
        self.assertTrue(any("do not overlap" in warning for warning in result["warnings"]))
        self.assertNotIn("PRIVATE SENTINEL", json.dumps(result))

    def test_empty_malformed_header_amount_or_date_fail_without_description(self):
        for text in ("", "Date,Amount\n01/09/2026,-10\n", "Date,Description,Amount\nBAD,PRIVATE SENTINEL,-10\n", "Date,Description,Amount\n01/09/2026,PRIVATE SENTINEL,nope\n", "Date,Description,Amount\n01/09/2026,PRIVATE SENTINEL,-10,EXTRA\n"):
            with self.subTest(text=text):
                try:
                    analyse_csv_text(text, index_fixture())
                except PersonalInflationError as error:
                    self.assertNotIn("PRIVATE SENTINEL", str(error))
                else:
                    self.fail("Malformed input was accepted")

    def test_missing_year_coverage_stops_without_fabrication(self):
        bundle = index_fixture()
        bundle["categories"][0]["values"].pop("2025-09")
        with self.assertRaisesRegex(PersonalInflationError, "does not reach back 12 months"):
            analyse_csv_text(signed([("01/09/2026", "DEMO CRISPS SHOP", "-30")]), bundle)

    def test_observed_monthly_changes_separate_from_index_result(self):
        rows = []
        for number in range(13):
            year = 2025 + (8 + number) // 12
            month = (8 + number) % 12 + 1
            rows.append((f"05/{month:02d}/{year}", "CARD PAYMENT DEMO CHOCOLATE CLUB REF123456", "-10" if number < 12 else "-11"))
        result = analyse_csv_text(signed(rows), index_fixture())
        self.assertAlmostEqual(result["personal_rate"], .1)
        self.assertEqual(len(result["observed_price_changes"]), 1)
        observed = result["observed_price_changes"][0]
        self.assertAlmostEqual(observed["change"], .1)
        self.assertEqual(observed["from_month"], "2025-09")
        self.assertEqual(observed["to_month"], "2026-09")
        self.assertNotIn("REF", observed["merchant"])
        self.assertEqual(observed["merchant"], "DEMO CHOCOLATE CLUB")

    def test_variable_multiple_purchases_are_not_recurring_bills(self):
        rows = []
        for number in range(13):
            year = 2025 + (8 + number) // 12
            month = (8 + number) % 12 + 1
            rows.extend([(f"05/{month:02d}/{year}", "DEMO CRISPS SHOP", "-10"), (f"15/{month:02d}/{year}", "DEMO CRISPS SHOP", "-10")])
        result = analyse_csv_text(signed(rows), index_fixture())
        self.assertEqual(result["observed_price_changes"], [])

    def test_synthetic_column_and_local_file_entrypoint_cp1252(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "bank.csv").write_bytes("Date,Description,Debit,Synthetic\n01/09/2026,DEMO CRISPS SHOP,£10,TRUE\n".encode("cp1252"))
            (path / "indices.json").write_text(json.dumps(index_fixture()))
            result = personal_inflation(path / "bank.csv", path / "indices.json")
        self.assertTrue(result["input_is_synthetic"])
        self.assertEqual(result["total_spending_gbp"], 10)

    def test_invalid_encoding_has_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bank.csv"
            path.write_bytes(b"\x81")
            with self.assertRaisesRegex(PersonalInflationError, "unsupported text encoding"):
                personal_inflation(path)

    def test_duplicate_header_is_ambiguous(self):
        text = "Date,Description,Amount,Value\n01/09/2026,DEMO CRISPS SHOP,-10,-20\n"
        with self.assertRaisesRegex(PersonalInflationError, "multiple possible amount"):
            analyse_csv_text(text, index_fixture())

    def test_matching_sourced_headline_reference_sets_comparison_and_other_fallback(self):
        bundle = index_fixture()
        bundle["mode"] = "synthetic_demo"
        reference = {"start_month": "2025-09", "end_month": "2026-09", "cpi_rate": .035, "cpih_rate": .036,
            "release_date": "2026-10-21", "source_url": "https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/september2026"}
        bundle["headline_reference"] = reference
        result = analyse_csv_text(signed([("01/09/2026", "DEMO CHOCOLATE SHOP", "-80"), ("02/09/2026", "TESCO", "-20")]), bundle)
        self.assertAlmostEqual(result["personal_rate"], .8 * .1 + .2 * .035)
        self.assertEqual(result["headline_rate"], .035)
        self.assertEqual(result["cpih_rate"], .036)
        self.assertAlmostEqual(result["benchmark_rate"], .15)
        self.assertEqual(result["headline_reference"], reference)
        self.assertEqual(result["mode"], "synthetic_demo")
        other = next(item for item in result["categories"] if item["category_id"] == "other")
        self.assertEqual(other["rate"], .035)
        self.assertEqual(other["index_id"], "ons_cpi_headline_reference")
        self.assertIn("3.5% headline CPI", result["summary"])
        self.assertFalse(any("No matching official" in warning for warning in result["warnings"]))
        self.assertTrue(any("broad household-category coverage" in warning for warning in result["warnings"]))

    def test_sourced_headline_reference_wrong_period_is_never_reused(self):
        bundle = index_fixture()
        bundle["headline_reference"] = {"start_month": "2024-09", "end_month": "2025-09", "cpi_rate": .035, "cpih_rate": .036}
        result = analyse_csv_text(signed([("01/09/2026", "TESCO", "-100")]), bundle)
        self.assertIsNone(result["headline_reference"])
        self.assertIsNone(result["headline_rate"])
        self.assertIsNone(result["cpih_rate"])
        self.assertAlmostEqual(result["personal_rate"], .15)
        self.assertTrue(any("does not match" in warning for warning in result["warnings"]))

    def test_sourced_headline_reference_invalid_rates_are_not_used(self):
        for rate in (True, float("nan"), float("inf"), -1, "3.5%"):
            bundle = index_fixture()
            bundle["headline_reference"] = {"start_month": "2025-09", "end_month": "2026-09", "cpi_rate": rate, "cpih_rate": .036}
            with self.subTest(rate=rate):
                result = analyse_csv_text(signed([("01/09/2026", "TESCO", "-100")]), bundle)
                self.assertIsNone(result["headline_reference"])
                self.assertAlmostEqual(result["personal_rate"], .15)

    def test_unreadable_files_have_clear_errors(self):
        with self.assertRaisesRegex(PersonalInflationError, "CSV could not be read"):
            personal_inflation("/not/a/statement.csv")


if __name__ == "__main__":
    unittest.main()
