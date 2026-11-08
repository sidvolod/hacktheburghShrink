"""Acquire and prepare the dated UK supermarket price panel.

Retailer plus the *exact* source name is a provisional listing identity, not a
barcode, a verified product version, or a reconstructed replacement family.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .common import connect, download_file, export_query, write_json
from .quantities import parse_quantity

SOURCE_ID = "uk-retail-panel"
REPO = "https://huggingface.co/datasets/Rif-SQL/time-series-uk-retail-supermarket-price-data"
ORIGINAL = "https://www.kaggle.com/datasets/declanmcalinden/time-series-uk-supermarket-data"
KAGGLE_METADATA = "https://www.kaggle.com/api/v1/datasets/view/declanmcalinden/time-series-uk-supermarket-data"
EXPECTED_SHA256 = "9d712bbead729442277d73692daee90b9535ed10e0b1834227f97d637560fe15"
FOOD_CATEGORIES = ("food_cupboard", "bakery", "frozen", "drinks", "fresh_food", "free-from")
ALL_CATEGORIES = FOOD_CATEGORIES + ("household", "pets", "health_products", "baby_products", "home")


def product_identifier(retailer: str | None, raw_name: str | None) -> str:
    """Keep retailers and changed size/count/variant names distinct."""
    value = json.dumps([retailer, raw_name], ensure_ascii=False, separators=(",", ":"))
    return "retail:" + hashlib.sha256(value.encode()).hexdigest()[:24]


def source_unit_prices(rate: float | None, unit: str | None) -> dict:
    """Convert only declared source dimensions; never equate ml and grams."""
    positive = rate is not None and math.isfinite(rate) and rate > 0
    return {
        "price_per_100g_source": rate / 10 if positive and unit == "kg" else None,
        "price_per_100ml_source": rate / 10 if positive and unit == "l" else None,
    }


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def prepare_views(con, raw_file: Path, root: Path) -> None:
    """Prepare source-preserving views and a small distinct-name quantity table."""
    con.execute(f"CREATE OR REPLACE TEMP VIEW retail_raw AS SELECT * FROM read_parquet({_quote(raw_file)}, file_row_number=true)")
    names = con.execute("SELECT DISTINCT supermarket_name, product_name FROM retail_raw ORDER BY 1,2").fetchall()
    quantity_file = root / "data/interim/retail-quantities.jsonl"
    quantity_file.parent.mkdir(parents=True, exist_ok=True)
    with quantity_file.open("w", encoding="utf-8") as handle:
        for retailer, name in names:
            quantity = parse_quantity(name or "")
            item = {
                "product_id": product_identifier(retailer, name),
                "supermarket_name": retailer,
                "product_name": name,
                "total_mass_g": quantity.get("total_mass_g"),
                "total_volume_ml": quantity.get("total_volume_ml"),
                "item_mass_g": quantity.get("item_mass_g"),
                "item_volume_ml": quantity.get("item_volume_ml"),
                "pack_count": quantity.get("pack_count"),
                "quantity_status": quantity.get("quantity_status"),
                "quantity_parse_json": json.dumps(quantity, ensure_ascii=False),
                "variable_weight_name": any(word in (name or "").lower() for word in ("approx", "typically", "average", "per kg", "perkg")),
            }
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    # Explicit schema keeps all-null quantity columns numeric in small fixtures.
    con.execute(f"""CREATE OR REPLACE TEMP VIEW retail_quantities AS
        SELECT * FROM read_json({_quote(quantity_file)}, format='newline_delimited', columns={{
          product_id:'VARCHAR', supermarket_name:'VARCHAR', product_name:'VARCHAR',
          total_mass_g:'DOUBLE', total_volume_ml:'DOUBLE', item_mass_g:'DOUBLE', item_volume_ml:'DOUBLE',
          pack_count:'INTEGER', quantity_status:'VARCHAR', quantity_parse_json:'VARCHAR',
          variable_weight_name:'BOOLEAN'}})""")
    category_case = "CASE category_name " + " ".join(
        f"WHEN '{name}' THEN {1 << index}" for index, name in enumerate(ALL_CATEGORIES)
    ) + " ELSE 0 END"
    category_list = "list_filter([" + ",".join(
        f"CASE WHEN (category_bits & {1 << index})>0 THEN '{name}' END"
        for index, name in enumerate(ALL_CATEGORIES)
    ) + "], x -> x IS NOT NULL)"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE retail_grouped AS
      WITH grouped AS (
        SELECT supermarket_name, product_name, capture_date::DATE AS observed_date,
          price_gbp, price_unit_gbp, unit,
          bit_or({category_case}) AS category_bits,
          bool_or(is_own_brand=true) AS has_own_brand_true,
          bool_or(is_own_brand=false) AS has_own_brand_false,
          count(*) AS raw_row_count,
          min(file_row_number) AS raw_row_index_first
        FROM retail_raw GROUP BY ALL
      ) SELECT * EXCLUDE(category_bits,has_own_brand_true,has_own_brand_false),
          {category_list} AS categories,
          list_filter([CASE WHEN has_own_brand_true THEN true END,
            CASE WHEN has_own_brand_false THEN false END], x -> x IS NOT NULL) AS own_brand_values
        FROM grouped""")
    con.execute("""CREATE OR REPLACE TEMP VIEW retail_conflicts AS
        SELECT supermarket_name, product_name, observed_date, count(*) AS distinct_price_records
        FROM retail_grouped GROUP BY ALL""")
    food_list = "[" + ",".join("'" + value + "'" for value in FOOD_CATEGORIES) + "]"
    con.execute(f"""CREATE OR REPLACE TEMP VIEW retail_prepared AS
      WITH joined AS (
        SELECT 'retail-price:' || md5(to_json(struct_pack(
          retailer := r.supermarket_name, name := r.product_name,
          observed_date := r.observed_date, price := r.price_gbp,
          rate := r.price_unit_gbp, unit := r.unit))) AS observation_id,
          q.product_id, '{SOURCE_ID}' AS source_id,
          'data/raw/retail/base_retail_gb_snappy.parquet' AS source_file,
          r.supermarket_name AS retailer_raw,
          CASE r.supermarket_name WHEN 'Sains' THEN 'Sainsbury''s' ELSE r.supermarket_name END AS retailer,
          r.product_name AS product_name_raw,
          lower(trim(regexp_replace(r.product_name, '\\s+', ' ', 'g'))) AS product_name_normalised,
          r.observed_date, r.price_gbp, r.price_unit_gbp AS source_unit_price_gbp,
          r.unit AS source_unit, 'GBP' AS currency, 'GB' AS market,
          'lowest_available_including_loyalty' AS price_basis,
          NULL::BOOLEAN AS is_loyalty_price, NULL::BOOLEAN AS is_promotional_price,
          r.categories, r.own_brand_values,
          list_has_any(r.categories, {food_list}) AS is_food_candidate,
          r.raw_row_count, r.raw_row_index_first,
          c.distinct_price_records > 1 AS conflicting_product_day,
          q.total_mass_g, q.total_volume_ml, q.item_mass_g, q.item_volume_ml, q.pack_count,
          q.quantity_status, q.variable_weight_name,
          CASE WHEN r.price_unit_gbp > 0 AND isfinite(r.price_unit_gbp) AND r.unit='kg' THEN r.price_unit_gbp::DOUBLE/10 END AS price_per_100g_source,
          CASE WHEN r.price_unit_gbp > 0 AND isfinite(r.price_unit_gbp) AND r.unit='l' THEN r.price_unit_gbp::DOUBLE/10 END AS price_per_100ml_source,
          CASE WHEN r.price_gbp > 0 AND isfinite(r.price_gbp) AND q.total_mass_g > 0 AND isfinite(q.total_mass_g) AND NOT q.variable_weight_name
            THEN 100*r.price_gbp::DOUBLE/q.total_mass_g END AS price_per_100g_name,
          CASE WHEN r.price_gbp > 0 AND isfinite(r.price_gbp) AND q.total_volume_ml > 0 AND isfinite(q.total_volume_ml) AND NOT q.variable_weight_name
            THEN 100*r.price_gbp::DOUBLE/q.total_volume_ml END AS price_per_100ml_name,
          CASE WHEN r.price_gbp>0 AND isfinite(r.price_gbp) AND r.price_unit_gbp>0 AND isfinite(r.price_unit_gbp) AND r.unit='kg'
            THEN 1000*r.price_gbp::DOUBLE/r.price_unit_gbp END AS implied_mass_g,
          CASE WHEN r.price_gbp>0 AND isfinite(r.price_gbp) AND r.price_unit_gbp>0 AND isfinite(r.price_unit_gbp) AND r.unit='l'
            THEN 1000*r.price_gbp::DOUBLE/r.price_unit_gbp END AS implied_volume_ml
        FROM retail_grouped r
        JOIN retail_quantities q ON r.supermarket_name IS NOT DISTINCT FROM q.supermarket_name
          AND r.product_name IS NOT DISTINCT FROM q.product_name
        JOIN retail_conflicts c ON r.supermarket_name IS NOT DISTINCT FROM c.supermarket_name
          AND r.product_name IS NOT DISTINCT FROM c.product_name AND r.observed_date IS NOT DISTINCT FROM c.observed_date
      ), checked AS (
        SELECT *,
          CASE WHEN price_per_100g_source IS NOT NULL AND price_per_100g_name IS NOT NULL
            THEN abs(price_per_100g_source/price_per_100g_name-1) > 0.05
          WHEN price_per_100ml_source IS NOT NULL AND price_per_100ml_name IS NOT NULL
            THEN abs(price_per_100ml_source/price_per_100ml_name-1) > 0.05
          ELSE false END AS source_name_unit_price_mismatch,
          price_gbp IS NULL OR price_gbp<=0 OR NOT isfinite(price_gbp) AS invalid_pack_price,
          source_unit_price_gbp IS NULL OR source_unit_price_gbp<=0 OR NOT isfinite(source_unit_price_gbp) AS invalid_source_rate,
          product_name_raw IS NULL OR trim(product_name_raw)='' OR observed_date IS NULL OR retailer_raw IS NULL AS invalid_identity
        FROM joined
      ) SELECT *,
          CASE WHEN NOT invalid_pack_price AND NOT invalid_identity AND NOT conflicting_product_day
              AND NOT source_name_unit_price_mismatch AND is_food_candidate
            THEN coalesce(price_per_100g_source, price_per_100g_name) END AS price_per_100g,
          CASE WHEN NOT invalid_pack_price AND NOT invalid_identity AND NOT conflicting_product_day
              AND NOT source_name_unit_price_mismatch AND is_food_candidate
            THEN coalesce(price_per_100ml_source, price_per_100ml_name) END AS price_per_100ml,
          CASE WHEN source_name_unit_price_mismatch THEN 'source_name_mismatch'
            WHEN coalesce(price_per_100g_source,price_per_100g_name) IS NOT NULL
              AND coalesce(price_per_100ml_source,price_per_100ml_name) IS NOT NULL THEN 'mixed_dimensions'
            WHEN price_per_100g_source IS NOT NULL THEN 'source_reported_per_kg'
            WHEN price_per_100ml_source IS NOT NULL THEN 'source_reported_per_litre'
            WHEN price_per_100g_name IS NOT NULL OR price_per_100ml_name IS NOT NULL THEN 'explicit_name_quantity'
            ELSE 'unavailable' END AS unit_price_basis,
          CASE WHEN source_name_unit_price_mismatch THEN 'source_name_mismatch'
            WHEN price_per_100g_source IS NOT NULL THEN 'source_reported_per_kg'
            WHEN price_per_100g_name IS NOT NULL THEN 'explicit_name_quantity'
            ELSE 'unavailable' END AS mass_unit_price_basis,
          CASE WHEN source_name_unit_price_mismatch THEN 'source_name_mismatch'
            WHEN price_per_100ml_source IS NOT NULL THEN 'source_reported_per_litre'
            WHEN price_per_100ml_name IS NOT NULL THEN 'explicit_name_quantity'
            ELSE 'unavailable' END AS volume_unit_price_basis
        FROM checked""")


def run(root: Path, fetch: bool = True) -> dict:
    raw_dir = root / "data/raw/retail"
    raw_file = raw_dir / "base_retail_gb_snappy.parquet"
    if fetch:
        for name in ("README.md", "NOTICE.MD", "base_retail_gb_snappy.parquet"):
            download_file(f"{REPO}/resolve/main/{name}", raw_dir / name, source_id=SOURCE_ID, root=root)
        download_file(KAGGLE_METADATA, raw_dir / "kaggle-metadata.json", source_id=SOURCE_ID, root=root)
        download_file("https://huggingface.co/api/datasets/Rif-SQL/time-series-uk-retail-supermarket-price-data/tree/main",
                      raw_dir / "hf-tree.json", source_id=SOURCE_ID, root=root)
    if not raw_file.exists():
        return {"status": "missing", "source_id": SOURCE_ID, "reason": "Run fetch first; raw retail Parquet is absent."}
    with raw_file.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Retail source content changed: inspect and update the pinned SHA256 before preparing it.")
    con = connect(root)
    try:
        prepare_views(con, raw_file, root)
        output = root / "data/processed"
        export_query(con, """SELECT *, product_id AS source_product_id,
            observed_date AS observation_date, price_per_100g AS price_per_100g_gbp,
            price_per_100ml AS price_per_100ml_gbp,
            price_per_100g IS NOT NULL OR price_per_100ml IS NOT NULL AS unit_price_eligible
            FROM retail_prepared""", output / "retail_prices.parquet")
        export_query(con, f"""SELECT q.product_id, q.product_id AS source_product_id, '{SOURCE_ID}' AS source_id,
            q.supermarket_name AS retailer_raw, q.product_name AS product_name_raw,
            lower(trim(regexp_replace(q.product_name, '\\s+', ' ', 'g'))) AS product_name_normalised,
            NULL::VARCHAR AS barcode, NULL::VARCHAR AS family_id,
            'retailer_exact_name_provisional' AS identity_status,
            q.total_mass_g, q.total_volume_ml, q.item_mass_g, q.item_volume_ml, q.pack_count, q.quantity_status,
            q.quantity_parse_json, q.variable_weight_name,
            min(r.observed_date) AS first_observed_date, max(r.observed_date) AS last_observed_date,
            count(DISTINCT r.observed_date) AS distinct_observed_dates,
            count(DISTINCT date_trunc('month', r.observed_date)) AS distinct_observed_months
          FROM retail_quantities q JOIN retail_prepared r USING(product_id) GROUP BY ALL""",
                     output / "retail_products.parquet")
        summary = con.execute("""SELECT count(*) AS prepared_price_observations,
            sum(raw_row_count) AS raw_rows, sum(raw_row_count-1) AS duplicate_or_category_repeat_rows,
            count(DISTINCT product_id) AS provisional_retailer_name_products,
            min(observed_date)::VARCHAR AS first_observed_date, max(observed_date)::VARCHAR AS last_observed_date,
            count(DISTINCT observed_date) AS observed_days, count(DISTINCT date_trunc('month',observed_date)) AS calendar_months,
            count(*) FILTER(WHERE conflicting_product_day) AS conflicting_product_day_observations,
            count(*) FILTER(WHERE invalid_pack_price) AS invalid_pack_price_observations,
            count(*) FILTER(WHERE invalid_source_rate) AS invalid_source_rate_observations,
            count(*) FILTER(WHERE source_name_unit_price_mismatch) AS source_name_rate_mismatch_observations,
            count(*) FILTER(WHERE total_mass_g>0) AS explicit_name_mass_observations,
            count(*) FILTER(WHERE total_volume_ml>0) AS explicit_name_volume_observations,
            count(*) FILTER(WHERE is_food_candidate) AS food_candidate_observations,
            count(*) FILTER(WHERE price_per_100g IS NOT NULL) AS usable_mass_price_observations,
            count(*) FILTER(WHERE price_per_100ml IS NOT NULL) AS usable_volume_price_observations
            FROM retail_prepared""").fetchone()
        cols = [item[0] for item in con.description]
        audit = dict(zip(cols, summary))
        audit.update({"source_id": SOURCE_ID, "status": "prepared", "sha256": digest,
                      "source_url": REPO, "original_source_url": ORIGINAL,
                      "price_basis": "lowest_available_including_loyalty",
                      "identity_scope": "retailer plus exact raw product name; no barcode or verified replacement links",
                      "quantity_rule": "Parse explicit name mass/volume; source price/rate implied quantity is separate and never treated as declared size.",
                      "rate_mismatch_rule": "Flag >5% disagreement between source unit rate and explicit-name unit price; allows source rounding.",
                      "food_candidate_categories": list(FOOD_CATEGORIES),
                      "limitations": ["Only four calendar months of panel coverage; April is partial.",
                                       "No row-level loyalty/promotion flag; source author reports lowest available price including loyalty.",
                                       "Name-based identities can split renamed listings and conflate same-name variants.",
                                       "Some categories contain non-food listings; food_candidate is a coarse filter.",
                                       "Morrisons scraper coverage was variable before 2024-01-27.",
                                       "Missing days are unobserved, never filled as no change.",
                                       "Source has no ingredients, barcodes or sales quantities."]})
        for name, query in {
            "retailers": "SELECT retailer_raw AS retailer, count(*) AS observations, count(DISTINCT product_id) AS products, min(observed_date)::VARCHAR AS first_date, max(observed_date)::VARCHAR AS last_date FROM retail_prepared GROUP BY 1 ORDER BY 1",
            "source_units": "SELECT source_unit, count(*) AS observations FROM retail_prepared GROUP BY 1 ORDER BY 1",
            "highest_source_mass_rates": "SELECT retailer,product_name_raw,observed_date::VARCHAR AS observed_date,source_unit_price_gbp::DOUBLE AS source_unit_price_gbp FROM retail_prepared WHERE source_unit='kg' ORDER BY source_unit_price_gbp DESC LIMIT 10",
            "quantity_status": "SELECT quantity_status,count(DISTINCT product_id) AS products FROM retail_prepared GROUP BY 1 ORDER BY 1",
        }.items():
            rows = con.execute(query).fetchall()
            names = [item[0] for item in con.description]
            audit[name] = [dict(zip(names, row)) for row in rows]
        write_json(root / "data/reports/retail-audit.json", audit)
        notes = {
            "source_id": SOURCE_ID, "dataset_url": REPO, "original_url": ORIGINAL,
            "original_metadata_url": KAGGLE_METADATA,
            "licence": "Apache 2.0", "licence_evidence": "Saved original Kaggle public API metadata and HF README/NOTICE.",
            "attribution": "Declan McAlinden (original collection), Rif Kiamil (Parquet merge).",
            "original_author_notes": {
                "price_basis": "Lowest available price, including Nectar/Clubcard; multi-buy and meal-deal discounts excluded.",
                "scraper_coverage": "Days only when scraper was run; Morrisons coverage variable before 2024-01-27.",
            },
            "retained_raw_fields": ["supermarket_name", "price_gbp", "price_unit_gbp", "unit", "product_name", "capture_date", "category_name", "is_own_brand"],
            "row_lineage": "raw_row_index_first is the zero-based first Parquet file_row_number; raw_row_count counts all contributors. Recover every contributor by joining the preserved retailer/name/date/price/rate/unit grouping keys against the unchanged raw source file.",
            "unit_price_basis_columns": "Use mass_unit_price_basis for price_per_100g_gbp and volume_unit_price_basis for price_per_100ml_gbp. Legacy unit_price_basis is mixed_dimensions when a row supports both dimensions; no density is assumed.",
        }
        write_json(root / "data/reports/retail-source-notes.json", notes)
        return audit
    finally:
        con.close()
