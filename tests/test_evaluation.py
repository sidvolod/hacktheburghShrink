"""Synthetic calculation/gate fixtures only; these are not observed model results."""
import math
import unittest

from shrinkflation.evaluation import feasibility_reasons, zero_change_metrics


class EvaluationTests(unittest.TestCase):
    def test_many_products_do_not_supply_chronological_periods(self):
        coverage = {"eligible_target_months":["2024-03-01"], "eligible_mass_pairs":40000,
            "strict_commodity_feature_rows_at_eligible_cutoffs":0,"price_linked_verified_response_events":0}
        reasons=feasibility_reasons(coverage)
        self.assertEqual([item["code"] for item in reasons],
            ["insufficient_chronological_periods","commodity_publication_timing_unknown","response_history_not_linked"])

    def test_real_error_units_keep_falls_flat_and_rises(self):
        reference=zero_change_metrics([-.1,0,.2])
        self.assertAlmostEqual(reference["mae_percentage_points"],10)
        self.assertAlmostEqual(reference["rmse_percentage_points"],100*math.sqrt(.05/3))
        self.assertEqual(reference["median_absolute_error_percentage_points"],10)
        self.assertEqual((reference["falls"],reference["flat"],reference["rises"]),(1,1,1))
        self.assertAlmostEqual(reference["mean_signed_error_percentage_points"],-10/3)

    def test_empty_is_unknown_and_nonfinite_outcomes_are_rejected(self):
        self.assertIsNone(zero_change_metrics([]))
        for value in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                zero_change_metrics([value])

    def test_commodity_and_response_gates_are_not_fixed_by_more_price_months(self):
        coverage = {"eligible_target_months":["2024-03-01","2024-04-01","2024-05-01","2024-06-01"],
            "eligible_mass_pairs":100, "strict_commodity_feature_rows_at_eligible_cutoffs":0,
            "price_linked_verified_response_events":0}
        self.assertEqual([item["code"] for item in feasibility_reasons(coverage)],
            ["commodity_publication_timing_unknown","response_history_not_linked"])


if __name__ == '__main__':
    unittest.main()
