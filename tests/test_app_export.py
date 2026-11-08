"""Synthetic local fixtures for export invariants; never observed demo evidence."""
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from shrinkflation.app_export import (
    RETAIL_SOURCE, export_comparisons, export_histories, initial_cases, portable_public_metadata, run,
)


def fixture_prices():
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE app_prices(
        source_product_id VARCHAR, product_name_raw VARCHAR, retailer VARCHAR,
        observation_id VARCHAR, observation_date DATE, price_gbp DOUBLE,
        total_mass_g DOUBLE, unit_price_eligible BOOLEAN, variable_weight_name BOOLEAN)""")
    connection.executemany("""INSERT INTO app_prices VALUES (?,?,?,?,?,?,?,?,?)""", [
        ("fixture-doritos-sains", "Doritos Cool Original Tortilla Chips 180g", "Sainsbury's", "ds-1", "2024-01-10", 1.80, 180, True, False),
        ("fixture-doritos-sains", "Doritos Cool Original Tortilla Chips 180g", "Sainsbury's", "ds-2", "2024-02-10", 1.98, 180, True, False),
        ("fixture-doritos-sains", "Doritos Cool Original Tortilla Chips 180g", "Sainsbury's", "ds-3", "2024-04-13", 2.16, 180, True, False),
        ("fixture-doritos-tesco", "Doritos Cool Original Tortilla Chips 180g", "Tesco", "dt-1", "2024-04-13", 1.80, 180, True, False),
        # Cheap prior-day, missing-mass, variable-weight and invalid prices cannot
        # silently become same-day comparable observations.
        ("fixture-prior-date", "Doritos Tortilla Chips 200g", "Sainsbury's", "old-1", "2024-04-12", .10, 200, True, False),
        ("fixture-missing-mass", "Doritos Tortilla Chips", "Sainsbury's", "null-mass", "2024-04-13", .10, None, True, False),
        ("fixture-variable-mass", "Doritos Tortilla Chips approx 180g", "Sainsbury's", "variable", "2024-04-13", .10, 180, True, True),
        ("fixture-invalid-price", "Doritos Tortilla Chips 180g", "Sainsbury's", "bad", "2024-04-13", None, 180, False, False),
        ("fixture-snickers-tesco", "Snickers Milk Chocolate Bars 4 x 41.7g", "Tesco", "sn-1", "2024-04-13", 2, 166.8, True, False),
        ("fixture-ice-cream", "Doritos Ice Cream 180g", "Sainsbury's", "ice", "2024-04-13", .10, 180, True, False),
        ("fixture-dessert", "Cadbury Dairy Milk Pots Of Joy Chocolate Dessert 240g", "Tesco", "dessert", "2024-04-13", .10, 240, True, False),
        ("fixture-cereal", "Nestle Kit Kat Cereal 330g", "Tesco", "cereal", "2024-04-13", .10, 330, True, False),
        ("fixture-dip", "Doritos Hot Salsa Dip 300g", "Sainsbury's", "dip", "2024-04-13", .10, 300, True, False),
        ("fixture-dippers", "Doritos Dippers Tortilla Chips 230g", "Tesco", "dippers", "2024-04-13", 2.30, 230, True, False),
        ("fixture-hot-chocolate", "Maltesers Malty Hot Chocolate 350g", "Tesco", "hot-chocolate", "2024-04-13", .10, 350, True, False),
        ("fixture-toffees", "Walkers Salted Caramel Toffees Bag 150g", "Tesco", "toffee", "2024-04-13", .10, 150, True, False),
        ("fixture-nuts", "Walkers Coated Peanuts Cheese Sharing Bag 175g", "Sainsbury's", "nuts", "2024-04-13", .10, 175, True, False),
    ])
    return connection


class AppExportTests(unittest.TestCase):
    def test_histories_preserve_source_listing_name_dates_and_independent_scope(self):
        connection = fixture_prices()
        try:
            histories = export_histories(connection)
        finally:
            connection.close()
        doritos = next(history for history in histories if history["brand"] == "Doritos")
        self.assertEqual(doritos["name"], "Doritos Cool Original Tortilla Chips 180g")
        self.assertEqual(doritos["retailer"], "Sainsbury's")
        self.assertEqual(doritos["source_url"], RETAIL_SOURCE)
        self.assertEqual(doritos["price_basis"], "lowest_available_including_loyalty")
        self.assertIn("separate from reported historical replacement chain", doritos["identity_scope"])
        self.assertEqual([point["date"] for point in doritos["points"]], ["2024-01-10", "2024-02-10", "2024-04-13"])
        for point in doritos["points"]:
            self.assertAlmostEqual(point["unit_price_gbp"], 100 * point["price_gbp"] / point["mass_g"])
        snickers = next(history for history in histories if history["brand"] == "Snickers")
        self.assertEqual(snickers["points"][0]["mass_g"], 166.8)
        self.assertAlmostEqual(snickers["points"][0]["unit_price_gbp"], 100 * 2 / 166.8)

    def test_comparisons_are_same_day_same_retailer_and_require_known_mass(self):
        connection = fixture_prices()
        try:
            groups = export_comparisons(connection)
        finally:
            connection.close()
        sains = next(group for group in groups if group["group"] == "Crisps" and group["retailer"] == "Sainsbury's")
        tesco = next(group for group in groups if group["group"] == "Crisps" and group["retailer"] == "Tesco")
        self.assertEqual([item["id"] for item in sains["items"]], ["fixture-doritos-sains"])
        self.assertCountEqual([item["id"] for item in tesco["items"]], ["fixture-doritos-tesco","fixture-dippers"])
        self.assertEqual(sains["date"], "2024-04-13")
        self.assertIn("not today's offers", sains["note"])
        self.assertIn("Loyalty", sains["note"])
        chocolate = next(group for group in groups if group["group"] == "Chocolate" and group["retailer"] == "Tesco")
        self.assertEqual([item["id"] for item in chocolate["items"]], ["fixture-snickers-tesco"])
        self.assertAlmostEqual(sains["items"][0]["price_per_100g_gbp"], 1.2)
        self.assertAlmostEqual(tesco["items"][0]["price_per_100g_gbp"], 1)
        for group in groups:
            values = [item["price_per_100g_gbp"] for item in group["items"]]
            self.assertEqual(values, sorted(values))
            self.assertTrue(all(item["price_basis"] == "lowest_available_including_loyalty" for item in group["items"]))

    def test_reported_case_calculations_do_not_turn_publication_into_event_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "research").mkdir()
            document = {"sources":{"fixture":{"url":"https://example.test/fixture-source","published":"2025-10-28"}},
                "cases":[{"id":"quality-street-uk-tub-2025","name":"Fixture Quality Street","retailer":"Fixture shop",
                    "source_id":"fixture","status":"Synthetic test fixture only",
                    "old":{"quantity_g":600,"price_gbp":6,"barcode":"00123456","period":"Unknown earlier period"},
                    "new":{"quantity_g":550,"price_gbp":7,"barcode":"00123457","period":"Reported 2025"}}]}
            (root / "research/reported-cases.json").write_text(json.dumps(document))
            case = initial_cases(root)[0]
        self.assertEqual(case["old"]["price_per_100g_gbp"], 1)
        self.assertAlmostEqual(case["new"]["price_per_100g_gbp"], 100 * 7 / 550)
        self.assertAlmostEqual(case["unit_price_change_fraction"], (7/550)/(6/600)-1)
        self.assertIsNone(case["event_date"])
        self.assertIsNone(case["old"]["transaction_date"])
        self.assertEqual(case["old"]["period"], "Unknown earlier period")
        self.assertEqual(case["old"]["barcode"], "00123456")
        self.assertEqual(case["old"]["price_basis"], "reported_shelf_price_same_retailer")

    def test_public_paths_are_portable_without_mutating_frozen_provenance(self):
        root = Path("/tmp/publish-fixture").resolve()
        original = {"path": str(root / "data/model.json"),
                    "nested": [{"root": str(root), "other": "/tmp/publish-fixture-extra/model.json"}],
                    "url": "https://example.test/source", "metric": 1.5747}
        frozen = json.dumps(original, sort_keys=True)
        public = portable_public_metadata(original, root)
        self.assertEqual(public["path"], "data/model.json")
        self.assertEqual(public["nested"][0]["root"], ".")
        self.assertEqual(public["nested"][0]["other"], "/tmp/publish-fixture-extra/model.json")
        self.assertEqual(public["url"], original["url"])
        self.assertEqual(public["metric"], original["metric"])
        self.assertEqual(json.dumps(original, sort_keys=True), frozen)

    def test_full_export_keeps_missing_evidence_prices_null(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("data/curated", "data/reports", "data/processed"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            case = {"id":"fixture-size-only","name":"Synthetic size-only fixture","brand":"Fixture", "retailer":None,
                "old":{"mass_g":100,"price_gbp":None,"price_basis":"not_reported","barcode":None},
                "new":{"mass_g":90,"price_gbp":None,"price_basis":"not_reported","barcode":None},
                "event_date":None,"source_ids":["fixture"],"photos":[],"family_link":{"status":"unresolved"}}
            (root / "data/curated/snack-cases.json").write_text(json.dumps({
                "sources":{"fixture":{"url":"https://example.test/fixture","title":"Synthetic fixture"}}, "cases":[case]}))
            reports = {"evaluation":{"status":"unavailable"},
                "retail-audit":{"prepared_price_observations":10,"first_observed_date":"2024-01-10","last_observed_date":"2024-04-13"},
                "catalogue-audit":{"rows":0},"commodity-audit":{"weekly_rows":0},
                "monthly-audit":{"eligible_sampled_monthly_pairs":0,"distinct_eligible_target_months":0}}
            for name, document in reports.items():
                (root / f"data/reports/{name}.json").write_text(json.dumps(document))
            (root / "data/source-registry.json").write_text(json.dumps({"purpose":"Synthetic fixture only"}))
            forecast_path = root / "data/experiments/category_forecast/summary.json"
            forecast_path.parent.mkdir(parents=True)
            forecast_path.write_text(json.dumps({"status":"ready", "categories":[{
                "category_id":"synthetic-test-category", "forecast":{"change_pct":0.5}}]}))
            for stage in ("category_tuning", "category_policy_tuning"):
                stage_path = root / f"data/experiments/{stage}/summary.json"
                stage_path.parent.mkdir(parents=True)
                stage_path.write_text(json.dumps({"status":"ready", "categories":[{
                    "category_id":"synthetic-test-category", "selected_model_id":"synthetic-selector",
                    "forecast":{"change_pct":0.25}, "live_selection_ranking":[], "leaderboard":[]}]}))
            connection = fixture_prices()
            connection.execute("COPY app_prices TO ? (FORMAT PARQUET)", [str(root / "data/processed/retail_prices.parquet")])
            connection.close()
            audit = run(root, fetch=False)
            document = json.loads((root / "data/app-public/data/demo.json").read_text())
            exported = document["cases"][0]
            self.assertEqual(audit["forecast_status"], "category_available")
            self.assertEqual(audit["product_forecast_status"], "unavailable")
            self.assertEqual(document["evaluation"]["status"], "unavailable")
            self.assertEqual(document["category_forecast"]["categories"][0]["category_id"], "synthetic-test-category")
            self.assertEqual(document["category_forecast"]["categories"][0]["forecast"]["change_pct"],0.5)
            self.assertEqual(document["category_tuning"]["categories"][0]["forecast"]["change_pct"],0.25)
            self.assertEqual(document["category_policy_tuning"]["categories"][0]["selected_model_id"],"synthetic-selector")
            self.assertTrue((root / "data/app-public/data/category-forecast.json").is_file())
            self.assertTrue((root / "data/app-public/data/category-policy-tuning.json").is_file())
            for side in ("old", "new"):
                self.assertIsNone(exported[side]["price_gbp"])
                self.assertIsNone(exported[side]["price_per_100g_gbp"])
            self.assertIsNone(exported["unit_price_change_fraction"])
            self.assertFalse(exported["price_comparison_available"])
            self.assertFalse(exported["eligible_monthly_training_label"])


if __name__ == "__main__":
    unittest.main()
