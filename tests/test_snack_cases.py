import copy
import unittest
from pathlib import Path

from shrinkflation.snack_cases import enrich_case,load_cases,load_document,load_recipe_findings,unit_price

ROOT=Path(__file__).resolve().parents[1]


class SnackCaseTests(unittest.TestCase):
    def test_known_cases_and_calculations_have_no_invented_dates(self):
        cases={case["id"]:case for case in load_cases(ROOT)}
        self.assertGreaterEqual(len(cases),5)
        quality=cases["quality-street-uk-tub-2025"]
        self.assertEqual(quality["family_id"],"case-family:quality-street-uk-tub-2025")
        self.assertAlmostEqual(quality["old"]["price_per_100g_gbp"],1)
        self.assertAlmostEqual(quality["new"]["price_per_100g_gbp"],7/5.5)
        self.assertAlmostEqual(quality["unit_price_change_fraction"],3/11)
        for case in cases.values():
            self.assertIsNone(case["event_date"])
            self.assertFalse(case["eligible_monthly_training_label"])
            self.assertTrue(case["sources"])
            self.assertIsNone(case["old"]["transaction_date"])
            self.assertIsNone(case["new"]["transaction_date"])

    def test_article_percentages_are_recomputed(self):
        cases={case["id"]:case for case in load_cases(ROOT)}
        for key in ("cadbury-oreo-bites-uk-2025","m-and-ms-chocolate-uk-2025"):
            self.assertAlmostEqual(cases[key]["unit_price_change_fraction"],.1)
        self.assertAlmostEqual(cases["mcvities-digestives-uk-500-to-400"]["unit_price_change_fraction"],.25/.22-1)
        self.assertAlmostEqual(cases["galaxy-minstrels-uk-pouch-2025"]["unit_price_change_fraction"],125/118-1)
        self.assertAlmostEqual(cases["revels-uk-pouch-2025"]["unit_price_change_fraction"],(3.3/185)/(2.75/205)-1)

    def test_missing_price_and_rrp_remain_distinct(self):
        cases={case["id"]:case for case in load_cases(ROOT)}
        maltesers=cases["maltesers-uk-pouch-2016"]
        self.assertIsNone(maltesers["old"]["price_per_100g_gbp"])
        self.assertIsNone(maltesers["unit_price_change_fraction"])
        self.assertFalse(maltesers["price_comparison_available"])
        later=cases["maltesers-uk-pouch-2017"]
        self.assertEqual(later["old"]["price_gbp"],1.5)
        self.assertEqual(later["new"]["price_gbp"],1.5)
        self.assertAlmostEqual(later["unit_price_change_fraction"],103/93-1)
        self.assertEqual(later["price_comparison_basis"],"reported_price_retailer_unspecified")
        self.assertIsNone(later["retailer"])
        self.assertEqual(cases["snickers-uk-single-2013"]["price_comparison_basis"],"recommended_retail_price")
        self.assertIsNone(cases["snickers-uk-single-2013"]["retailer"])

    def test_different_price_basis_is_not_a_comparable_increase(self):
        document=load_document(ROOT)
        case=copy.deepcopy(document["cases"][0])
        case["new"]["price_basis"]="recommended_retail_price"
        result=enrich_case(case,document["sources"])
        self.assertIsNone(result["unit_price_change_fraction"])
        with self.assertRaises(ValueError):
            unit_price(1,0)

    def test_recipe_snapshots_remain_separate_from_size_event_dates(self):
        cases={case["id"]:case for case in load_cases(ROOT)}
        case=cases["mcvities-digestives-uk-500-to-400"]
        self.assertTrue(case["recipe_comparison_available"])
        recipe=case["recipe_history"]
        self.assertEqual(recipe["old"]["date"],"2008-11-11")
        self.assertEqual(recipe["new"]["date"],"2022-09-29")
        self.assertEqual(recipe["new"]["date_basis"],"document_last_updated_not_purchase_or_reformulation_date")
        self.assertIsNone(case["event_date"])
        self.assertIsNone(case["old"]["transaction_date"])
        self.assertFalse(case["eligible_monthly_training_label"])
        self.assertEqual(len(recipe["sources"]),2)
        self.assertTrue(all(not c["recipe_comparison_available"] for c in cases.values() if c["id"]!=case["id"]))

    def test_standalone_recipe_evidence_does_not_invent_mass_price_or_transition(self):
        finding=load_recipe_findings(ROOT)[0]
        self.assertFalse(finding["eligible_monthly_training_label"])
        self.assertNotIn("unit_price_change_fraction",finding)
        recipe=finding["recipe_history"]
        self.assertIsNone(recipe["old"]["mass_g"])
        self.assertIsNone(recipe["new"]["mass_g"])
        self.assertEqual(recipe["new"]["date_basis"],"access_date_only_not_publication_or_recipe_transition")
        source=next(s for s in recipe["sources"] if s["id"]=="mcvities-penguin-official-2026")
        self.assertIsNone(source["published"])
        self.assertEqual(source["raw_kind"],"access_note_not_article_capture")


if __name__ == "__main__":
    unittest.main()
