import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shrinkflation.common import require_data_path, stable_id
from shrinkflation.open_prices import normalise_item
from shrinkflation.quantities import parse_quantity


class QuantityTests(unittest.TestCase):
    def test_multipack_and_total(self):
        quantity = parse_quantity("6 x 25 g (150g)")
        self.assertEqual((quantity["total_mass_g"], quantity["item_mass_g"], quantity["pack_count"]), (150, 25, 6))
        self.assertEqual(parse_quantity("25g × 4")["total_mass_g"], 100)
        self.assertEqual(parse_quantity("2*266 g")["total_mass_g"], 532)
        self.assertEqual(parse_quantity("4*75g")["total_mass_g"], 300)

    def test_mass_and_volume_separate(self):
        self.assertEqual(parse_quantity("1.5kg")["total_mass_g"], 1500)
        quantity = parse_quantity("2 x 1L")
        self.assertEqual(quantity["total_volume_ml"], 2000)
        self.assertIsNone(quantity["total_mass_g"])
        self.assertEqual(parse_quantity("600gm")["total_mass_g"], 600)

    def test_ambiguous_or_unknown_never_becomes_zero(self):
        for text in ("6 pack 25g", "100g / 90g", "6x25g 200g", "0g", "2X20g Plus 3X10g",
                     "4x145g (4x102g drained)", "2 x 6 x 25g", "1,000g", "-5g", "100-150g"):
            result = parse_quantity(text)
            self.assertEqual(result["quantity_status"], "ambiguous", text)
            self.assertIsNone(result["total_mass_g"])
        self.assertEqual(parse_quantity("12 eggs")["quantity_status"], "count_only")
        self.assertIsNone(parse_quantity("12 eggs")["total_mass_g"])
        self.assertIsNone(parse_quantity("2% fat")["total_mass_g"])


class EvidenceSafetyTests(unittest.TestCase):
    def test_current_quantity_not_historical_denominator(self):
        item = {"id": 1, "price": 2, "currency":"GBP", "date":"2024-01-01", "product_code":"001234",
            "product":{"code":"001234", "quantity":"100g"}, "location": {"osm_address_country_code":"GB"}}
        price, product = normalise_item(item, "raw.json", 0)
        self.assertEqual(price["barcode"], "001234")
        self.assertEqual(product["total_mass_g"], 100)
        self.assertIsNone(price["price_per_100g_gbp"])
        item["price_per"] = "KILOGRAM"
        self.assertEqual(normalise_item(item, "raw.json", 0)[0]["price_per_100g_gbp"], .2)

    def test_path_escape_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                require_data_path(root, root / "elsewhere/file.csv")
            self.assertEqual(require_data_path(root, root / "data/raw/file.csv"), (root / "data/raw/file.csv").resolve())

    def test_id_is_deterministic_and_dimension_sensitive(self):
        self.assertEqual(stable_id("x", "001"), stable_id("x", "001"))
        self.assertNotEqual(stable_id("x", "001"), stable_id("x", 1))


if __name__ == "__main__":
    unittest.main()
