"""Meaningful catalogue invariants with synthetic, explicitly local fixtures."""

from pathlib import Path
import tempfile
import unittest

import duckdb

from shrinkflation.catalogue import normalized_query


def check_current_catalogue(tmp_path: Path):
    con = duckdb.connect()
    raw = tmp_path / "raw.parquet"
    con.execute(
        f"""COPY (
            SELECT code, [{{'lang':'main','text':'Original'}}, {{'lang':'en','text':'English'}}] AS product_name,
                'Brand' AS brands, ['brand'] AS brands_tags,
                quantity, pq AS product_quantity, unit AS product_quantity_unit,
                country AS countries_tags, [{{'lang':'en','text':'Milk, sugar'}}] AS ingredients_text,
                []::VARCHAR[] AS images, 7 AS rev, 100 AS created_t,
                200 AS last_modified_t, 300 AS last_updated_t, false AS obsolete,
                ['en:snacks'] AS categories_tags, []::VARCHAR[] AS stores_tags, 'en' AS lang
            FROM (VALUES
                ('000123', '1 kg', '1', 'kg', ['en:united-kingdom']),
                ('000456', '500 ml', '500', 'ml', ['en:united-kingdom']),
                ('000789', '100 g', '100', 'g', ['en:france']),
                ('000999', '-5g', '-5', 'g', ['en:united-kingdom']),
                ('001000', 'unknown', '100', NULL, ['en:united-kingdom']),
                ('001001', 'invalid', 'Infinity', 'g', ['en:united-kingdom'])
            ) t(code,quantity,pq,unit,country)
        ) TO '{raw}' (FORMAT PARQUET)"""
    )
    rows = con.execute(
        "SELECT barcode, product_name, total_mass_g, total_volume_ml, quantity_temporal_status, "
        "off_modified_epoch_s, raw_quantity FROM (" + normalized_query(raw) + ") ORDER BY barcode"
    ).fetchall()
    assert rows == [
        ("000123", "English", 1000.0, None, "current_catalogue_not_historical_price_proof", 200, "1 kg"),
        ("000456", "English", None, 500.0, "current_catalogue_not_historical_price_proof", 200, "500 ml"),
        ("000999", "English", None, None, "current_catalogue_not_historical_price_proof", 200, "-5g"),
        ("001000", "English", None, None, "current_catalogue_not_historical_price_proof", 200, "unknown"),
        ("001001", "English", None, None, "current_catalogue_not_historical_price_proof", 200, "invalid"),
    ]
    con.close()


class CatalogueTests(unittest.TestCase):
    def test_uk_filter_barcodes_raw_text_and_distinct_units(self):
        with tempfile.TemporaryDirectory() as directory:
            check_current_catalogue(Path(directory))

    def test_conflicting_barcode_records_keep_distinct_record_ids_and_cannot_auto_link(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            check_current_catalogue(folder)
            con = duckdb.connect()
            con.execute(
                "CREATE TABLE records AS SELECT * REPLACE ('0123456789012' AS code) "
                "FROM read_parquet(?) WHERE code='000123'", [str(folder / "raw.parquet")]
            )
            con.execute("INSERT INTO records SELECT * REPLACE (rev+1 AS rev) FROM records")
            con.execute(
                "INSERT INTO records SELECT * REPLACE ('0123456789013' AS code) FROM records LIMIT 1"
            )
            duplicate_fixture = folder / "duplicates.parquet"
            con.execute(f"COPY records TO '{duplicate_fixture}' (FORMAT PARQUET)")
            results = con.execute(
                "SELECT barcode,count(*),count(DISTINCT source_record_id),bool_and(barcode_format_valid),"
                "bool_or(conflicting_duplicate),bool_and(identity_eligible) FROM ("
                + normalized_query(duplicate_fixture) + ") GROUP BY barcode ORDER BY barcode"
            ).fetchall()
            self.assertEqual(results, [
                ("0123456789012", 2, 2, True, True, False),
                ("0123456789013", 1, 1, True, False, True),
            ])
            con.close()
