"""Curated snack reveals with explicit price basis, date precision and evidence.

The selected positive cases demonstrate documented changes; they are never
silently promoted to dated monthly training labels or automatic barcode links.
"""
from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from pathlib import Path

import requests

from .common import connect, download_file, export_rows, sha256_file, write_json


def unit_price(price_gbp: float | None, mass_g: float) -> float | None:
    if mass_g <= 0 or not math.isfinite(mass_g):
        raise ValueError("Declared mass must be finite and positive")
    if price_gbp is None:
        return None
    if price_gbp <= 0 or not math.isfinite(price_gbp):
        raise ValueError("Known price must be finite and positive")
    return float(Decimal(100) * Decimal(str(price_gbp)) / Decimal(str(mass_g)))


def enrich_case(raw: dict, sources: dict) -> dict:
    case = copy.deepcopy(raw)
    if case.get("event_date") is not None:
        raise ValueError("These selected cases do not establish exact event dates")
    for side in ("old", "new"):
        value = case[side]
        value["price_per_100g_gbp"] = unit_price(value["price_gbp"], value["mass_g"])
        barcode = value.get("barcode")
        if barcode is not None and not isinstance(barcode, str):
            raise ValueError("Barcodes must remain strings")
    old, new = case["old"], case["new"]
    case["mass_change_fraction"] = float(Decimal(str(new["mass_g"])) / Decimal(str(old["mass_g"])) - 1)
    compatible = old["price_basis"] == new["price_basis"] and old["price_basis"] != "not_reported"
    if compatible and old["price_gbp"] is not None and new["price_gbp"] is not None:
        ratio = (Decimal(str(new["price_gbp"])) / Decimal(str(new["mass_g"]))) / (Decimal(str(old["price_gbp"])) / Decimal(str(old["mass_g"])))
        case["unit_price_change_fraction"] = float(ratio - 1)
    else:
        case["unit_price_change_fraction"] = None
    case["sources"] = [copy.deepcopy(sources[key]) for key in case["source_ids"]]
    case["family_id"] = case.get("family_id") or "snack-family:" + case["id"]
    case["price_comparison_available"] = case["unit_price_change_fraction"] is not None
    case["price_comparison_basis"] = old["price_basis"] if compatible else "not_comparable"
    case["eligible_monthly_training_label"] = False
    case["label_exclusion_reason"] = "selected_positive_case_without_exact_event_and_transaction_dates"
    recipe = case.get("recipe_history")
    case["recipe_comparison_available"] = bool(recipe and recipe.get("status") == "documented_label_comparison")
    if case["recipe_comparison_available"]:
        recipe["sources"] = [copy.deepcopy(sources[key]) for key in recipe["source_ids"]]
    return case


def load_document(root: Path) -> dict:
    return json.loads((root / "data/curated/snack-cases.json").read_text())


def load_cases(root: Path) -> list[dict]:
    document = load_document(root)
    cases = [enrich_case(case, document["sources"]) for case in document["cases"]]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate curated case IDs")
    return cases


def load_recipe_findings(root: Path) -> list[dict]:
    document = load_document(root)
    findings = copy.deepcopy(document.get("recipe_findings", []))
    for finding in findings:
        recipe = finding["recipe_history"]
        recipe["sources"] = [copy.deepcopy(document["sources"][key]) for key in recipe["source_ids"]]
        finding["eligible_monthly_training_label"] = False
    return findings


def run(root: Path, fetch: bool = True) -> dict:
    document = load_document(root)
    access_failures = []
    if fetch:
        for source in document["sources"].values():
            if source["raw_kind"] == "access_note_not_article_capture":
                continue
            url = source["url"].split("#", 1)[0]
            try:
                download_file(url, root / source["raw_path"], source_id=source["id"], root=root)
            except (requests.RequestException, OSError) as error:
                access_failures.append({"source_id":source["id"],"url":url,"error":str(error)})
    cases = load_cases(root)
    recipe_findings = load_recipe_findings(root)
    output = root / "data/processed"
    write_json(output / "snack_cases.json", {"schema_version":1, "cases":cases,
        "recipe_findings":recipe_findings, "recipe_leads":document["recipe_leads"], "reuse_note":document["reuse_note"]})
    rows, memberships = [], []
    for case in cases:
        old,new=case["old"],case["new"]
        rows.append({"case_id":case["id"],"family_id":case["family_id"],"name":case["name"],
            "retailer":case["retailer"],"old_barcode":old["barcode"],"new_barcode":new["barcode"],
            "old_mass_g":old["mass_g"],"new_mass_g":new["mass_g"],
            "old_price_gbp":old["price_gbp"],"new_price_gbp":new["price_gbp"],
            "old_price_per_100g_gbp":old["price_per_100g_gbp"],"new_price_per_100g_gbp":new["price_per_100g_gbp"],
            "mass_change_fraction":case["mass_change_fraction"],"unit_price_change_fraction":case["unit_price_change_fraction"],
            "price_basis":case["price_comparison_basis"],"event_date":None,
            "source_published_date":case["sources"][0]["published"],"evidence_status":case["evidence_status"],
            "eligible_monthly_training_label":False,"case_json":json.dumps(case,ensure_ascii=False)})
        if case["family_link"]["status"] == "manually_supported_replacement_pair":
            for side in ("old","new"):
                memberships.append({"family_id":case["family_id"],"barcode":case[side]["barcode"],"role":side,
                    "valid_from":None,"valid_to":None,"review_status":case["family_link"]["status"],
                    "evidence_json":json.dumps(case["family_link"],ensure_ascii=False)})
    connection=connect(root)
    try:
        export_rows(connection,rows,{"case_id":"VARCHAR","family_id":"VARCHAR","name":"VARCHAR","retailer":"VARCHAR",
            "old_barcode":"VARCHAR","new_barcode":"VARCHAR","old_mass_g":"DOUBLE","new_mass_g":"DOUBLE",
            "old_price_gbp":"DOUBLE","new_price_gbp":"DOUBLE","old_price_per_100g_gbp":"DOUBLE","new_price_per_100g_gbp":"DOUBLE",
            "mass_change_fraction":"DOUBLE","unit_price_change_fraction":"DOUBLE","price_basis":"VARCHAR","event_date":"DATE",
            "source_published_date":"DATE","evidence_status":"VARCHAR","eligible_monthly_training_label":"BOOLEAN","case_json":"VARCHAR"},output / "snack_changes.parquet")
        export_rows(connection,memberships,{"family_id":"VARCHAR","barcode":"VARCHAR","role":"VARCHAR","valid_from":"DATE","valid_to":"DATE",
            "review_status":"VARCHAR","evidence_json":"VARCHAR"},output / "snack_family_members.parquet")
    finally:
        connection.close()
    report={"cases":len(cases),"families":len({case["brand"] for case in cases}),
        "curated_input_path":"data/curated/snack-cases.json",
        "curated_input_sha256":sha256_file(root / "data/curated/snack-cases.json"),
        "price_comparable_cases":sum(case["price_comparison_available"] for case in cases),
        "recipe_comparable_cases":sum(case["recipe_comparison_available"] for case in cases),
        "standalone_recipe_findings":len(recipe_findings),
        "rrp_only_price_cases":sum(case["price_comparison_basis"]=="recommended_retail_price" for case in cases),
        "reviewed_barcode_members":len(memberships),"eligible_monthly_training_labels":0,
        "source_files_present":sum((root / source["raw_path"]).exists() for source in document["sources"].values()),
        "source_captures_present":sum(source["raw_kind"] != "access_note_not_article_capture" and (root / source["raw_path"]).exists()
            for source in document["sources"].values()),
        "access_notes_present":sum(source["raw_kind"] == "access_note_not_article_capture" and (root / source["raw_path"]).exists()
            for source in document["sources"].values()),
        "sources_missing_captures":[source["id"] for source in document["sources"].values() if not (root / source["raw_path"]).exists()],
        "source_access_failures":access_failures,
        "limitations":["Selected positive demonstrations, not representative training data.",
            "Article publication dates are not exact market-transition or transaction dates.",
            "RRP comparisons are labelled separately from reported shelf-price comparisons.",
            "No price-per-100g is invented when price evidence is missing.",
            "Recipe comparisons use dated label snapshots, not proven exact reformulation dates or cost changes."]}
    write_json(root / "data/reports/snack-cases-audit.json",report)
    return report
