"""Local-only output paths, bounded downloads, provenance, and DuckDB helpers."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_data_path(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((root / "data").resolve()):
        raise ValueError(f"Dataset output must stay under {root / 'data'}: {path}")
    return resolved


def download_file(url: str, destination: Path, *, source_id: str, root: Path) -> Path:
    """Cache raw responses under data; never overwrite an existing snapshot silently.

    Metadata records retrieval time separately from observation/publication dates.
    Content-Length validation applies to identity-encoded responses only.
    """
    destination = require_data_path(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = destination.with_name(destination.name + ".metadata.json")
    if destination.exists():
        if metadata_path.exists():
            meta = json.loads(metadata_path.read_text())
            if meta.get("url") != url:
                raise ValueError(f"Cached URL differs for {destination}; use a new snapshot path")
            if meta.get("sha256") != sha256_file(destination):
                raise ValueError(f"Cached file checksum mismatch: {destination}")
        else:
            write_json(metadata_path, {"source_id": source_id, "url": url,
                "retrieved_at": None, "metadata_created_at": utc_now(),
                "note": "Pre-existing file; retrieval time not known by this downloader",
                "bytes": destination.stat().st_size, "sha256": sha256_file(destination)})
        return destination
    temporary = destination.with_name(destination.name + ".part")
    for attempt in range(3):
        try:
            with requests.get(url, stream=True, timeout=(20, 120), headers={
                "User-Agent": "shrinkflationTrack-data-preparation/0.1 (public research)",
                "Accept-Encoding": "identity",
            }) as response:
                response.raise_for_status()
                digest = hashlib.sha256()
                size = 0
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                expected = response.headers.get("Content-Length")
                if expected and not response.headers.get("Content-Encoding") and size != int(expected):
                    raise OSError(f"Incomplete download: {size} bytes, expected {expected}")
                if not size:
                    raise OSError("Empty download")
                temporary.replace(destination)
                write_json(metadata_path, {"source_id": source_id, "url": url,
                    "final_url": response.url, "retrieved_at": utc_now(),
                    "bytes": size, "sha256": digest.hexdigest(),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "http_last_modified": response.headers.get("Last-Modified")})
                return destination
        except (requests.RequestException, OSError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def connect(root: Path):
    temp = require_data_path(root, root / "data/tmp/duckdb")
    extensions = require_data_path(root, root / "data/.cache/duckdb_extensions")
    temp.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(config={"memory_limit": "2GB", "threads": 4,
        "temp_directory": str(temp), "extension_directory": str(extensions),
        "preserve_insertion_order": False})
    return connection


def export_query(conn, query: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + ".tmp.parquet")
    conn.execute(f"COPY ({query}) TO {sql_literal(temp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    temp.replace(destination)


def export_rows(conn, rows: list[dict], schema: dict[str, str], destination: Path) -> None:
    """Explicit types preserve identifier strings and null-only columns."""
    conn.execute("DROP TABLE IF EXISTS _export_rows")
    conn.execute("CREATE TEMP TABLE _export_rows (" + ", ".join(f'"{k}" {v}' for k, v in schema.items()) + ")")
    if rows:
        conn.executemany("INSERT INTO _export_rows VALUES (" + ",".join("?" for _ in schema) + ")",
            [[row.get(key) for key in schema] for row in rows])
    export_query(conn, "SELECT * FROM _export_rows", destination)


def stable_id(prefix: str, *values) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str)
    return prefix + ":" + hashlib.sha256(encoded.encode()).hexdigest()[:24]
