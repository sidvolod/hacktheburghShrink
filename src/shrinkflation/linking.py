"""Review candidates for familiar snacks; similarity is never replacement proof."""
from pathlib import Path

from .common import connect, export_query, sql_literal, write_json

FOCUS = {
    "snickers": "snickers", "maltesers": "maltesers", "milky-way": "milky\\s*way",
    "doritos": "doritos", "walkers": "walkers", "pringles": "pringles",
    "oreo": "oreo", "quality-street": "quality\\s*street", "dairy-milk": "dairy\\s*milk",
    "m-and-ms": "m&m|m & m|m and m", "mcvities": "mcvitie|mc vitie",
}


def run(root: Path, fetch: bool = True) -> dict:
    processed = root / "data/processed"
    conn = connect(root)
    try:
        conn.execute("CREATE TEMP TABLE focus(focus_family VARCHAR, pattern VARCHAR)")
        conn.executemany("INSERT INTO focus VALUES (?,?)", list(FOCUS.items()))
        conn.execute(f"""CREATE TEMP TABLE focused_retail AS
            SELECT f.focus_family,p.* FROM read_parquet({sql_literal(processed / 'retail_products.parquet')}) p
            JOIN focus f ON regexp_matches(lower(p.product_name_raw),f.pattern)""")
        conn.execute(f"""CREATE TEMP TABLE focused_off AS
            SELECT f.focus_family,p.* FROM read_parquet({sql_literal(processed / 'catalogue_products.parquet')}) p
            JOIN focus f ON regexp_matches(lower(p.product_name),f.pattern)
            WHERE p.barcode IS NOT NULL AND p.product_name IS NOT NULL AND p.identity_eligible""")
        conn.execute("""CREATE TEMP TABLE ranked AS
            SELECT r.focus_family,r.source_product_id AS retail_source_product_id,
                r.retailer_raw,r.product_name_raw AS retail_product_name,
                r.total_mass_g AS retail_mass_g,r.total_volume_ml AS retail_volume_ml,r.pack_count AS retail_pack_count,
                o.barcode AS off_barcode,o.product_name AS off_product_name,o.brand AS off_brand,
                o.raw_quantity AS off_raw_quantity,o.total_mass_g AS off_mass_g,o.total_volume_ml AS off_volume_ml,
                jaro_winkler_similarity(lower(r.product_name_raw),lower(o.product_name)) AS name_similarity,
                o.source_url,
                'needs_identity_and_temporal_evidence_review' AS review_status,
                'uncalibrated_name_similarity_not_probability' AS score_definition,
                'size_and_count_differences_retained_no_replacement_inference' AS matching_rule,
                row_number() OVER(PARTITION BY r.focus_family,r.source_product_id
                  ORDER BY jaro_winkler_similarity(lower(r.product_name_raw),lower(o.product_name)) DESC,o.barcode) AS candidate_rank
            FROM focused_retail r JOIN focused_off o USING(focus_family)""")
        export_query(conn,"SELECT * FROM ranked WHERE candidate_rank<=5",processed / "retail_catalogue_candidates.parquet")
        # This count makes no claim about reconstructed family time coverage.
        stats = conn.execute("""SELECT focus_family,count(DISTINCT retail_source_product_id) AS retail_listings,
            count(DISTINCT off_barcode) AS off_barcodes,count(*) AS candidate_pairs
            FROM ranked WHERE candidate_rank<=5 GROUP BY 1 ORDER BY 1""").fetchall()
        report = {"scope": "11 familiar snack-name groups; not a catalogue-wide entity-resolution result",
            "candidate_pairs": conn.execute("SELECT count(*) FROM ranked WHERE candidate_rank<=5").fetchone()[0],
            "verified_new_links": 0,
            "groups": [dict(zip(("focus_family","retail_listings","off_barcodes","candidate_pairs"),row)) for row in stats],
            "limitations": ["Current OFF snapshots and 2024 retailer listings may describe different eras or concurrent variants.",
                "Top five name-similarity candidates require flavour, format, market and temporal evidence review.",
                "Mass, count and recipe differences are evidence to investigate, never hard rejection gates.",
                "Candidates are not inserted into reviewed family membership or monthly price targets."]}
        write_json(root / "data/reports/linking-audit.json",report)
        return report
    finally:
        conn.close()
