"""A separate registry for reported cases, reviewed membership and unresolved leads."""
from __future__ import annotations

import json
from pathlib import Path

from .common import connect, export_rows, write_json


def run(root: Path, fetch: bool = True) -> dict:
    document = json.loads((root / "research/reported-cases.json").read_text())
    plan = json.loads((root / "research/dataset-plan.json").read_text())
    changes, members, families, candidates = [], [], [], []
    for case in document["cases"]:
        old, new = case["old"], case["new"]
        source = document["sources"][case["source_id"]]
        family_id = "case-family:" + case["id"]
        families.append({"family_id": family_id, "name": case["name"], "market": "GB",
            "scope": "manually_reviewed_reported_case_not_catalogue_wide_matching"})
        old_unit = 100 * old["price_gbp"] / old["quantity_g"]
        new_unit = 100 * new["price_gbp"] / new["quantity_g"]
        changes.append({"change_id": case["id"], "family_id": family_id, "product_name": case["name"],
            "retailer": case["retailer"], "old_barcode": old["barcode"], "new_barcode": new["barcode"],
            "old_mass_g": old["quantity_g"], "new_mass_g": new["quantity_g"],
            "old_price_gbp": old["price_gbp"], "new_price_gbp": new["price_gbp"],
            "old_price_per_100g_gbp": old_unit, "new_price_per_100g_gbp": new_unit,
            "mass_change_fraction": new["quantity_g"] / old["quantity_g"] - 1,
            "unit_price_change_fraction": new_unit / old_unit - 1,
            "old_period_raw": old["period"], "new_period_raw": new["period"],
            "event_date": None, "old_transaction_date": None, "new_transaction_date": None,
            "source_published_date": source["published"], "source_url": source["url"],
            "evidence_status": case["status"], "evidence_json": json.dumps(case, ensure_ascii=False),
            "eligible_monthly_training_label": False,
            "label_exclusion_reason": "selected_positive_case_and_exact_event_and_transaction_dates_unavailable"})
        for role in ("old", "new"):
            barcode = case[role]["barcode"]
            if barcode:
                members.append({"family_id": family_id, "barcode": barcode, "role": role,
                    "review_status": "manually_supported_by_report_and_product_identity",
                    "source_url": source["url"], "valid_from": None, "valid_to": None,
                    "note": "Reported replacement; exact on-sale boundaries unknown; current OFF dates are not market dates"})
    for lead in plan.get("leads_not_verified_as_complete_pairs", []):
        if lead.get("old_barcode") and lead.get("new_barcode"):
            candidates.append({"old_barcode": lead["old_barcode"], "new_barcode": lead["new_barcode"],
                "name": lead["name"], "status": "needs_evidence_review", "score": None,
                "note": lead["assessment"], "evidence_json": json.dumps(lead, ensure_ascii=False)})
    conn = connect(root)
    processed = root / "data/processed"
    export_rows(conn, changes, {"change_id":"VARCHAR", "family_id":"VARCHAR", "product_name":"VARCHAR",
        "retailer":"VARCHAR", "old_barcode":"VARCHAR", "new_barcode":"VARCHAR", "old_mass_g":"DOUBLE", "new_mass_g":"DOUBLE",
        "old_price_gbp":"DOUBLE", "new_price_gbp":"DOUBLE", "old_price_per_100g_gbp":"DOUBLE", "new_price_per_100g_gbp":"DOUBLE",
        "mass_change_fraction":"DOUBLE", "unit_price_change_fraction":"DOUBLE", "old_period_raw":"VARCHAR", "new_period_raw":"VARCHAR",
        "event_date":"DATE", "old_transaction_date":"DATE", "new_transaction_date":"DATE", "source_published_date":"DATE",
        "source_url":"VARCHAR", "evidence_status":"VARCHAR", "evidence_json":"VARCHAR", "eligible_monthly_training_label":"BOOLEAN",
        "label_exclusion_reason":"VARCHAR"}, processed / "reported_changes.parquet")
    export_rows(conn, families, {"family_id":"VARCHAR", "name":"VARCHAR", "market":"VARCHAR", "scope":"VARCHAR"}, processed / "product_families.parquet")
    export_rows(conn, members, {"family_id":"VARCHAR", "barcode":"VARCHAR", "role":"VARCHAR", "review_status":"VARCHAR",
        "source_url":"VARCHAR", "valid_from":"DATE", "valid_to":"DATE", "note":"VARCHAR"}, processed / "family_members.parquet")
    export_rows(conn, candidates, {"old_barcode":"VARCHAR", "new_barcode":"VARCHAR", "name":"VARCHAR", "status":"VARCHAR",
        "score":"DOUBLE", "note":"VARCHAR", "evidence_json":"VARCHAR"}, processed / "candidate_family_links.parquet")
    conn.close()
    report = {"reported_cases": len(changes), "reviewed_barcode_members": len(members),
        "unverified_candidate_pairs": len(candidates), "exact_monthly_event_labels": 0,
        "limitations": ["Selected positive demonstrations; not representative training data.",
            "Unknown event and transaction dates remain null.", "Recipe-change leads remain unverified."]}
    write_json(root / "data/reports/evidence-audit.json", report)
    return report
