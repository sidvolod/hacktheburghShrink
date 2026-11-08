# Forecast feasibility and evaluation

**Forecast unavailable. No chronological model comparison was run.**

The target is next-calendar-month price-per-gram change; commodity inputs are weekly. The retail panel spans 2024-01-09 to 2024-04-13.

- 39,920 eligible mass-price pairs cover 1 distinct target month(s). The minimum comparison policy requires three training target months and one later test target month. Splitting products from the same month would not test future calendar periods.
- Real weekly commodity histories exist, but no strict publication-aware feature row is eligible at the retail forecast cutoffs. Observation dates and current archives do not establish original release or revision-vintage timing.
- Reported changes and one reviewed cross-barcode replacement are retained, but the retailer panel has no verified dated family-response sequence linked to these monthly price rows. Candidate matches are not training labels.

## Model comparison

| Model | Status | Held-out MAE | Held-out RMSE |
| --- | --- | --- | --- |
| No change | Not run | Unavailable | Unavailable |
| Linear regression | Not run | Unavailable | Unavailable |
| Gradient-boosted trees | Not run | Unavailable | Unavailable |

Commodity and previous-response feature improvements are **unknown**, not zero. No model was selected and no next-month forecast is emitted.

## Descriptive reference from real observations

For the 39,920 eligible **mass-price** pairs targeting March 2024, a zero-change prediction has MAE **8.0784 percentage points** and RMSE **20.1500 percentage points**. These are observed single-period errors, **not held-out backtest results, forecast accuracy, or evidence of future skill**. Volume outcomes are separate. Identities are provisional, prices may include loyalty discounts, and large observed changes remain.

## Data needed

- **More complete retail months.** For even one minimal chronological comparison, collect at least three additional distinct eligible target months after/before the existing March 2024 period, with complete adjacent-month sampling and labels available before each test cutoff. More periods are needed to assess commodity lags and performance stability.
- **Reviewed dated family histories.** Connect retailer listings to reviewed old/new barcodes and document replacement timing, pack mass/count, prices, offer conditions and raw ingredient evidence. Distinguish concurrent variants.
- **Commodity release and revision timing.** Retain daily/weekly release timestamps or defensible historical availability policies and original vintages. Current archive observation dates alone are insufficient for historical cutoffs.
- **Weekly sugar, edible oils and dairy.** Acquire genuine weekly/daily feeds for the missing relevant inputs; do not interpolate monthly World Bank values or substitute oilseeds for crude edible oils.

The one reviewed barcode replacement and unverified candidates are separate evidence assets. A same-barcode repeat count is not a measurement of all possible reconstructed-family coverage.

Reproduce with `PYTHONPATH=src .venv/bin/python -c "from pathlib import Path; from shrinkflation.evaluation import run; run(Path.cwd())"`. Exact metrics, scope, coverage and source-file lineage are in `data/reports/evaluation.json`.
