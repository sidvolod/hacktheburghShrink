"""Dated prices and separate current product enrichment from saved Open Prices pages."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .common import connect, export_query, export_rows, stable_id, write_json
from .quantities import parse_quantity


PRICE_SCHEMA = {"observation_id": "VARCHAR", "source": "VARCHAR", "source_price_id": "BIGINT",
    "barcode": "VARCHAR", "source_product_id": "VARCHAR", "observation_date": "DATE",
    "retailer": "VARCHAR", "location_id": "BIGINT", "country_code": "VARCHAR",
    "price_gbp": "DOUBLE", "currency": "VARCHAR", "price_per_raw": "VARCHAR",
    "price_per_100g_gbp": "DOUBLE", "price_per_100ml_gbp": "DOUBLE",
    "unit_price_basis": "VARCHAR", "price_is_discounted": "BOOLEAN",
    "price_without_discount_gbp": "DOUBLE", "discount_type": "VARCHAR",
    "proof_id": "BIGINT", "proof_type": "VARCHAR", "proof_file_path": "VARCHAR",
    "proof_date": "DATE", "record_created_at": "TIMESTAMPTZ", "record_updated_at": "TIMESTAMPTZ",
    "current_product_snapshot_id": "VARCHAR", "quantity_temporal_status": "VARCHAR",
    "source_url": "VARCHAR", "raw_path": "VARCHAR", "raw_item_index": "INTEGER"}

PRODUCT_SCHEMA = {"snapshot_id": "VARCHAR", "source_product_id": "VARCHAR", "barcode": "VARCHAR",
    "product_name": "VARCHAR", "brands": "VARCHAR", "raw_quantity": "VARCHAR",
    "total_mass_g": "DOUBLE", "total_volume_ml": "DOUBLE", "pack_count": "INTEGER",
    "quantity_status": "VARCHAR", "source_last_synced_at": "TIMESTAMPTZ",
    "quantity_temporal_status": "VARCHAR", "raw_product_json": "VARCHAR"}


def normalise_item(item: dict, raw_path: str, index: int) -> tuple[dict, dict | None]:
    product = item.get("product") or {}
    location = item.get("location") or {}
    proof = item.get("proof") or {}
    barcode = item.get("product_code") or product.get("code")
    barcode = str(barcode) if barcode else None
    snapshot = None
    if product:
        raw_json = json.dumps(product, sort_keys=True, ensure_ascii=False)
        quantity = parse_quantity(product.get("quantity"))
        snapshot = {"snapshot_id": stable_id("op-snapshot", raw_json),
            "source_product_id": "off:" + barcode if barcode else None, "barcode": barcode,
            "product_name": product.get("product_name"), "brands": product.get("brands"),
            **{key: quantity[key] for key in ("raw_quantity", "total_mass_g", "total_volume_ml", "pack_count", "quantity_status")},
            "source_last_synced_at": product.get("source_last_synced"),
            "quantity_temporal_status": "current_enrichment_not_dated_pack_proof", "raw_product_json": raw_json}
    price = float(item["price"]) if item.get("price") is not None else None
    price_per = item.get("price_per")
    positive = price is not None and price > 0
    row = {"observation_id": f"open-prices:{item['id']}", "source": "open-prices",
        "source_price_id": item["id"], "barcode": barcode,
        "source_product_id": "off:" + barcode if barcode else None,
        "observation_date": item.get("date"), "retailer": location.get("osm_brand") or location.get("osm_name"),
        "location_id": item.get("location_id"), "country_code": location.get("osm_address_country_code"),
        "price_gbp": price, "currency": item.get("currency"), "price_per_raw": price_per,
        "price_per_100g_gbp": price / 10 if positive and price_per == "KILOGRAM" else None,
        "price_per_100ml_gbp": price / 10 if positive and price_per in ("LITER", "LITRE") else None,
        "unit_price_basis": "explicit_price_per" if price_per in ("KILOGRAM", "LITER", "LITRE") else "pack_mass_not_dated",
        "price_is_discounted": item.get("price_is_discounted"),
        "price_without_discount_gbp": item.get("price_without_discount"), "discount_type": item.get("discount_type"),
        "proof_id": item.get("proof_id"), "proof_type": proof.get("type"), "proof_file_path": proof.get("file_path"),
        "proof_date": proof.get("date"), "record_created_at": item.get("created"), "record_updated_at": item.get("updated"),
        "current_product_snapshot_id": snapshot["snapshot_id"] if snapshot else None,
        "quantity_temporal_status": "current_enrichment_not_dated_pack_proof",
        "source_url": f"https://prices.openfoodfacts.org/api/v1/prices/{item['id']}",
        "raw_path": raw_path, "raw_item_index": index}
    return row, snapshot


def run(root: Path, fetch: bool = True) -> dict:
    # Existing frozen pages are intentionally retained, rather than mixing new pagination.
    paths = sorted((root / "data/raw/open-prices").glob("open-prices-gbp-page*.json"))
    if not paths:
        raise FileNotFoundError("No saved Open Prices pages")
    rows, snapshots, rejected = [], {}, []
    seen = set()
    total = 0
    for path in paths:
        for index, item in enumerate(json.loads(path.read_text())["items"]):
            total += 1
            reason = None
            if item.get("duplicate_of") is not None:
                reason = "marked_duplicate"
            elif item["id"] in seen:
                reason = "repeated_source_id"
            elif item.get("currency") != "GBP":
                reason = "not_gbp"
            elif (item.get("location") or {}).get("osm_address_country_code") != "GB":
                reason = "not_explicit_gb"
            if reason:
                rejected.append({"source_price_id": item["id"], "reason": reason,
                    "raw_path": str(path.relative_to(root)), "raw_item_index": index})
                continue
            seen.add(item["id"])
            row, snapshot = normalise_item(item, str(path.relative_to(root)), index)
            rows.append(row)
            if snapshot:
                snapshots[snapshot["snapshot_id"]] = snapshot
    conn = connect(root)
    processed = root / "data/processed"
    export_rows(conn, rows, PRICE_SCHEMA, processed / "open_prices.parquet")
    export_rows(conn, list(snapshots.values()), PRODUCT_SCHEMA, processed / "open_prices_product_snapshots.parquet")
    export_rows(conn, rejected, {"source_price_id": "BIGINT", "reason": "VARCHAR", "raw_path": "VARCHAR", "raw_item_index": "INTEGER"}, processed / "open_prices_exclusions.parquet")
    prices = str(processed / "open_prices.parquet").replace("'", "''")
    conn.execute(f"CREATE TEMP VIEW p AS SELECT * FROM read_parquet('{prices}')")
    report = {"raw_rows": total, "retained_explicit_gb_gbp_rows": len(rows),
        "exclusions": dict(Counter(x["reason"] for x in rejected)), "current_product_snapshots": len(snapshots),
        "date_range": list(conn.execute("SELECT min(observation_date), max(observation_date) FROM p").fetchone()),
        "barcoded_rows": conn.execute("SELECT count(*) FROM p WHERE barcode IS NOT NULL").fetchone()[0],
        "distinct_barcodes": conn.execute("SELECT count(DISTINCT barcode) FROM p").fetchone()[0],
        "barcodes_two_dates": conn.execute("SELECT count(*) FROM (SELECT barcode FROM p WHERE barcode IS NOT NULL GROUP BY barcode HAVING count(DISTINCT observation_date)>=2)").fetchone()[0],
        "direct_unit_price_rows": conn.execute("SELECT count(*) FROM p WHERE price_per_100g_gbp IS NOT NULL OR price_per_100ml_gbp IS NOT NULL").fetchone()[0],
        "limitations": ["Current nested product quantities are not dated proof of historical pack mass; no historical unit price is inferred from them.",
            "Same-barcode coverage is not cross-barcode family coverage.", "Currency is filtered separately from explicit GB location.",
            "Promotional prices and proof references retained. Missing observations are not flat outcomes."]}
    write_json(root / "data/reports/open-prices-audit.json", report)
    conn.close()
    return report
