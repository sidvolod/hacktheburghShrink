"""Pinned Open Food Facts UK current-state catalogue, kept apart from histories.

The official global parquet is pinned and hash-checked, then UK-tagged records
are projected into a small catalogue. Database edit dates are preserved as
database metadata and are never asserted to be market dates.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from .common import connect, download_file, export_query, sha256_file, write_json
from .quantities import parse_quantity

DATASET = "openfoodfacts/product-database"
PINNED_REVISION = "92cf2f1cbf3c51b8929f138105991ef1c4e72aa3"
SOURCE_URL = f"https://huggingface.co/datasets/{DATASET}"
PARQUET_URL = f"{SOURCE_URL}/resolve/{PINNED_REVISION}/food.parquet"
FIELDS = (
    "code, product_name, brands, brands_tags, quantity, product_quantity, "
    "product_quantity_unit, countries_tags, ingredients_text, images, rev, "
    "created_t, last_modified_t, last_updated_t, obsolete, categories_tags, "
    "stores_tags, lang"
)
LIMITATIONS = [
    "Current catalogue snapshot, not a product revision archive or price history.",
    "UK country tags are contributor-supplied market metadata, not proof of a UK transaction.",
    "OFF creation/edit/image-upload dates are database events, not launch, reformulation or shelf-transition dates.",
    "Current quantities must not be attached to historical prices without dated quantity evidence.",
    "Different barcodes, pack sizes and counts may be replacements or concurrent variants; no family link is inferred here.",
    "Data ODbL / individual contents Database Contents License; photographs CC-BY-SA with attribution.",
]


def _sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def preferred_text_sql(column: str) -> str:
    """Keep original multilingual fields and choose a display text explicitly."""
    return (
        "coalesce("
        f"nullif((list_extract(list_filter({column}, x -> x.lang = 'en'), 1)).text, ''), "
        f"nullif((list_extract(list_filter({column}, x -> x.lang = 'main'), 1)).text, ''), "
        f"nullif((list_extract({column}, 1)).text, ''))"
    )


def normalized_query(raw_path: Path) -> str:
    """Prepare source identities and quantities without making family claims."""
    quantity = "try_cast(product_quantity AS DOUBLE)"
    unit = "lower(trim(product_quantity_unit))"
    positive_quantity = f"CASE WHEN isfinite({quantity}) AND {quantity} > 0 THEN {quantity} END"
    mass = (
        f"CASE {unit} WHEN 'g' THEN {positive_quantity} "
        f"WHEN 'kg' THEN 1000 * ({positive_quantity}) "
        f"WHEN 'mg' THEN ({positive_quantity}) / 1000 END"
    )
    volume = (
        f"CASE {unit} WHEN 'ml' THEN {positive_quantity} "
        f"WHEN 'l' THEN 1000 * ({positive_quantity}) "
        f"WHEN 'cl' THEN 10 * ({positive_quantity}) END"
    )
    return f"""
        SELECT
            'off:' || code AS source_product_id,
            'off-record:' || sha256(to_json(raw_record)) AS source_record_id,
            code AS barcode,
            count(*) OVER (PARTITION BY code) AS barcode_record_count,
            count(DISTINCT sha256(to_json(raw_record))) OVER (PARTITION BY code) > 1 AS conflicting_duplicate,
            coalesce(regexp_full_match(code, '[0-9]{{8}}|[0-9]{{12,14}}'), false) AS barcode_format_valid,
            count(*) OVER (PARTITION BY code) = 1
                AND coalesce(regexp_full_match(code, '[0-9]{{8}}|[0-9]{{12,14}}'), false) AS identity_eligible,
            {preferred_text_sql('product_name')} AS product_name,
            to_json(product_name)::VARCHAR AS product_name_raw_json,
            brands AS brand,
            to_json(brands_tags)::VARCHAR AS brands_tags_json,
            quantity AS raw_quantity,
            product_quantity AS raw_product_quantity,
            product_quantity_unit AS raw_product_quantity_unit,
            {mass} AS total_mass_g,
            {volume} AS total_volume_ml,
            'off_structured_quantity_current_state' AS quantity_basis,
            'current_catalogue_not_historical_price_proof' AS quantity_temporal_status,
            {preferred_text_sql('ingredients_text')} AS ingredients_text,
            to_json(ingredients_text)::VARCHAR AS raw_ingredients_json,
            to_json(images)::VARCHAR AS raw_images_json,
            to_json(countries_tags)::VARCHAR AS countries_tags_json,
            to_json(categories_tags)::VARCHAR AS categories_tags_json,
            to_json(stores_tags)::VARCHAR AS stores_tags_json,
            lang AS source_language,
            rev,
            created_t AS off_created_epoch_s,
            last_modified_t AS off_modified_epoch_s,
            last_updated_t AS off_updated_epoch_s,
            obsolete,
            'GB' AS market_tag,
            'current_catalogue_state' AS record_type,
            'off' AS source,
            'https://world.openfoodfacts.org/product/' || code AS source_url,
            {_sql_string(PINNED_REVISION)} AS source_dataset_revision,
            'ODbL' AS data_license,
            'CC-BY-SA' AS image_license
        FROM read_parquet({_sql_string(raw_path)}) AS raw_record
        WHERE list_contains(countries_tags, 'en:united-kingdom')
    """


def _record_subset_manifest(root: Path, raw_path: Path, retrieved_at: str) -> None:
    sha = hashlib.sha256()
    with raw_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    write_json(
        raw_path.with_suffix(".provenance.json"),
        {
            "source_id": "off-uk-current-projection",
            "source_url": PARQUET_URL,
            "dataset_url": SOURCE_URL,
            "dataset_revision": PINNED_REVISION,
            "retrieved_at": retrieved_at,
            "local_file": str(raw_path.relative_to(root)),
            "sha256": sha.hexdigest(),
            "bytes": raw_path.stat().st_size,
            "method": "DuckDB column projection and UK country-tag predicate from pinned official global parquet",
            "columns": [field.strip() for field in FIELDS.split(",")],
            "filter": "list_contains(countries_tags, 'en:united-kingdom')",
            "limitations": LIMITATIONS,
        },
    )


def _download_global(root: Path, raw_dir: Path) -> Path:
    """Resume bounded parallel ranges into one file, then verify the HF LFS hash.

    The official source has 4,785 tiny row groups. Scanning it remotely requires
    many high-latency requests, so a single local raw source is faster and lets
    subsequent preparation run offline. Part files and checkpoints stay in data.
    """
    tree_path = download_file(
        f"https://huggingface.co/api/datasets/{DATASET}/tree/{PINNED_REVISION}",
        raw_dir / "tree.json", source_id="off-pinned-file-metadata", root=root,
    )
    tree = json.loads(tree_path.read_text())
    info = next(item for item in tree if item["path"] == "food.parquet")
    expected_size = info["size"]
    expected_hash = info["lfs"]["oid"]
    destination = raw_dir / "food.parquet"
    metadata_path = destination.with_name(destination.name + ".metadata.json")
    if destination.exists():
        if destination.stat().st_size != expected_size or sha256_file(destination) != expected_hash:
            raise ValueError(f"OFF raw parquet size/hash mismatch: {destination}")
        return destination
    partial = raw_dir / "food.parquet.part"
    checkpoint = raw_dir / "food.parquet.parts.json"
    chunk_size = 64 * 1024 * 1024
    completed = set()
    if checkpoint.exists() and partial.exists():
        saved = json.loads(checkpoint.read_text())
        if saved.get("sha256") == expected_hash and partial.stat().st_size == expected_size:
            completed = set(saved.get("completed", []))
    fd = os.open(partial, os.O_CREAT | os.O_RDWR, 0o644)
    os.ftruncate(fd, expected_size)
    count = (expected_size + chunk_size - 1) // chunk_size

    def fetch_chunk(index: int) -> int:
        start = index * chunk_size
        end = min(start + chunk_size, expected_size) - 1
        for attempt in range(3):
            try:
                with requests.get(PARQUET_URL, stream=True, timeout=(20, 120), headers={
                    "Range": f"bytes={start}-{end}", "Accept-Encoding": "identity",
                    "User-Agent": "shrinkflationTrack-data-preparation/0.1 (public research)",
                }) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{expected_size}":
                        raise OSError("OFF endpoint did not return the requested byte range")
                    offset = start
                    for piece in response.iter_content(4 * 1024 * 1024):
                        written = os.pwrite(fd, piece, offset)
                        if written != len(piece):
                            raise OSError("Short local write while downloading OFF")
                        offset += written
                    if offset != end + 1:
                        raise OSError("Incomplete OFF range response")
                    return index
            except (requests.RequestException, OSError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Unreachable")

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(fetch_chunk, i) for i in range(count) if i not in completed]
            for future in as_completed(futures):
                completed.add(future.result())
                write_json(checkpoint, {"sha256": expected_hash, "completed": sorted(completed), "chunk_size": chunk_size})
                if len(completed) % 16 == 0 or len(completed) == count:
                    print(f"OFF raw download: {len(completed)}/{count} ranges complete", flush=True)
        os.fsync(fd)
    finally:
        os.close(fd)
    if sha256_file(partial) != expected_hash:
        checkpoint.unlink(missing_ok=True)
        raise ValueError("Downloaded OFF parquet failed the publisher's SHA-256 check")
    partial.replace(destination)
    checkpoint.unlink(missing_ok=True)
    write_json(metadata_path, {
        "source_id": "off-pinned-global-food-parquet", "url": PARQUET_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "bytes": expected_size,
        "sha256": expected_hash, "verification": "Hugging Face LFS SHA-256",
        "dataset_revision": PINNED_REVISION, "method": "Eight concurrent 64MiB HTTP ranges; one local raw file",
    })
    return destination


def run(root: Path, fetch: bool = True) -> dict:
    root = root.resolve()
    raw_dir = root / "data/raw/off"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "uk-products-current.parquet"
    output = root / "data/processed/catalogue_products.parquet"
    con = connect(root)
    try:
        if fetch:
            download_file(
                f"https://huggingface.co/api/datasets/{DATASET}/revision/{PINNED_REVISION}",
                raw_dir / "dataset-revision-api.json",
                source_id="off-dataset-metadata",
                root=root,
            )
            download_file(
                f"{SOURCE_URL}/raw/{PINNED_REVISION}/README.md",
                raw_dir / "README.source.md",
                source_id="off-dataset-card",
                root=root,
            )
        if not raw_path.exists():
            global_file = raw_dir / "food.parquet"
            if fetch:
                global_file = _download_global(root, raw_dir)
            elif not global_file.exists():
                raise FileNotFoundError(f"Missing OFF UK projection and global source under {raw_dir}")
            schema = con.execute(f"DESCRIBE SELECT * FROM read_parquet({_sql_string(global_file)})").fetchall()
            write_json(raw_dir / "schema.json", schema)
            query = (
                f"SELECT {FIELDS} FROM read_parquet({_sql_string(global_file)}) "
                "WHERE list_contains(countries_tags, 'en:united-kingdom')"
            )
            export_query(con, query, raw_path)
            _record_subset_manifest(root, raw_path, datetime.now(timezone.utc).isoformat())
        elif not raw_path.with_suffix(".provenance.json").exists():
            # Migration of the initial range-read projection made during source inspection.
            _record_subset_manifest(
                root, raw_path, datetime.fromtimestamp(raw_path.stat().st_mtime, timezone.utc).isoformat()
            )
        con.execute("CREATE TEMP TABLE _off_normalized AS " + normalized_query(raw_path))
        # Parse distinct declarations once; a typed lookup avoids a NumPy/UDF
        # dependency and retains ambiguous declarations without guessing totals.
        con.execute("""CREATE TEMP TABLE _off_parsed_quantities (
            quantity_key VARCHAR, declared_total_mass_g DOUBLE, declared_total_volume_ml DOUBLE,
            item_mass_g DOUBLE, item_volume_ml DOUBLE, pack_count INTEGER, quantity_parse_status VARCHAR
        )""")
        quantity_rows = []
        for (value,) in con.execute("SELECT DISTINCT raw_quantity FROM _off_normalized").fetchall():
            parsed = parse_quantity(value)
            quantity_rows.append((value, parsed["total_mass_g"], parsed["total_volume_ml"],
                parsed["item_mass_g"], parsed["item_volume_ml"], parsed["pack_count"], parsed["quantity_status"]))
        if quantity_rows:
            con.executemany("INSERT INTO _off_parsed_quantities VALUES (?, ?, ?, ?, ?, ?, ?)", quantity_rows)
        export_query(con, """
            WITH annotated AS (
                SELECT n.*, p.* EXCLUDE (quantity_key)
                FROM _off_normalized n LEFT JOIN _off_parsed_quantities p
                  ON n.raw_quantity IS NOT DISTINCT FROM p.quantity_key
            ), conflicts AS (
                SELECT *,
                    coalesce(abs(total_mass_g - declared_total_mass_g) > 0.01, false)
                    OR coalesce(abs(total_volume_ml - declared_total_volume_ml) > 0.01, false)
                    OR (total_mass_g IS NOT NULL AND declared_total_volume_ml IS NOT NULL)
                    OR (total_volume_ml IS NOT NULL AND declared_total_mass_g IS NOT NULL)
                    AS structured_declared_quantity_conflict
                FROM annotated
            ) SELECT * EXCLUDE (total_mass_g, total_volume_ml, quantity_basis),
                total_mass_g AS structured_total_mass_g,
                total_volume_ml AS structured_total_volume_ml,
                CASE WHEN NOT structured_declared_quantity_conflict THEN total_mass_g END AS total_mass_g,
                CASE WHEN NOT structured_declared_quantity_conflict THEN total_volume_ml END AS total_volume_ml,
                CASE WHEN structured_declared_quantity_conflict THEN 'conflicting_source_quantities'
                     ELSE quantity_basis END AS quantity_basis
            FROM conflicts
        """, output)
        metrics = con.execute(
            f"""SELECT count(*) AS rows, count(DISTINCT barcode) AS barcodes,
                count(*) FILTER (WHERE barcode IS NULL OR trim(barcode) = '') AS missing_barcode_rows,
                count(*) FILTER (WHERE product_name IS NOT NULL) AS named_rows,
                count(*) FILTER (WHERE brand IS NOT NULL AND trim(brand) != '') AS branded_rows,
                count(*) FILTER (WHERE raw_quantity IS NOT NULL AND trim(raw_quantity) != '') AS raw_quantity_rows,
                count(*) FILTER (WHERE structured_total_mass_g IS NOT NULL) AS structured_mass_rows,
                count(*) FILTER (WHERE structured_total_volume_ml IS NOT NULL) AS structured_volume_rows,
                count(*) FILTER (WHERE total_mass_g IS NOT NULL) AS accepted_current_mass_rows,
                count(*) FILTER (WHERE total_volume_ml IS NOT NULL) AS accepted_current_volume_rows,
                count(*) FILTER (WHERE ingredients_text IS NOT NULL) AS ingredient_text_rows,
                count(*) FILTER (WHERE pack_count IS NOT NULL) AS declared_count_rows,
                count(*) FILTER (WHERE structured_declared_quantity_conflict) AS structured_declared_quantity_conflicts,
                count(*) FILTER (WHERE obsolete) AS marked_obsolete_rows,
                min(off_modified_epoch_s) AS oldest_database_edit_epoch_s,
                max(off_modified_epoch_s) AS newest_database_edit_epoch_s
            FROM read_parquet({_sql_string(output)})"""
        ).fetchone()
        report = dict(
            zip(
                [
                    "rows", "barcodes", "missing_barcode_rows", "named_rows", "branded_rows", "raw_quantity_rows",
                    "structured_mass_rows", "structured_volume_rows", "accepted_current_mass_rows",
                    "accepted_current_volume_rows", "ingredient_text_rows",
                    "declared_count_rows", "structured_declared_quantity_conflicts",
                    "marked_obsolete_rows", "oldest_database_edit_epoch_s", "newest_database_edit_epoch_s",
                ],
                metrics,
            )
        )
        report.update(
            {
                "source": SOURCE_URL,
                "revision": PINNED_REVISION,
                "raw_projection": str(raw_path.relative_to(root)),
                "output": str(output.relative_to(root)),
                "raw_projection_bytes": raw_path.stat().st_size,
                "raw_global_file": "data/raw/off/food.parquet",
                "raw_global_bytes": (raw_dir / "food.parquet").stat().st_size if (raw_dir / "food.parquet").exists() else None,
                "raw_projection_sha256": json.loads(raw_path.with_suffix(".provenance.json").read_text())["sha256"],
                "duplicate_barcode_rows": report["rows"] - report["missing_barcode_rows"] - report["barcodes"],
                "historical_market_dates_verified": 0,
                "family_links_inferred": 0,
                "limitations": LIMITATIONS,
            }
        )
        report["identity_eligible_rows"] = con.execute(
            f"SELECT count(*) FROM read_parquet({_sql_string(output)}) WHERE identity_eligible"
        ).fetchone()[0]
        report["invalid_barcode_format_rows"] = con.execute(
            f"SELECT count(*) FROM read_parquet({_sql_string(output)}) WHERE NOT barcode_format_valid"
        ).fetchone()[0]
        report["duplicate_barcode_groups"] = [
            {"barcode": barcode, "records": records, "revisions": revisions, "conflicting": conflicting}
            for barcode, records, revisions, conflicting in con.execute(
                f"SELECT barcode, count(*), list(rev ORDER BY rev), bool_or(conflicting_duplicate) "
                f"FROM read_parquet({_sql_string(output)}) GROUP BY barcode HAVING count(*) > 1 ORDER BY barcode"
            ).fetchall()
        ]
        report["barcode_validation_note"] = "Identifier format only; GTIN checksums have not been validated. Duplicate barcode records remain separate and are ineligible for automatic exact-identity links."
        write_json(root / "data/reports/catalogue-source-notes.json", report)
        write_json(root / "data/reports/catalogue-audit.json", report)
        return report
    finally:
        con.close()
