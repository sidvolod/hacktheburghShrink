import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from shrinkflation.monthly import prepare_monthly


class MonthlyTests(unittest.TestCase):
    def test_adjacent_months_only_signed_changes_and_missing_targets(self):
        with TemporaryDirectory() as folder:
            conn = duckdb.connect()
            conn.execute("""CREATE TABLE p(source_product_id VARCHAR,retailer VARCHAR,observation_date DATE,
                price_basis VARCHAR,mass_unit_price_basis VARCHAR,volume_unit_price_basis VARCHAR,unit_price_eligible BOOLEAN,
                price_per_100g_gbp DOUBLE,price_per_100ml_gbp DOUBLE)""")
            for product, days in {
                "fall": [("2024-01-01",1),("2024-01-31",1),("2024-02-01",1),("2024-02-14",1),("2024-02-29",1),
                         ("2024-03-01",.9),("2024-03-15",.9),("2024-03-31",.9)],
                "missing": [("2024-01-01",2),("2024-03-31",3)],
            }.items():
                conn.executemany("INSERT INTO p VALUES (?,'shop',?,'base','kg',NULL,true,?,NULL)", [(product,day,price) for day,price in days])
            path = Path(folder) / "prices.parquet"
            conn.execute("COPY p TO ? (FORMAT PARQUET)", [str(path)])
            prepare_monthly(conn,path)
            row = conn.execute("SELECT next_month_unit_price_change_fraction,eligible_for_sampled_monthly_price_evaluation FROM monthly_targets WHERE source_product_id='fall' AND history_month='2024-02-01'").fetchone()
            self.assertAlmostEqual(row[0],-.1)
            self.assertTrue(row[1])
            row = conn.execute("SELECT target_observed,next_month_unit_price_change_fraction FROM monthly_targets WHERE source_product_id='missing' AND history_month='2024-01-01'").fetchone()
            self.assertEqual(row,(False,None))
            self.assertEqual(conn.execute("SELECT count(*) FROM monthly_targets WHERE history_month='2024-03-01' AND target_observed").fetchone()[0],0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
