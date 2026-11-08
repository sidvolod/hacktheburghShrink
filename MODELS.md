# Trained category models

Run `./run_models.sh --as-of 2026-11-08 --offline` from this folder to reproduce the frozen experiment. Run `./run.sh` afterward to export it to the local website. Models run on CPU with a four-thread limit. Five hours or cloud access is not needed for this dataset.

## Separate experiment folders

```text
data/experiments/category_forecast/
  dataset.parquet
  metadata.json
  provenance.json
  summary.json
  report.md
  chocolate/                         # same layout for crisps/
    comparison.png
    ridge/
      history_only/
      history_plus_weekly_commodities/
    hist_gradient_boosting/
      history_only/
      history_plus_weekly_commodities/
    no_change/baseline/
    seasonal/baseline/
    recent/baseline/
    trailing_mean/baseline/
```

Each experiment folder has `config.json`, `metrics.json`, `validation_predictions.csv` and `test_predictions.csv`. Learned models additionally have `model.joblib`, containing the fitted preprocessing/model pipeline and exact feature order. Configuration records all tested hyperparameters, selected settings, runtime versions and provenance. There are 16 model/feature-group experiments across the two categories, including eight fitted learned-model artifacts.

## Real data and forecast meaning

- ONS chocolate L79X and crisps L79R: 141 monthly index observations each, January 2015–September 2026. Annual and quarterly rows are excluded.
- Dataset: 129 historical monthly targets plus one live prediction row per category. The target is `100 * (index[target month] / index[previous month] - 1)`.
- Historical issues are at midnight Europe/London on the eighth of the preceding month. The live issue is 8 November 2026 and predicts December 2026 inflation versus November.
- CPI features use observations through issue month minus two. The current forecast therefore uses September CPI. Historical target labels become available on the first of target month plus two months, conservatively after normal following-month ONS publication.
- Weekly cocoa, FX, maize and wheat features come from real existing weekly observations, with seven-day cocoa/FX and fourteen-day EU buffers. No monthly interpolation. Grain benchmarks are exploratory proxies, not measured ingredient weights for every crisp.
- These are category price-index forecasts. They do not predict an individual snack's shelf price, grams, recipe changes or probability of shrinkflation.

Raw CSVs, URL/retrieval metadata and content hashes are frozen under `data/raw/ons-category/`. The dataset metadata retains the weekly source hash and assumptions. Sources are ONS, ICCO, ECB and European Commission crop statistics. ONS CPI publication guidance: https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/howwepublishourconsumerpricesoutputs .

## Evaluation

Ridge uses fold-local median imputation and standardisation. Boosted trees use shallow scikit-learn histogram gradient boosting with random internal early stopping disabled. Fixed small hyperparameter grids are evaluated on expanding pre-test folds. Both price-history and weekly-commodity feature groups are tested against four baselines.

Settings and the overall winner use 34 validation months, January 2021–October 2023, whose labels are available by the first test issue on 8 December 2023. November/December 2023 outcomes cannot influence selection. The final test covers 33 monthly targets, January 2024–September 2026. At every issue, the training set includes only labels available by that issue; earlier test observations may enter later expanding fits once published. Preprocessing is refitted inside each training fold.

| Category | Validation winner | Test MAE | Test RMSE | No-change MAE |
| --- | --- | ---: | ---: | ---: |
| Chocolate | Boosted trees + weekly commodities | 1.5747 pp | 1.9596 pp | 1.9770 pp |
| Crisps | Ridge, history only | 1.3520 pp | 1.7348 pp | 1.2648 pp |

Chocolate improves MAE by 20.35% versus no change in this test. However, its seasonal baseline scores 1.6158 pp, and history-only boosted trees score 1.5948 pp. Adding commodities improves the same boosted-tree family by only 0.0200 pp, about 1.26%. Do not attribute the entire gain over no change to commodities. Crisps is 6.90% worse than no change on the test; its validation-selected model remains selected rather than switching retrospectively to the best test result.

The live point predictions are +2.3167% chocolate and +0.4791% crisps for December 2026. No probability or prediction interval is emitted. Typical test errors are material relative to these predicted changes. Backtests use current archives with explicit release-buffer assumptions, not recovered original historical vintages; corrections and proxy limitations remain.

## Verification and reproduction

```sh
./run_models.sh --as-of 2026-11-08 --offline
./run.sh --check --browser-check --port 4174
```

`requirements-models.lock` pins the tested local modelling environment. `requirements.lock` remains the lighter preparation environment; `pyproject.toml` exposes an optional `models` dependency group. Existing product-level feasibility reports remain separate and continue to explain why the short branded panel cannot support the original SKU forecast.
