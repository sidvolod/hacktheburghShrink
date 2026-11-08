"""Small real-data exports for the local demo; full research tables remain separate."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .common import connect, utc_now, write_json

RETAIL_SOURCE = "https://www.kaggle.com/datasets/declanmcalinden/time-series-uk-supermarket-data"
HISTORY_SPECS = (
    ("Doritos", "doritos cool original.*180g", "Sainsbury's"),
    ("Snickers", "snickers milk chocolate bars 4 x 41.7g", "Tesco"),
    ("Snickers", "^snickers caramel nougat peanuts & milk chocolate snack bar 48g$", "Sainsbury's"),
    ("Oreo Bites", "cadbury oreo bites chocolate bag 110g", "Tesco"),
    ("M&M's", "m&m.*chocolate more to share.*220g", "Sainsbury's"),
    ("Revels", "^revels milk chocolate sharing pouch bag 205g$", "Tesco"),
    ("Galaxy Minstrels", "^galaxy minstrels milk chocolate buttons pouch bag 125g$", "Tesco"),
    ("Maltesers", "maltesers milk chocolate.*sharing.*175g", "Sainsbury's"),
    ("Pringles", "pringles original sharing crisps 185g", "Tesco"),
    ("Milky Way", "milky way chocolate bars 6x21.5g", "Tesco"),
    ("McVitie's", "mcvitie.*digestives the original biscuits 360g", "Sainsbury's"),
)


def initial_cases(root: Path) -> list[dict]:
    """Bootstrap the first working path from existing source-supported records."""
    document = json.loads((root / "research/reported-cases.json").read_text())
    cases = []
    for case in document["cases"]:
        source = document["sources"][case["source_id"]]
        versions = {}
        for role in ("old","new"):
            version = case[role]
            versions[role] = {"mass_g":version["quantity_g"],"price_gbp":version["price_gbp"],
                "price_per_100g_gbp":100*version["price_gbp"]/version["quantity_g"],
                "price_basis":"reported_base_non_promoted" if source.get("price_basis") else "reported_shelf_price_same_retailer","barcode":version["barcode"],
                "period":version["period"],"transaction_date":None}
        cases.append({"id":case["id"],"name":case["name"],"brand":case["name"].split(" ")[0],
            "category":"Chocolate","market":"GB","retailer":case["retailer"],**versions,
            "mass_change_fraction":versions["new"]["mass_g"]/versions["old"]["mass_g"]-1,
            "unit_price_change_fraction":versions["new"]["price_per_100g_gbp"]/versions["old"]["price_per_100g_gbp"]-1,
            "evidence_status":case["status"],"event_date":None,"event_date_precision":"Exact transition/transaction dates unknown",
            "sources":[{"id":case["source_id"],"url":source["url"],"title":"Which? consumer investigation","published":source["published"],"role":"reported_change"}],
            "limitations":["Selected documented change, not a forecasting training label.","Source publication is not the exact transition date."],
            "photos":[],"family_link":{"status":"reviewed_reported_pair" if versions["old"]["barcode"] else "barcodes_unverified",
                "old_barcode":versions["old"]["barcode"],"new_barcode":versions["new"]["barcode"],"note":"See source evidence; no exact on-sale boundaries."}})
    return cases


def export_histories(conn) -> list[dict]:
    histories = []
    for label,pattern,retailer in HISTORY_SPECS:
        match = conn.execute("""SELECT source_product_id,product_name_raw,count(DISTINCT observation_date) AS days
            FROM app_prices WHERE retailer=? AND regexp_matches(lower(product_name_raw),?)
              AND unit_price_eligible AND total_mass_g>0 AND NOT variable_weight_name
            GROUP BY ALL ORDER BY days DESC,product_name_raw LIMIT 1""",[retailer,pattern]).fetchone()
        if not match:
            continue
        product_id,name,_ = match
        rows = conn.execute("""SELECT observation_date::VARCHAR,median(price_gbp)::DOUBLE,
            median(100*price_gbp/total_mass_g),median(total_mass_g)
            FROM app_prices WHERE source_product_id=? AND unit_price_eligible AND total_mass_g>0
            GROUP BY observation_date ORDER BY observation_date""",[product_id]).fetchall()
        histories.append({"id":product_id,"name":name,"brand":label,"retailer":retailer,"dimension":"mass_g",
            "price_basis":"lowest_available_including_loyalty","source_url":RETAIL_SOURCE,
            "identity_scope":"retailer_exact_name_provisional; separate from reported historical replacement chain",
            "quantity_basis":"explicit_retailer_name_at_capture",
            "points":[{"date":r[0],"price_gbp":r[1],"unit_price_gbp":r[2],"mass_g":r[3]} for r in rows]})
    return histories


def export_comparisons(conn) -> list[dict]:
    groups = []
    for group,pattern in (("Chocolate","snickers|mars chocolate|twix|kitkat|kit kat|cadbury dairy milk|maltesers|m&m.*chocolate"),
                          ("Crisps","doritos|pringles|walkers.*(ready salted|cheese|prawn|salt)")):
        # Brand names can also identify drinks, dips, nuts or unrelated toffees.
        # Require an explicit source-name snack format for this small demo cohort.
        format_pattern = ('(^|[^a-z])(bars?|fingers|pouch|buttons)([^a-z]|$)' if group == 'Chocolate'
                          else '(^|[^a-z])(crisps?|chips)([^a-z]|$)')
        for retailer in ("Tesco","Sainsbury's"):
            rows = conn.execute("""SELECT source_product_id,product_name_raw,total_mass_g,price_gbp::DOUBLE,
                100*price_gbp/total_mass_g AS price_per_100g,observation_date::VARCHAR
                FROM app_prices WHERE retailer=? AND observation_date='2024-04-13'
                  AND regexp_matches(lower(product_name_raw),?) AND unit_price_eligible
                  AND regexp_matches(lower(product_name_raw),?)
                  AND total_mass_g>0 AND NOT variable_weight_name
                  AND NOT regexp_matches(lower(product_name_raw),'ice cream|easter|egg|protein|spread|drink|cake|dessert|cereal|trifle|pots of joy|yogurt|yoghurt')
                  AND NOT regexp_matches(lower(product_name_raw),'(^|[^a-z])dips?([^a-z]|$)')
                QUALIFY row_number() OVER(PARTITION BY source_product_id ORDER BY observation_id)=1
                ORDER BY price_per_100g,product_name_raw LIMIT 14""",[retailer,pattern,format_pattern]).fetchall()
            if not rows:
                continue
            groups.append({"id":f"{group.lower()}-{retailer.lower()}","group":group,"label":group,
                "date":"2024-04-13","retailer":retailer,"source_url":RETAIL_SOURCE,
                "note":"Historical same-day observations, not today's offers. Loyalty discounts may apply; exact conditions are unavailable.",
                "items":[{"id":r[0],"name":r[1],"mass_g":r[2],"price_gbp":r[3],
                    "price_per_100g_gbp":r[4],"price_basis":"lowest_available_including_loyalty",
                    "quantity_basis":"explicit_retailer_name_at_capture"} for r in rows]})
    return groups


def portable_public_metadata(value, root: Path):
    """Keep published snapshot paths relative without changing frozen artifacts."""
    prefix = str(root.resolve())
    if isinstance(value, dict):
        return {key: portable_public_metadata(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_public_metadata(item, root) for item in value]
    if isinstance(value, str):
        if value == prefix:
            return "."
        if value.startswith(prefix + "/"):
            return value[len(prefix) + 1:]
    return value


def run(root: Path, fetch: bool = False) -> dict:
    public = root / "data/app-public"
    (public / "data").mkdir(parents=True,exist_ok=True)
    curated = root / "data/curated/snack-cases.json"
    if curated.exists():
        from .snack_cases import load_cases
        cases = copy.deepcopy(load_cases(root))
    else:
        cases = initial_cases(root)
    for case in cases:
        for photo in case.get("photos",[]):
            path = (root / photo["local_path"]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f"Missing local evidence photo: {path}")
            destination = public / "images" / path.name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,destination)
            photo["local_path"] = "/images/" + path.name
    evaluation_path = root / "data/reports/evaluation.json"
    if not evaluation_path.exists():
        from .evaluation import run as evaluate
        evaluate(root)
    evaluation = json.loads(evaluation_path.read_text())
    retail = json.loads((root / "data/reports/retail-audit.json").read_text())
    catalogue = json.loads((root / "data/reports/catalogue-audit.json").read_text())
    commodities = json.loads((root / "data/reports/commodity-audit.json").read_text())
    monthly = json.loads((root / "data/reports/monthly-audit.json").read_text())
    conn = connect(root)
    try:
        path = str(root / "data/processed/retail_prices.parquet").replace("'","''")
        conn.execute(f"CREATE TEMP VIEW app_prices AS SELECT * FROM read_parquet('{path}')")
        data = {"schema_version":1,"generated_at":utc_now(),"cases":cases,
            "histories":export_histories(conn),"comparisons":export_comparisons(conn),"evaluation":evaluation,
            "coverage":{"retail_observations":retail["prepared_price_observations"],"catalogue_records":catalogue["rows"],
                "weekly_commodity_rows":commodities["weekly_rows"],"monthly_pairs":monthly["eligible_sampled_monthly_pairs"],
                "eligible_target_months":monthly["distinct_eligible_target_months"],"retail_first_date":retail["first_observed_date"],
                "retail_last_date":retail["last_observed_date"],"case_count":len(cases),
                "known_limitations":["Current catalogue is not historical price proof.","Retail histories are provisional listings; reported transitions remain separate."]}}
        if curated.exists():
            from .snack_cases import load_recipe_findings
            data["recipe_findings"] = load_recipe_findings(root)
        category_report = root / "data/experiments/category_forecast/summary.json"
        if category_report.exists():
            category_forecast = json.loads(category_report.read_text())
            if not isinstance(category_forecast.get("categories"), list):
                raise ValueError("Category forecast report must contain a categories list")
            data["category_forecast"] = category_forecast
            shutil.copyfile(category_report, public / "data/category-forecast.json")
        tuning_report = root / "data/experiments/category_tuning/summary.json"
        if tuning_report.exists():
            category_tuning = json.loads(tuning_report.read_text())
            if not isinstance(category_tuning.get("categories"), list):
                raise ValueError("Category tuning report must contain a categories list")
            if category_tuning.get("categories"):
                for category in category_tuning["categories"]:
                    scores = {row["candidate_id"]:row["mae_pp"] for row in category.get("live_selection_ranking",[])}
                    for row in category.get("leaderboard",[]):
                        row["validation_mae_pp"] = scores.get(row.get("candidate_id"))
                data["category_tuning"] = category_tuning
                shutil.copyfile(tuning_report, public / "data/category-tuning.json")
        policy_report = root / "data/experiments/category_policy_tuning/summary.json"
        if policy_report.exists():
            category_policy_tuning = json.loads(policy_report.read_text())
            if not isinstance(category_policy_tuning.get("categories"), list):
                raise ValueError("Category policy report must contain a categories list")
            if category_policy_tuning.get("categories"):
                for category in category_policy_tuning["categories"]:
                    scores = {row["candidate_id"]:row["mae_pp"] for row in category.get("live_selection_ranking",[])}
                    for row in category.get("leaderboard",[]):
                        row["validation_mae_pp"] = scores.get(row.get("candidate_id"))
                data["category_policy_tuning"] = category_policy_tuning
                shutil.copyfile(policy_report, public / "data/category-policy-tuning.json")
        write_json(public / "data/demo.json",data)
        # Reports contain facts/metadata only; raw research pages are not served.
        for source in (evaluation_path,root / "data/reports/monthly-audit.json",root / "data/source-registry.json"):
            shutil.copyfile(source,public / "data" / source.name)
        for snapshot in (public / "data").glob("*.json"):
            write_json(snapshot, portable_public_metadata(json.loads(snapshot.read_text()), root))
        report = {"cases":len(cases),"histories":len(data["histories"]),"comparison_groups":len(data["comparisons"]),
            "recipe_findings":len(data.get("recipe_findings", [])),
            "comparison_items":sum(len(g["items"]) for g in data["comparisons"]),
            "forecast_status":"category_available" if data.get("category_forecast",{}).get("categories") else evaluation["status"],
            "tuning_status":"exploratory_available" if data.get("category_tuning",{}).get("categories") else "not_run",
            "product_forecast_status":evaluation["status"],
            "comparison_cohort_rule":"Familiar brands plus explicit bar/finger/pouch/button or crisp/chip format in the captured name; exclude desserts, cereals, drinks and dips. No ingredient/dietary equivalence inferred.",
            "output":"data/app-public/data/demo.json","bytes":(public / "data/demo.json").stat().st_size}
        write_json(root / "data/reports/app-export-audit.json",report)
        return report
    finally:
        conn.close()
