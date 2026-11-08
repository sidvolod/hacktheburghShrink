"""Small synthetic fixtures test transformations, never model evaluation."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from shrinkflation.retail import prepare_views, product_identifier, source_unit_prices


class RetailTests(unittest.TestCase):
    def test_identifiers_keep_size_count_and_retailer_distinct(self):
        self.assertNotEqual(product_identifier("Tesco", "Bar 4 x 40g"), product_identifier("Tesco", "Bar 5 x 40g"))
        self.assertNotEqual(product_identifier("Tesco", "Bar 48g"), product_identifier("ASDA", "Bar 48g"))
        self.assertEqual(product_identifier("Tesco", "Bar 48g"), product_identifier("Tesco", "Bar 48g"))


    def test_source_units_do_not_mix_dimensions(self):
        self.assertEqual(source_unit_prices(20, "kg")["price_per_100g_source"], 2)
        self.assertIsNone(source_unit_prices(20, "l")["price_per_100g_source"])
        self.assertEqual(source_unit_prices(20, "l")["price_per_100ml_source"], 2)
        self.assertIsNone(source_unit_prices(0, "kg")["price_per_100g_source"])
        self.assertIsNone(source_unit_prices(2, "unit")["price_per_100g_source"])
        self.assertIsNone(source_unit_prices(float('inf'), "kg")["price_per_100g_source"])
        self.assertIsNone(source_unit_prices(float('nan'), "kg")["price_per_100g_source"])

    def test_nonfinite_prices_and_rates_are_ineligible(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            con = duckdb.connect()
            raw = root / 'nonfinite.parquet'
            con.execute("""CREATE TABLE fixture AS SELECT * FROM (VALUES
                ('Tesco',2.0,'Infinity'::DOUBLE,'kg','Unknown snack A',TIMESTAMP '2024-01-15','food_cupboard',false),
                ('Tesco','NaN'::DOUBLE,20.0,'kg','Unknown snack B',TIMESTAMP '2024-01-15','food_cupboard',false)
            ) t(supermarket_name,price_gbp,price_unit_gbp,unit,product_name,capture_date,category_name,is_own_brand)""")
            con.execute(f"COPY fixture TO '{raw}' (FORMAT PARQUET)")
            prepare_views(con, raw, root)
            self.assertEqual(con.execute("SELECT count(*) FROM retail_prepared WHERE price_per_100g IS NOT NULL").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT invalid_pack_price,invalid_source_rate FROM retail_prepared WHERE product_name_raw='Unknown snack A'").fetchone(), (False,True))
            self.assertEqual(con.execute("SELECT invalid_pack_price,invalid_source_rate FROM retail_prepared WHERE product_name_raw='Unknown snack B'").fetchone(), (True,False))
            con.close()


    def test_repeated_categories_deduplicate_but_conflicting_day_prices_stay_flagged(self):
        with TemporaryDirectory() as directory:
            self.check_repeated_categories(Path(directory))

    def check_repeated_categories(self, tmp_path: Path):
        con = duckdb.connect()
        raw = tmp_path / "fixture.parquet"
        con.execute("""CREATE TABLE fixture AS SELECT * FROM (VALUES
            ('Tesco', 2.0, 20.0, 'kg', 'Snack bar 100g', TIMESTAMP '2024-01-15', 'food_cupboard', false),
            ('Tesco', 2.0, 20.0, 'kg', 'Snack bar 100g', TIMESTAMP '2024-01-15', 'free-from', false),
            ('Tesco', 2.5, 25.0, 'kg', 'Snack bar 100g', TIMESTAMP '2024-01-15', 'food_cupboard', false),
            ('ASDA', 2.0, 20.0, 'l', 'Juice 100ml', TIMESTAMP '2024-01-16', 'drinks', false),
            ('ASDA', 2.0, 200.0, 'kg', 'Snack bar 100g', TIMESTAMP '2024-01-16', 'food_cupboard', false),
            ('ASDA', 2.0, 4.0, 'l', 'Ice cream 480g', TIMESTAMP '2024-01-16', 'frozen', false)
        ) t(supermarket_name,price_gbp,price_unit_gbp,unit,product_name,capture_date,category_name,is_own_brand)""")
        con.execute(f"COPY fixture TO '{raw}' (FORMAT PARQUET)")
        prepare_views(con, raw, tmp_path)
        assert con.execute("SELECT count(*),sum(raw_row_count) FROM retail_prepared").fetchone() == (5, 6)
        assert con.execute("SELECT count(*) FROM retail_prepared WHERE conflicting_product_day").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM retail_prepared WHERE conflicting_product_day AND price_per_100g IS NOT NULL").fetchone()[0] == 0
        assert con.execute("SELECT price_per_100g,price_per_100ml FROM retail_prepared WHERE product_name_raw='Juice 100ml'").fetchone() == (None, 2)
        assert con.execute("SELECT source_name_unit_price_mismatch,price_per_100g FROM retail_prepared WHERE retailer='ASDA' AND product_name_raw='Snack bar 100g'").fetchone() == (True, None)
        basis = con.execute("SELECT unit_price_basis,mass_unit_price_basis,volume_unit_price_basis FROM retail_prepared WHERE product_name_raw='Ice cream 480g'").fetchone()
        self.assertEqual(basis, ('mixed_dimensions', 'explicit_name_quantity', 'source_reported_per_litre'))
        mass_price, volume_price = con.execute("SELECT price_per_100g,price_per_100ml FROM retail_prepared WHERE product_name_raw='Ice cream 480g'").fetchone()
        self.assertAlmostEqual(mass_price, 200/480)
        self.assertAlmostEqual(volume_price, 0.4)
        con.close()
