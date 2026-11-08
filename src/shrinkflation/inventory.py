"""Inventory frozen raw inputs and expose prepared tables through one DuckDB."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .common import sha256_file, sql_literal, utc_now, write_json


def run(root: Path, fetch: bool = True) -> dict:
    files = []
    for path in sorted((root / "data/raw").rglob("*")):
        if not path.is_file() or path.name.endswith((".part", ".tmp")):
            continue
        meta = path.with_name(path.name + ".metadata.json")
        provenance = path.with_suffix(".provenance.json")
        item = {"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
            "sha256": sha256_file(path)}
        for label, candidate in (("download_metadata",meta),("projection_provenance",provenance)):
            if candidate.exists() and candidate != path:
                item[label] = str(candidate.relative_to(root))
                expected = json.loads(candidate.read_text()).get("sha256")
                if expected and expected != item["sha256"]:
                    raise ValueError(f"Raw input differs from its saved checksum: {path}")
        files.append(item)
    original_manifest = json.loads((root / "research/source-manifest.json").read_text())
    copied_verification = []
    for entry in original_manifest["files"]:
        path = (root / entry["file"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Copy manifest path leaves the project")
        if not path.exists() or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Original copied evidence is missing or changed: {entry['file']}")
        copied_verification.append({"path":entry["file"],"sha256":entry["sha256"],"verified":True})
    raw_inventory = {"generated_at":utc_now(),"raw_files": files,
        "raw_bytes": sum(f["bytes"] for f in files),
        "original_copy_manifest":"research/source-manifest.json",
        "original_copy_verification":copied_verification}
    write_json(root / "data/reports/raw-inventory.json",raw_inventory)
    processed = root / "data/processed"
    database = processed / "shrinkflation.duckdb"
    conn = duckdb.connect(str(database))
    tables = []
    try:
        for path in sorted(processed.glob("*.parquet")):
            if path.stem.endswith(".tmp"):
                continue
            view = path.stem
            conn.execute(f'CREATE OR REPLACE VIEW "{view}" AS SELECT * FROM read_parquet({sql_literal(path)})')
            columns = conn.execute(f'DESCRIBE "{view}"').fetchall()
            tables.append({"view":view,"parquet":str(path.relative_to(root)),"bytes":path.stat().st_size,
                "rows":conn.execute(f'SELECT count(*) FROM "{view}"').fetchone()[0],
                "columns":[{"name":c[0],"type":c[1]} for c in columns]})
    finally:
        conn.close()
    write_json(root / "data/reports/schema.json",{"database":str(database.relative_to(root)),"tables":tables})
    reports = {}
    for path in sorted((root / "data/reports").glob("*-audit.json")):
        if path.name == "completion-audit.json":
            continue  # Runtime verification is separate and may finish after preparation.
        reports[path.stem] = json.loads(path.read_text())
    evaluation = root / "data/reports/evaluation.json"
    if evaluation.exists():
        reports["evaluation"] = json.loads(evaluation.read_text())
    summary = {"generated_at":utc_now(),"prepared_tables":len(tables),"raw_bytes":raw_inventory["raw_bytes"],
        "target_cadence":"monthly grocery unit-price outcomes","commodity_cadence":"weekly",
        "status":"prepared_for_inspection_and_family_review_not_validated_model_training",
        "reports":reports,
        "completion_audit_file":"data/reports/completion-audit.json",
        "remaining_work":["Review retailer/OFF identity candidates and reconstruct supported replacement histories.",
            "Resolve unit-price anomalies and collect dated pack and ingredient evidence for additional families.",
            "Establish row-specific commodity publication/vintage timing before leakage-safe backtesting.",
            "Acquire longer retail time coverage; four calendar months do not support broad lag conclusions.",
            "Choose model cohort and chronological cutoffs only after inspecting eligibility reports."]}
    write_json(root / "data/reports/preparation-summary.json",summary)
    return {"tables":len(tables),"raw_files":len(files),"raw_bytes":raw_inventory["raw_bytes"]}
