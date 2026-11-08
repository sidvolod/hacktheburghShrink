import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from shrinkflation.features import prepare_features


class FeatureTimingTests(unittest.TestCase):
    def test_late_or_unknown_publication_is_never_strict_history(self):
        with TemporaryDirectory() as directory:
            conn=duckdb.connect()
            conn.execute("""CREATE TABLE w(series_id VARCHAR,commodity VARCHAR,unit VARCHAR,currency VARCHAR,
                week_end DATE,value DOUBLE,publication_known BOOLEAN,eligible_for_backtest BOOLEAN,
                available_at TIMESTAMPTZ,change_pct_1w DOUBLE)""")
            conn.execute("""INSERT INTO w VALUES
                ('cocoa','cocoa','tonne','GBP','2024-01-05',100,true,true,'2024-01-06',NULL),
                ('cocoa','cocoa','tonne','GBP','2024-01-12',110,false,false,NULL,10),
                ('cocoa','cocoa','tonne','GBP','2024-01-19',120,true,true,'2024-02-02',9),
                ('cocoa','cocoa','tonne','GBP','2024-01-26',130,false,false,NULL,8),
                ('cocoa','cocoa','tonne','GBP','2024-02-02',999,true,true,'2024-02-02',999)""")
            path=Path(directory)/"weekly.parquet"
            conn.execute("COPY w TO ? (FORMAT PARQUET)",[str(path)])
            prepare_features(conn,path,["2024-02-01"])
            values=conn.execute("SELECT feature_mode,latest_weekly_value,eligible_for_backtest FROM feature_values ORDER BY feature_mode").fetchall()
            self.assertEqual(values,[("exploratory_observation_dates_only",130.0,False),("strict_known_publication",100.0,False)])
            conn.execute("INSERT INTO w VALUES ('cocoa','cocoa','tonne','GBP','2024-03-29',777,true,true,'2024-03-31T23:30:00Z',NULL)")
            conn.execute("COPY w TO ? (FORMAT PARQUET)",[str(path)])
            prepare_features(conn,path,["2024-04-01"])
            # London midnight is 23:00 UTC after the spring clock change.
            self.assertEqual(conn.execute("SELECT latest_weekly_value FROM feature_values WHERE feature_mode='strict_known_publication'").fetchone()[0],999)
            conn.close()


if __name__ == "__main__":
    unittest.main()
