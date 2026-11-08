"""Real monthly UK category outcomes with publication-buffered weekly features.

This is a current-archive retrospective dataset, not an original-vintage archive.
The fixed availability buffers below are modelling assumptions, not verified
historical release timestamps. No monthly series is interpolated into weeks.
"""
from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .common import download_file, sha256_file, utc_now, write_json

CATEGORIES = {
    "chocolate": {"name": "UK chocolate", "series": "l79x"},
    "crisps": {"name": "UK crisps", "series": "l79r"},
}
SERIES = {
    "cocoa_gbp": {"id": "icco-cocoa-london", "categories": ["chocolate"], "buffer": 7, "windows": [4, 12, 26], "volatility": True},
    "gbp_per_usd": {"id": "derived-ecb-gbp-per-usd", "categories": ["chocolate", "crisps"], "buffer": 7, "windows": [4, 12], "volatility": False},
    "maize_us_gulf": {"id": "eu-world-maize-us-gulf-3yc", "categories": ["crisps"], "buffer": 14, "windows": [4, 12], "volatility": True},
    "wheat_us_gulf": {"id": "eu-world-wheat-us-gulf-hrw", "categories": ["crisps"], "buffer": 14, "windows": [4, 12], "volatility": True},
}


def _add_months(value: date, months: int) -> date:
    number = value.year * 12 + value.month - 1 + months
    return date(number // 12, number % 12 + 1, 1)


def _url(series: str) -> str:
    return "https://www.ons.gov.uk/generator?format=csv&uri=/economy/inflationandpriceindices/timeseries/" + series + "/mm23"


def _snapshot(root: Path, series: str, offline: bool) -> tuple[Path, dict]:
    folder = root / "data/raw/ons-category"
    pointer = folder / f"latest-{series}.json"
    if pointer.exists():
        meta = json.loads(pointer.read_text())
        path = root / meta["snapshot_path"]
        if not path.exists() or sha256_file(path) != meta["sha256"]:
            raise ValueError(f"ONS snapshot checksum mismatch: {path}")
        return path, meta
    incoming = folder / "incoming" / f"{series}.csv"
    if not incoming.exists():
        if offline:
            raise FileNotFoundError(f"Offline ONS cache missing: {incoming}")
        download_file(_url(series), incoming, source_id=f"ons-{series}", root=root)
    digest = sha256_file(incoming)
    path = folder / f"{series}-{digest}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256_file(path) != digest:
        raise ValueError(f"Immutable ONS snapshot differs: {path}")
    if not path.exists():
        shutil.copyfile(incoming, path)
    original_meta = incoming.with_name(incoming.name + ".metadata.json")
    meta = json.loads(original_meta.read_text()) if original_meta.exists() else {"retrieved_at": None, "note": "Pre-existing incoming cache; original retrieval time unknown"}
    meta.update({"source_id": f"ons-{series}", "url": _url(series), "sha256": digest,
                 "snapshot_path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                 "source_frequency": "monthly", "license": "Open Government Licence v3.0; attribute ONS"})
    write_json(path.with_name(path.name + ".metadata.json"), meta)
    write_json(pointer, meta)
    return path, meta


def _parse_ons(path: Path) -> tuple[dict[date, float], dict]:
    values: dict[date, float] = {}
    fields = {}
    months = {name: number for number, name in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if len(row) < 2:
                continue
            parts = row[0].split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1] in months:
                month = date(int(parts[0]), months[parts[1]], 1)
                try:
                    value = float(row[1])
                except ValueError:
                    continue
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(f"Invalid ONS index at {month}: {row[1]}")
                if month in values and values[month] != value:
                    raise ValueError(f"Conflicting ONS observation at {month}")
                values[month] = value
            elif row[0] in {"Title", "CDID", "Unit", "Release date", "Next release"}:
                fields[row[0]] = row[1]
    if not values:
        raise ValueError(f"No monthly ONS observations: {path}")
    return dict(sorted(values.items())), fields


def _weekly_inputs(root: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    path = root / "data/processed/commodity_weekly.parquet"
    if not path.exists():
        return {}, {"status": "missing", "path": str(path.relative_to(root)), "series": {}}
    data = pd.read_parquet(path)
    needed = {"series_id", "week_end", "value"}
    if not needed.issubset(data.columns):
        raise ValueError(f"Weekly commodity schema missing {sorted(needed - set(data.columns))}")
    data["week_end"] = pd.to_datetime(data["week_end"]).dt.date
    inputs = {}
    provenance = {}
    for key, spec in SERIES.items():
        if key == "gbp_per_usd":
            gbp = data.loc[data.series_id == "ecb-gbp-per-eur", ["week_end", "value"]]
            usd = data.loc[data.series_id == "ecb-usd-per-eur", ["week_end", "value"]]
            selected = gbp.merge(usd, on="week_end", suffixes=("_gbp", "_usd"), validate="one_to_one")
            selected["value"] = selected.value_gbp / selected.value_usd
            selected = selected[["week_end", "value"]]
            provenance[key] = {"series_id": spec["id"], "derived_from": ["ecb-gbp-per-eur", "ecb-usd-per-eur"], "unit": "GBP per USD", "formula": "weekly mean GBP/EUR divided by weekly mean USD/EUR; ratio of means, not mean of daily crosses"}
        else:
            source = data.loc[data.series_id == spec["id"]]
            selected = source[["week_end", "value"]].copy()
            provenance[key] = {"series_id": spec["id"], "source_ids": sorted(source.source_id.dropna().unique().tolist()) if "source_id" in source else [],
                "units": sorted(source.unit.dropna().unique().tolist()) if "unit" in source else [],
                "currencies": sorted(source.currency.dropna().unique().tolist()) if "currency" in source else [],
                "source_urls": sorted(source.source_url.dropna().unique().tolist()) if "source_url" in source else [],
                "source_frequencies": sorted(source.source_frequency.dropna().unique().tolist()) if "source_frequency" in source else [],
                "roll_conventions": sorted(source.roll_convention.dropna().unique().tolist()) if "roll_convention" in source else []}
        selected = selected.loc[np.isfinite(selected.value) & (selected.value > 0)].sort_values("week_end").reset_index(drop=True)
        if selected.week_end.duplicated().any():
            raise ValueError(f"Duplicate weekly series dates: {key}")
        inputs[key] = selected
        provenance[key].update({"weekly_rows": len(selected), "first_week_end": str(selected.week_end.min()) if len(selected) else None,
            "last_week_end": str(selected.week_end.max()) if len(selected) else None, "availability_buffer_days": spec["buffer"]})
    return inputs, {"status": "current_archive", "path": str(path.relative_to(root)), "sha256": sha256_file(path), "series": provenance}


def _commodity_names(key: str, spec: dict) -> list[str]:
    return [f"commodity_{key}_return_{window}w_pct" for window in spec["windows"]] + ([f"commodity_{key}_volatility_12w_pct"] if spec["volatility"] else [])


def _weekly_features(inputs: dict[str, pd.DataFrame], category: str, cutoff: date) -> tuple[dict, str | None]:
    features = {}
    ends = []
    for key, spec in SERIES.items():
        features.update({name: np.nan for name in _commodity_names(key, spec)})
        if category not in spec["categories"] or key not in inputs:
            continue
        series = inputs[key]
        series = series.loc[series.week_end <= cutoff - timedelta(days=spec["buffer"])]
        if series.empty:
            continue
        latest = series.iloc[-1]
        if (cutoff - latest.week_end).days > 35:
            continue
        ends.append(latest.week_end)
        for window in spec["windows"]:
            boundary = latest.week_end - timedelta(weeks=window)
            older = series.loc[series.week_end <= boundary]
            if not older.empty and (boundary - older.iloc[-1].week_end).days <= 10:
                features[f"commodity_{key}_return_{window}w_pct"] = 100 * (latest.value / older.iloc[-1].value - 1)
        if spec["volatility"]:
            recent = series.loc[series.week_end >= latest.week_end - timedelta(weeks=12)].copy()
            gaps = recent.week_end.diff().map(lambda value: value.days if pd.notna(value) else np.nan)
            returns = recent.value.pct_change(fill_method=None).where((gaps >= 5) & (gaps <= 9)) * 100
            if returns.count() >= 8:
                features[f"commodity_{key}_volatility_12w_pct"] = float(returns.std(ddof=1))
    return features, max(ends).isoformat() if ends else None


def _build_category_frame(indices: dict[str, dict[date, float]], inputs: dict[str, pd.DataFrame], as_of: date) -> pd.DataFrame:
    rows = []
    live_month = _add_months(as_of, 1)
    for category, index in indices.items():
        changes = {month: 100 * (value / index[_add_months(month, -1)] - 1)
                   for month, value in index.items() if _add_months(month, -1) in index}
        targets = [month for month in changes if month >= date(2016, 1, 1) and _add_months(month, 2) <= as_of]
        for target in targets + [live_month]:
            live = target == live_month
            issue_month = _add_months(target, -1)
            cutoff = as_of if live else issue_month.replace(day=8)
            ceiling = _add_months(issue_month, -2)
            known = sorted(month for month in index if month <= ceiling)
            latest = known[-1] if known else None
            row = {"category_id": category, "category_name": CATEGORIES[category]["name"], "target_month": target.isoformat(),
                "forecast_cutoff": datetime.combine(cutoff, time(), ZoneInfo("Europe/London")).isoformat(),
                "label_available_date": _add_months(target, 2).isoformat(), "target_change_pct": np.nan if live else changes[target],
                "is_live": live, "baseline_zero": 0.0, "latest_known_cpi_month": latest.isoformat() if latest else None}
            for lag in (0, 1, 2, 3, 6, 12):
                row[f"history_change_lag{lag}_pct"] = changes.get(_add_months(latest, -lag), np.nan) if latest else np.nan
            for window in (3, 6, 12):
                values = [changes.get(_add_months(latest, -lag), np.nan) for lag in range(window)] if latest else []
                complete = len(values) == window and all(math.isfinite(value) for value in values)
                row[f"history_mean_{window}m_pct"] = float(np.mean(values)) if complete else np.nan
                row[f"history_std_{window}m_pct"] = float(np.std(values, ddof=1)) if complete else np.nan
            seasonal_month = _add_months(target, -12)
            row["baseline_seasonal"] = changes.get(seasonal_month, np.nan) if seasonal_month <= ceiling else np.nan
            row["baseline_recent"] = row["history_change_lag0_pct"]
            row["baseline_trailing_mean"] = row["history_mean_3m_pct"]
            row["season_sin"] = math.sin(2 * math.pi * target.month / 12)
            row["season_cos"] = math.cos(2 * math.pi * target.month / 12)
            commodities, maximum_end = _weekly_features(inputs, category, cutoff)
            row.update(commodities)
            row["max_commodity_week_end"] = maximum_end
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["category_id", "target_month"]).reset_index(drop=True)


def prepare_category_data(root: Path, as_of: date, offline: bool = False) -> tuple[pd.DataFrame, dict]:
    """Cache source snapshots, prepare real outcomes/features, and save artifacts.

    ``offline`` forbids source downloads. Existing immutable snapshots are reused
    even online; remove the latest pointer deliberately to request a new capture.
    Historical rows contain only labels conservatively available by ``as_of``.
    Live rows are next calendar month, with unknown labels retained as NaN.
    """
    root = root.resolve()
    indices, ons_metadata = {}, {}
    for category, spec in CATEGORIES.items():
        path, provenance = _snapshot(root, spec["series"], offline)
        index, fields = _parse_ons(path)
        if spec["series"].upper() != fields.get("CDID"):
            raise ValueError(f"Unexpected ONS series: {fields.get('CDID')}")
        indices[category] = index
        ons_metadata[category] = {**provenance, "ons_fields": fields, "observations": len(index),
            "first_month": min(index).isoformat(), "last_month": max(index).isoformat()}
    inputs, weekly_metadata = _weekly_inputs(root)
    frame = _build_category_frame(indices, inputs, as_of)
    category_features = {category: [name for key, spec in SERIES.items() if category in spec["categories"] for name in _commodity_names(key, spec)] for category in CATEGORIES}
    coverage = {category: {"observed_target_rows": int(((frame.category_id == category) & ~frame.is_live).sum()),
        "live_rows": int(((frame.category_id == category) & frame.is_live).sum()),
        "feature_nonmissing_rows": {name: int(frame.loc[frame.category_id == category, name].notna().sum()) for name in category_features[category]}}
        for category in CATEGORIES}
    metadata = {"schema_version": 1, "generated_at": utc_now(), "as_of": as_of.isoformat(),
        "scope": "UK category CPI percentage changes; not SKU prices or shrinkflation probabilities", "target_frequency": "monthly",
        "commodity_input_frequency": "genuine weekly observations, including daily-to-weekly source aggregates",
        "target_formula": "100 * (category CPI index in target month / previous calendar month index - 1)",
        "historical_forecast_cutoff": "00:00 Europe/London on eighth day of previous calendar month",
        "live_forecast_cutoff": "as_of date, 00:00 Europe/London; target is next calendar month",
        "cpi_feature_policy": "Only index observations through issue month minus two calendar months; calendar gaps are not filled",
        "label_availability_policy": "First day of target month plus two months, conservatively after usual following-month ONS publication",
        "availability_status": "current_archive_with_explicit_buffer_assumptions_not_original_vintages",
        "weekly_availability_policy": "Completed weekly period plus seven days for ICCO/ECB, fourteen for EU; stale beyond35days becomes missing",
        "category_commodity_features": category_features, "sources": {"ons": ons_metadata, "weekly": weekly_metadata}, "coverage": coverage,
        "limitations": ["Archive revisions are not reconstructed; buffers are explicit assumptions, not verified historical release timestamps.",
            "Category indices do not establish individual brand, retailer, pack-size or recipe changes.",
            "Cocoa, grain and exchange-rate references are proxies, not manufacturer purchase contracts or a complete ingredient cost model.",
            "No monthly commodity interpolation; no monthly World Bank values used as weekly inputs.",
            "Historical targets are observed values; missing labels and inapplicable or missing commodity features remain NaN."]}
    output = root / "data/experiments/category_forecast"
    output.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output / "dataset.parquet", index=False)
    metadata["dataset_sha256"] = sha256_file(output / "dataset.parquet")
    write_json(output / "metadata.json", metadata)
    return frame, metadata
