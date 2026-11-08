"""Evidence-preserving commodity ETL. Retail targets remain monthly.

Public source snapshots are cached inside data/raw/commodities. Native weekly
quotes and daily observations are kept distinct before forming W-FRI buckets.
Unknown historical publication times remain null; a retrieval date is not a
historical availability date, and current archives are not vintage backtests.
"""
from __future__ import annotations

import csv
import html
import io
import json
import math
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from .common import (connect, download_file, export_query, require_data_path,
                     sha256_file, sql_literal, stable_id, utc_now, write_json)


ICCO_PAGE = "https://www.icco.org/statistics/statistics_2025/"
ICCO_CURRENT_PAGE = "https://www.icco.org/statistics/"
EU_CEREALS_PAGE = "https://agriculture.ec.europa.eu/data-and-analysis/markets/overviews/market-observatories/crops/cereals-statistics_en"
EU_OILSEEDS_PAGE = "https://agriculture.ec.europa.eu/data-and-analysis/markets/overviews/market-observatories/crops/oilseeds-and-protein-crops_en"
ECB_PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
WB_PAGE = "https://www.worldbank.org/en/research/commodity-markets"

DOWNLOADS = [
    ("icco-statistics-page.html", ICCO_PAGE),
    ("icco-current-statistics-page.html", ICCO_CURRENT_PAGE),
    ("ecb-eurofxref-hist.zip", "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"),
    ("ecb-fx-methodology.html", ECB_PAGE),
    ("ecb-disclaimer.html", "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html"),
    ("eu-cereal-prices.xlsx", "https://circabc.europa.eu/sd/a/2f167193-3c01-46fb-b1da-a951cbb4b0db/cereals-eu-prices.xlsx"),
    ("eu-world-cereal-prices.xlsx", "https://circabc.europa.eu/sd/a/bc2f8af9-c12b-41ee-b3a6-231457a0e52d/cereals-world-prices.xlsx"),
    ("eu-world-oilseed-prices.xlsx", "https://circabc.europa.eu/sd/a/2ddd7dcd-dff1-41b5-94b9-6cd207181a3c/oliseeds-world-prices.xlsx"),
    ("eu-cereals-page.html", EU_CEREALS_PAGE),
    ("eu-oilseeds-page.html", EU_OILSEEDS_PAGE),
    ("eu-reuse-notice.html", "https://commission.europa.eu/legal-notice_en"),
]

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_sheets(path: Path) -> dict[str, list[tuple[int, dict[str, str]]]]:
    """Read original/cached cell values only; no spreadsheet authoring or recalculation.

    Formula cells use their source-provided cached value, never a new computation.
    This also handles shared and inline strings without installing Excel libraries.
    """
    result = {}
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.itertext()) for t in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        relationships = {
            x.attrib["Id"]: x.attrib["Target"]
            for x in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        if workbook.find("s:workbookPr", NS) is not None:
            if workbook.find("s:workbookPr", NS).get("date1904") in ("1", "true"):
                raise ValueError(f"Unsupported 1904 date system: {path}")
        for sheet in workbook.find("s:sheets", NS):
            target = relationships[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = []
            for row in ET.fromstring(archive.read(member)).findall("s:sheetData/s:row", NS):
                values = {}
                for cell in row:
                    address = cell.get("r", "")
                    column = re.sub(r"\d", "", address)
                    value = cell.find("s:v", NS)
                    text = value.text if value is not None else ""
                    if cell.get("t") == "s" and text:
                        text = shared[int(text)]
                    elif cell.get("t") == "inlineStr":
                        inline = cell.find("s:is", NS)
                        text = "".join(inline.itertext()) if inline is not None else ""
                    if text is not None:
                        values[column] = text
                rows.append((int(row.get("r")), values))
            result[sheet.attrib["name"]] = rows
    return result


def excel_date(value: str) -> date:
    return date(1899, 12, 30) + timedelta(days=int(float(value)))


def number(value) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def friday_bucket(observed_date: date) -> tuple[date, date]:
    end = observed_date + timedelta(days=(4 - observed_date.weekday()) % 7)
    return end - timedelta(days=6), end


def _icco_download(root: Path, page: Path, table_id: int) -> Path:
    folder = root / "data/raw/commodities"
    output = require_data_path(root, folder / f"icco-daily-prices-table{table_id}.json")
    metadata = output.with_name(output.name + ".metadata.json")
    if output.exists():
        if not metadata.exists() or json.loads(metadata.read_text()).get("sha256") != sha256_file(output):
            raise ValueError(f"Missing/invalid ICCO snapshot provenance: {output}")
        return output
    nonce = re.search(fr'id="wdtNonceFrontendServerSide_{table_id}"[^>]*value="([^\"]+)"', page.read_text())
    if not nonce:
        raise ValueError(f"Public ICCO table {table_id} no longer appears on {page.name}")
    url = f"https://www.icco.org/wp-admin/admin-ajax.php?action=get_wdtable&table_id={table_id}"
    body = {"draw": 1, "start": 0, "length": -1, "wdtNonce": nonce.group(1)}
    response = requests.post(url, data=body, timeout=(15, 45))
    response.raise_for_status()
    payload = response.json()
    if len(payload["data"]) != int(payload["recordsTotal"]):
        raise ValueError("ICCO public-table export was truncated")
    output.write_bytes(response.content)
    write_json(metadata, {"source_id": "icco-daily-prices", "url": url,
        "method": "POST", "body": body, "retrieved_at": utc_now(),
        "bytes": output.stat().st_size, "sha256": sha256_file(output),
        "source_page": ICCO_PAGE if table_id == 14 else ICCO_CURRENT_PAGE})
    return output


def _record(*, source_id, series_id, series_name, commodity, observed_date,
            raw_value, unit, currency, market, stage, source_file, locator,
            source_url, frequency="daily", period_start=None, period_end=None,
            roll="not_applicable", license_status="review_required", **extra):
    return {"observation_id": stable_id("commodity", source_id, series_id, locator, raw_value),
        "source_id": source_id, "series_id": series_id, "series_name": series_name,
        "commodity": commodity, "observation_date": observed_date.isoformat(),
        "source_period_start": (period_start or observed_date).isoformat(),
        "source_period_end": (period_end or observed_date).isoformat(),
        "source_frequency": frequency, "value": number(raw_value), "raw_value": str(raw_value),
        "unit": unit, "raw_unit": extra.pop("raw_unit", unit),
        "unit_definition_status": extra.pop("unit_definition_status", "declared_source_unit"),
        "currency": currency, "market": market, "market_stage": stage,
        "roll_convention": roll, "available_at": None, "publication_known": False,
        "availability_note": "Latest historical archive; original row publication times/vintages not supplied. Retrieval time is separate.",
        "eligible_for_backtest": False, "license_status": license_status,
        "source_file": str(source_file), "raw_locator": locator,
        "source_url": source_url, "is_estimated": False, "is_calculated": False,
        "is_confidential": False, **extra}


def parse_icco(folder: Path) -> tuple[list[dict], dict]:
    rows, skipped = [], []
    fields = [(2, "london", "GBP", "London futures nearest-three average"),
              (3, "newyork", "USD", "New York futures nearest-three average"),
              (4, "daily-usd", "USD", "ICCO daily price"),
              (5, "daily-eur", "EUR", "ICCO daily price")]
    roll = "Average nearest three active ICE London/New York futures months; shift on 15th of month preceding nearest maturing month; London conversion uses six-month forward FX. See ICCO methodology."
    for path in sorted(folder.glob("icco-daily-prices-table*.json")):
        if not re.fullmatch(r"icco-daily-prices-table\d+\.json", path.name):
            continue
        payload = json.loads(path.read_text())
        for index, values in enumerate(payload["data"]):
            try:
                observed = datetime.strptime(values[1], "%d/%m/%Y").date()
            except (ValueError, IndexError):
                skipped.append({"source_file": path.name, "row": index, "values": values, "reason": "invalid_or_blank_date"})
                continue
            for position, code, currency, name in fields:
                rows.append(_record(source_id="icco", series_id="icco-cocoa-" + code,
                    series_name=name, commodity="cocoa", observed_date=observed,
                    raw_value=values[position], unit="per_metric_tonne", currency=currency,
                    market="ICE London/New York" if position >= 4 else name.split()[0],
                    stage="futures_reference", source_file="data/raw/commodities/" + path.name,
                    locator=f"data[{index}],wdt_id={values[0]},column={position}",
                    source_url=ICCO_PAGE, roll=roll,
                    raw_unit={"GBP": "£ sterling/tonne", "USD": "US$/tonne", "EUR": "Euro/tonne"}[currency]))
    # Duplicated public tables are provenance duplicates; conflicting values stay separate.
    unique, conflicts = {}, []
    for row in rows:
        key = row["series_id"], row["observation_date"]
        if key in unique and unique[key]["value"] != row["value"]:
            conflicts.append({"key": key, "first": unique[key], "second": row})
        elif key not in unique:
            unique[key] = row
    if conflicts:
        raise ValueError(f"Conflicting ICCO dates need review: {len(conflicts)}")
    return list(unique.values()), {"invalid_date_rows": skipped, "duplicate_observations_removed": len(rows) - len(unique)}


def parse_ecb(path: Path) -> list[dict]:
    rows = []
    with zipfile.ZipFile(path) as archive:
        text = archive.read("eurofxref-hist.csv").decode("utf-8-sig")
    for index, entry in enumerate(csv.DictReader(io.StringIO(text), skipinitialspace=True), start=2):
        observed = date.fromisoformat(entry["Date"])
        for currency in ("GBP", "USD"):
            if not entry.get(currency):
                continue
            rows.append(_record(source_id="ecb", series_id=f"ecb-{currency.lower()}-per-eur",
                series_name=f"ECB {currency} per EUR reference rate", commodity="fx",
                observed_date=observed, raw_value=entry[currency], unit=f"{currency}_per_EUR",
                currency=currency, market="ECB", stage="reference_exchange_rate",
                source_file="data/raw/commodities/" + path.name,
                locator=f"eurofxref-hist.csv:row={index},column={currency}", source_url=ECB_PAGE,
                raw_unit=f"{currency} per 1 EUR",
                license_status="ecb_reuse_with_attribution",
                availability_note="ECB normally publishes around 16:00 CET. This archive does not supply original release timestamps or vintages; no row-specific availability asserted."))
    return rows


def parse_world_weekly(path: Path, kind: str) -> list[dict]:
    rows = []
    data = dict(xlsx_sheets(path)["Data"])
    labels = data[2]
    # Source's dollar columns only. EUR versions are workbook FX conversions.
    columns = "BCDEFGHIJKL" if kind == "cereal" else "BCDEFGHIJK"
    if labels.get("A") != "Wednesday":
        raise ValueError(f"Unexpected weekly source date header: {path}")
    for row_index, entry in data.items():
        if row_index < 3 or not entry.get("A"):
            continue
        try:
            observed = excel_date(entry["A"])
        except ValueError:
            continue
        for column in columns:
            label = labels.get(column)
            if not label:
                continue
            commodity = label.split(" - ")[0].lower().replace(" ", "_")
            rows.append(_record(source_id="eu-world-" + kind,
                series_id="eu-world-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                series_name=label, commodity=commodity, observed_date=observed,
                raw_value=entry.get(column, ""), unit="per_source_ton" if kind == "cereal" else "per_metric_tonne", currency="USD",
                market=label.partition(" - ")[2], stage="FOB_export_reference",
                source_file="data/raw/commodities/" + path.name, locator=f"Data!{column}{row_index}",
                source_url=EU_CEREALS_PAGE if kind == "cereal" else EU_OILSEEDS_PAGE,
                raw_unit="$/ton" if kind == "cereal" else "$/t",
                frequency="weekly_quote", license_status="check_underlying_world_quote_rights",
                unit_definition_status="unknown_ton_definition" if kind == "cereal" else "source_t_symbol_tonne",
                availability_note="Wednesday is the quoted observation date, not a verified publication date. World oilseed rows are seeds, not crude oil prices."))
    return rows


def parse_eu_cereals(path: Path) -> list[dict]:
    data = xlsx_sheets(path)["Data_excl.conf."]
    labels = dict(data)[1]
    required = {"A": "Member State Code", "C": "Detailed Product", "G": "Dt Begin Period",
                "H": "Dt End Period", "M": "Vl Euro Price", "R": "Place of Quotation"}
    if any(labels.get(k) != v for k, v in required.items()):
        raise ValueError("EU cereal source schema changed")
    rows = []
    for index, entry in data:
        if index == 1 or not entry.get("G"):
            continue
        start, end = excel_date(entry["G"]), excel_date(entry["H"])
        label, market, stage, country = entry.get("C", ""), entry.get("R", ""), entry.get("D", ""), entry.get("A", "")
        flags = {name: entry.get(col) in ("1", "true", "TRUE") for col, name in
                 [("O", "is_estimated"), ("P", "is_calculated"), ("Q", "is_confidential")]}
        rows.append(_record(source_id="eu-cereal-notifications",
            series_id=stable_id("eu-cereal", country, label, market, stage), series_name=label,
            commodity=label.lower().replace(" ", "_"), observed_date=end,
            raw_value=entry.get("M", ""), unit="per_metric_tonne", currency="EUR",
            market=f"{country} - {market}", stage=stage,
            source_file="data/raw/commodities/" + path.name, locator=f"Data_excl.conf.!M{index}",
            source_url=EU_CEREALS_PAGE, frequency="weekly_interval", period_start=start,
            period_end=end, license_status="eu_reuse_with_attribution",
            raw_unit="€/tonne (Vl Euro Price)",
            source_raw_json=json.dumps(entry, ensure_ascii=False), **flags))
    return rows


def parse_worldbank(path: Path) -> list[dict]:
    data = dict(xlsx_sheets(path)["Monthly Prices"])
    names, units = data[5], data[6]
    rows = []
    for index, entry in data.items():
        period = entry.get("A", "")
        if not re.fullmatch(r"\d{4}M\d{2}", period):
            continue
        for column, name in names.items():
            if column == "A" or not name:
                continue
            rows.append({"source_id": "worldbank-monthly", "series_id": stable_id("wb", name),
                "series_name": name, "month": f"{period[:4]}-{period[-2:]}-01",
                "value": number(entry.get(column)), "raw_value": entry.get(column, ""),
                "unit": units.get(column), "currency": "USD" if "$" in units.get(column, "") else None,
                "source_frequency": "monthly", "available_at": None,
                "publication_known": False, "eligible_as_weekly_input": False,
                "source_file": "data/raw/commodities/" + path.name,
                "raw_locator": f"Monthly Prices!{column}{index}", "source_url": WB_PAGE})
    return rows


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(root: Path, fetch: bool = True) -> dict:
    root = root.resolve()
    folder = root / "data/raw/commodities"
    if fetch:
        for name, url in DOWNLOADS:
            download_file(url, folder / name, source_id=name.split(".")[0], root=root)
        _icco_download(root, folder / "icco-statistics-page.html", 14)
        _icco_download(root, folder / "icco-current-statistics-page.html", 26)
    required = [folder / name for name, _ in DOWNLOADS if name.endswith((".zip", ".xlsx"))]
    required += [folder / "icco-daily-prices-table14.json", folder / "worldbank-monthly.xlsx"]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"Missing commodity snapshot; run with fetch enabled: {path}")
    cocoa, cocoa_audit = parse_icco(folder)
    rows = cocoa + parse_ecb(folder / "ecb-eurofxref-hist.zip")
    rows += parse_world_weekly(folder / "eu-world-cereal-prices.xlsx", "cereal")
    rows += parse_world_weekly(folder / "eu-world-oilseed-prices.xlsx", "oilseed")
    rows += parse_eu_cereals(folder / "eu-cereal-prices.xlsx")
    monthly = parse_worldbank(folder / "worldbank-monthly.xlsx")
    interim = root / "data/interim/commodities/observations.jsonl"
    _jsonl(interim, rows)
    monthly_path = root / "data/interim/commodities/worldbank-monthly.jsonl"
    _jsonl(monthly_path, monthly)
    conn = connect(root)
    source = f"read_json_auto({sql_literal(interim)}, sample_size=-1, maximum_object_size=16777216)"
    conn.execute(f"CREATE TEMP TABLE commodity_observations AS SELECT * REPLACE (CAST(observation_date AS DATE) AS observation_date, CAST(source_period_start AS DATE) AS source_period_start, CAST(source_period_end AS DATE) AS source_period_end, CAST(available_at AS TIMESTAMPTZ) AS available_at) FROM {source}")
    out = root / "data/processed"
    export_query(conn, "SELECT * FROM commodity_observations ORDER BY series_id, observation_date, raw_locator", out / "commodity_observations.parquet")
    export_query(conn, "SELECT * FROM commodity_observations WHERE source_frequency='daily' ORDER BY series_id, observation_date", out / "commodity_daily.parquet")
    # Real quotes only. No missing-value imputation or forward filling. Mon-Sun
    # native reporting intervals enter the Friday bucket AFTER their Sunday end.
    conn.execute("""CREATE TEMP VIEW commodity_values_clean AS
        SELECT * FROM commodity_observations
        WHERE value > 0 AND NOT is_estimated AND NOT is_calculated AND NOT is_confidential
        QUALIFY count(DISTINCT value) OVER (PARTITION BY series_id, observation_date)=1
            AND row_number() OVER (PARTITION BY series_id, observation_date ORDER BY raw_locator)=1""")
    conflicts = conn.execute("""SELECT series_id, observation_date, count(*) AS source_rows,
        count(DISTINCT value) AS distinct_values FROM commodity_observations
        WHERE value > 0 AND NOT is_estimated AND NOT is_calculated AND NOT is_confidential
        GROUP BY series_id, observation_date HAVING count(DISTINCT value)>1
        ORDER BY series_id, observation_date""").fetchall()
    conn.execute("""CREATE TEMP TABLE weekly_base AS
        WITH bucketed AS (
            SELECT *, observation_date + CAST((4 - isodow(observation_date) + 1 + 7) % 7 AS INTEGER) AS bucket_end
            FROM commodity_values_clean
        )
        SELECT series_id, any_value(source_id) AS source_id, any_value(series_name) AS series_name,
            any_value(commodity) AS commodity, bucket_end-6 AS week_start, bucket_end AS week_end,
            avg(value) AS value, arg_max(value, observation_date) AS last_value,
            any_value(unit) AS unit, any_value(raw_unit) AS raw_unit,
            any_value(unit_definition_status) AS unit_definition_status, any_value(currency) AS currency,
            any_value(market) AS market, any_value(market_stage) AS market_stage,
            any_value(source_frequency) AS source_frequency, count(*) AS observation_count,
            min(observation_date) AS first_observation_date, max(observation_date) AS last_observation_date,
            min(source_period_start) AS source_period_start, max(source_period_end) AS source_period_end,
            CAST(NULL AS TIMESTAMPTZ) AS available_at, false AS publication_known,
            false AS eligible_for_backtest,
            'Original publication times and source vintages unresolved; do not equate period end with historical availability.' AS availability_note,
            any_value(license_status) AS license_status, any_value(roll_convention) AS roll_convention,
            any_value(source_url) AS source_url, list(observation_id ORDER BY observation_date, observation_id) AS observation_ids
        FROM bucketed GROUP BY series_id, bucket_end""")
    export_query(conn, """WITH previous AS (
        SELECT *, lag(value) OVER w AS previous_week_value,
            lag(week_end) OVER w AS previous_week_end FROM weekly_base
        WINDOW w AS (PARTITION BY series_id ORDER BY week_end))
        SELECT *, CASE WHEN week_end - previous_week_end = 7
            THEN 100*(value/previous_week_value-1) ELSE NULL END AS change_pct_1w
        FROM previous ORDER BY series_id, week_end""", out / "commodity_weekly.parquet")
    export_query(conn, f"SELECT * REPLACE (CAST(month AS DATE) AS month, CAST(available_at AS TIMESTAMPTZ) AS available_at) FROM read_json_auto({sql_literal(monthly_path)}, sample_size=-1) ORDER BY series_id, month", out / "commodity_monthly_support.parquet")
    summary = conn.execute("""SELECT source_id, count(*) AS observations, count(DISTINCT series_id) AS series,
        min(observation_date) AS date_min, max(observation_date) AS date_max,
        count(*) FILTER (WHERE value IS NULL) AS missing_values,
        count(*) FILTER (WHERE is_estimated OR is_calculated OR is_confidential) AS flagged_values
        FROM commodity_observations GROUP BY source_id ORDER BY source_id""").fetchall()
    weekly_count = conn.execute("SELECT count(*) FROM weekly_base").fetchone()[0]
    monthly_overlap = conn.execute("""WITH months AS (
        SELECT CAST(month AS DATE) AS month FROM generate_series(DATE '2024-01-01', DATE '2024-04-01', INTERVAL '1 month') t(month)
        ), sources AS (SELECT DISTINCT source_id FROM commodity_observations)
        SELECT sources.source_id, months.month, count(o.observation_id) AS source_rows,
            count(o.value) AS nonmissing_values, count(DISTINCT o.series_id) AS series_with_observation,
            min(o.observation_date) AS observed_date_min, max(o.observation_date) AS observed_date_max,
            count(o.observation_id) FILTER (WHERE o.eligible_for_backtest AND o.available_at IS NOT NULL) AS strict_available_rows
        FROM months CROSS JOIN sources LEFT JOIN commodity_observations o
            ON o.source_id=sources.source_id AND date_trunc('month', o.observation_date)=months.month
        GROUP BY sources.source_id, months.month ORDER BY sources.source_id, months.month""").fetchall()
    exact_overlap = conn.execute("""SELECT source_id, count(*) AS source_rows,
        count(value) AS nonmissing_values, count(DISTINCT series_id) AS series_with_observation,
        min(observation_date) AS observed_date_min, max(observation_date) AS observed_date_max
        FROM commodity_observations WHERE observation_date BETWEEN DATE '2024-01-09' AND DATE '2024-04-13'
        GROUP BY source_id ORDER BY source_id""").fetchall()
    report = {"generated_at": utc_now(), "status": "formatted_with_explicit_coverage_and_availability_gaps",
        "observations": len(rows), "weekly_rows": weekly_count, "monthly_support_rows": len(monthly),
        "sources": [dict(zip(["source_id", "observations", "series", "date_min", "date_max", "missing_values", "flagged_values"], row)) for row in summary],
        "cocoa_audit": cocoa_audit,
        "conflicting_series_dates_excluded_from_weekly": len(conflicts),
        "conflicting_series_dates_sample": [dict(zip(["series_id", "observation_date", "source_rows", "distinct_values"], row)) for row in conflicts[:20]],
        "weekly_values_policy": "Identical series/date/value duplicates counted once. Conflicting values for the same series/date are excluded from weekly aggregation; raw observations retained.",
        "unit_review": {
            "icco": "Official table headers are GBP sterling/tonne, US dollars/tonne and euros/tonne. No pence scaling or unit conversion performed. raw_unit preserves source labels.",
            "ecb": "GBP and USD columns quote currency units per 1 EUR. USD per GBP = (USD per EUR)/(GBP per EUR). Original rates exported; no cross-rate or current-FX substitution performed.",
            "eu_world": "Source workbook headings $/ton for cereal and $/t for oilseeds. Cereal unit retained as per_source_ton, unit_definition_status=unknown_ton_definition because a metric/short-ton definition was not independently established. Oilseed t is the source tonne symbol. No numeric mass/currency conversion performed. Source raw_unit preserved.",
            "eu_cereal": "Vl Euro Price is euro/tonne. National price and currency remain in source_raw_json; normalized output uses the published euro price, without another FX conversion.",
            "identity": "series IDs distinguish commodity, market, currency and stage. Different countries, quoted locations, stages and original currencies are never averaged into a common price."},
        "retail_panel_overlap": {"retail_date_min": "2024-01-09", "retail_date_max": "2024-04-13",
            "note": "Observation-date overlap only; does not establish historical availability or vintages.",
            "sources": [dict(zip(["source_id", "source_rows", "nonmissing_values", "series_with_observation", "observed_date_min", "observed_date_max"], row)) for row in exact_overlap]},
        "monthly_2024_overlap": [dict(zip(["source_id", "month", "source_rows", "nonmissing_values", "series_with_observation", "observed_date_min", "observed_date_max", "strict_available_rows"], row)) for row in monthly_overlap],
        "weekly_method": "W-FRI Saturday-Friday: mean of real daily observations, or weekly quoted points. Native weekly source intervals are retained. No interpolation/filling; changes require adjacent weekly buckets.",
        "publication_times": "available_at=NULL,publication_known=false,eligible_for_backtest=false until historical release/vintage policy is verified. ECB normal 16:00 CET schedule alone is not a row-specific timestamp.",
        "gaps": ["No genuine daily/weekly sugar feed acquired.",
            "World oilseed quotations are seeds, not crude vegetable oils; no dedicated weekly crude-oil feed acquired.",
            "ICCO and world-reference quote redistribution/training permissions are not established by public accessibility. License_status records review requirements.",
            "Current downloaded archives may revise historical observations; original vintages are not supplied.",
            "World Bank monthly data is supporting history only and never upsampled into weekly observations."],
        "source_access_failures": [
            {"url": "https://stooq.com/q/d/l/?s=cc.f&i=d", "status": 404},
            {"url": "https://api.tech.ec.europa.eu/agrifood/api/cereal/prices", "status": 500, "detail": "Upstream address endpoint SUSPENDED; official XLSX fallback used."},
            {"url": "https://api.tech.ec.europa.eu/agrifood/api/oilseeds/prices", "status": 500, "detail": "Upstream address endpoint SUSPENDED."},
            {"url": "https://ahdb.org.uk/UKDeliveredExport/API", "detail": "Export timed out; latest workbook is a current snapshot only. Not added to historical panel."},
            {"url": "https://fred.stlouisfed.org/legal/terms/", "detail": "Current terms prohibit ML development/training uses. No FRED data downloaded; original ECB source used."}]}
    write_json(root / "data/reports/commodity-audit.json", report)
    write_json(root / "data/reports/commodity-source-notes.json", {
        "generated_at": utc_now(), "primary_sources": [ICCO_PAGE, ICCO_CURRENT_PAGE, EU_CEREALS_PAGE, EU_OILSEEDS_PAGE, ECB_PAGE, WB_PAGE],
        "raw_directory": "data/raw/commodities", "outputs": ["commodity_observations.parquet", "commodity_daily.parquet", "commodity_weekly.parquet", "commodity_monthly_support.parquet"],
        "method_and_limitations": report})
    conn.close()
    return report
