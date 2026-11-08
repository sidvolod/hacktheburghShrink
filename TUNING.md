# Backtesting and tuning

Reproduce the complete local experiment with:

```sh
./tune_models.sh --as-of 2026-11-08 --offline
./run.sh
```

The first command builds enhanced features from the frozen data, tests a bounded model catalog, and compares aggregation/selection policies using saved forecasts. All outputs stay under `data/experiments/category_tuning/` and `data/experiments/category_policy_tuning/`. Hash-addressed run folders preserve each manifest and its artifacts; root `summary.json` files point to the latest completed results. No cloud service or additional dataset is used.

## Interpretation

The January 2024–September 2026 evaluation period was already inspected before this work. These are **retrospective exploratory backtests**, not new untouched-test results. Original category models and their 79 artifact files remain unchanged under `data/experiments/category_forecast/`.

Targets remain monthly category CPI changes, with the same historical issue dates, release delays and source-archive limitations. They are not forecasts of a specific product's price per gram, pack size or recipe. Forecasts issued 8 November concern December 2026.

## First stage: model search

There are 59 fixed candidates per category: seasonal baselines, regularised Ridge, seasonal-residual Ridge, shorter training windows, robust/exact gradient boosting, histogram gradient boosting, Elastic Net, Huber regression and conservative blends. New features add month indicators, Easter timing for chocolate, same-calendar-month returns in prior years, seasonal means/medians, and lagged genuine weekly commodity inputs. The original labels, dates and numeric columns are preserved.

Every candidate produces expanding chronological forecasts from January 2020 onward. Each fit uses only labels available at that issue; imputation and scaling are fitted inside that fold. Candidate configurations, source hashes and search limits are frozen in `search_manifest.json` before scores are calculated. Cached prediction CSVs, fitted live models and live forecasts are saved in separate candidate folders.

For each outer month, the model selector ranks candidates on their common preceding 36 months of available prediction errors, requiring at least 12. The winner can change monthly. Its aggregate error describes the **selection strategy**, not the last model selected for the live forecast. The 59-model search yields 9,558 candidate forecasts across both categories.

## Second stage: stability and regime changes

Ten fixed policies reuse those saved forecasts without retraining: strongest model, mean/median of the top three or five, inverse-error weighted top three, a conservative single-model blend, faster 12/24-month candidate ranking, and no change.

Each policy constructs its historical forecast using only candidate errors published by that historical issue. A second selector chooses among policies using only their own preceding 36 months of published errors, again requiring 12 common months. Both selection layers are audited. Fixed-policy rankings are descriptive comparisons; the next live policy is not selected by its full-period outer score. Averaging weights are heuristics, not confidence probabilities.

## Reports and verification

- `data/experiments/category_tuning/summary.json`: model-search strategy, all candidates, outer predictions, live choice and original comparison.
- `data/experiments/category_policy_tuning/summary.json`: policy-selection strategy, policy comparisons, components/weights and dated live forecast.
- Each hash-addressed run contains its frozen manifest, saved prediction CSVs, metrics and plots.
- `data/reports/category-tuning-final.log`: complete runner output.
- `data/reports/tuning-python-tests.log`: chronology, future-information invariance, preprocessing, manifest and export tests.
- The website retains **Original evaluation** and **Tuned backtest** views and labels the exploratory status.

The initial exploratory run `b51142352a5e6ea9` is retained with its exact source snapshot. Its residual-model CSVs had a minor audit-boundary erratum: the earliest training month sometimes included an initial row later dropped for a missing seasonal baseline. Training counts, latest availability bounds and predictions were correct. The runner was corrected before the final reproducibility run; its results are saved in a distinct run folder.

## Completed comparison

All rows below use the same 33 target months per category, January 2024–September 2026. MAE is in percentage points; lower is better.

| Approach | Chocolate MAE | Crisps MAE |
| --- | ---: | ---: |
| Original frozen approach | 1.5747 | 1.3520 |
| Rolling selection among 59 configurations | 1.5640 | 1.4478 |
| Rolling selection among 10 aggregation policies | 1.6511 | 1.3383 |
| No-change baseline | 1.9770 | 1.2648 |

The model-search strategy reduced chocolate error by only 0.68% and increased crisps error by 7.09%. The policy strategy increased chocolate error by 4.85% and reduced crisps error by 1.02%; crisps still failed to beat no change. These small, inconsistent results do not establish improved future accuracy. The website therefore keeps the **original evaluation as the default**, with both exploratory comparisons available under Tuned backtest. Selecting a different winning approach per category after seeing these scores would itself be further retrospective selection.

Final model run: `f97dd7d15914cda7`. Final policy run: `1488998508ebcb68`. Exact used Python sources are archived in each run's `source/` folder and match the frozen manifest hashes. The original 79-file experiment is unchanged.

The December 2026 exploratory live forecasts differ substantially from the original: model search gives chocolate −0.5850% and crisps 0%; policy selection gives chocolate −0.2404% and crisps 0%. These are category-index forecasts, not shelf-price observations. This disagreement is another reason to treat the current outlook as experimental. No calibrated interval is claimed.

An independent reconstruction verified all 9,558 candidate forecasts and training cutoffs, 1,344 policy forecasts, 3,082 component values/weights, all 66 outer policy choices and both live policy forecasts. The published-data chronology passed, but current-archive vintage limitations still apply. Independent reconstruction does not make this a fresh holdout.

Final software verification passed 57 Python tests, seven TypeScript checks and 27 desktop/phone Chromium checks, with one expected phone-only skip on desktop. Production build, both tuning views, report downloads and original-default switching passed; screenshots were visually inspected. Full log: `data/reports/tuning-browser-check.log`.
