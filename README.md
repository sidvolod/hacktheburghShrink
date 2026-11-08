# shrincflationTrack

A local UK grocery detective: documented shrinkflation, the real cost of 100 grams, dated retail prices and trained category forecasts. **Monthly retail outcomes are the target; weekly commodity movements are inputs.** Product histories and category price-index predictions have distinct scopes.

## Launch

Clone the repository, then launch:

```sh
git clone https://github.com/sidvolod/hacktheburghShrink.git
cd hacktheburghShrink
./run.sh
```

Open **http://127.0.0.1:4173** and leave the terminal running. Stop with Ctrl+C. For a busy port, use `./run.sh --port 4174`.

The command validates the committed real-data demo snapshot, checks TypeScript, builds the app and serves only its public bundle on loopback. Viewing the demo needs no research-data download or model training. Missing demo files produce recovery instructions rather than silently starting a large download. Initial setup can install local Python/npm dependencies and a checksum-verified Node runtime. Downloads, runtime/cache files and generated data remain under `data/`; Python packages stay in `.venv/`, and UI dependencies in `web/node_modules/`. No global Node installation is required on macOS/Linux arm64/x64. Python 3.12+ is recommended for automatic runtime extraction; this workspace uses Python 3.14.

To verify and build without starting a server:

```sh
./run.sh --check --prepare-only
```

For desktop and phone browser verification, including screenshots:

```sh
./run.sh --check --browser-check --port 4174
```

This starts a temporary local server, runs the headless Chromium suite, and stops that server afterward. Checks use committed demo data and synthetic fixtures; the large retail tables are not required. Browser binaries, temporary profiles, screenshots and reports stay under `data/`. It downloads the pinned browser on first use. Results are saved in `data/reports/browser/results.json` and `data/reports/browser/html/`.

The latest model/build check passes **66 Python tests and 22 TypeScript tests**. The browser suite covers desktop and phone; see `VERIFICATION.md` and the current reports for the latest run.

## Working paths

- **The detective:** start with a snack-memory quiz and print a source-linked hidden inflation receipt. Revels’ former 205g amount costs £3.66 at the later rate, a 33.0% effective increase. Proportional ghost overlays show missing weight. Then search ten case files across nine familiar products, inspect before/after weights and reported prices, and open source/date/barcode evidence. Quality Street includes the reviewed 600g→550g barcode pair and attributed source photographs. Other barcode chains remain unresolved.
- **Price trail:** inspect eleven actual 2024 retailer listing histories and individual dated points. These provisional listings remain separate from reported replacement chains.
- **Price comparison:** compare 56 historical same-day observations across chocolate/crisps snapshots at Tesco and Sainsbury’s. Choose 50–1,000g and calculate an exact whole-pack basket at minimum checkout cost; equal-cost ties prefer less excess, then fewer packs. Prices are fixed recorded offers, with loyalty/stock conditions unknown and no inferred discount tiers.
- **Forecast lab:** trained chocolate and crisps category outlooks, validation/test model comparisons, saved historical predictions and an interactive reveal of actual outcomes. Forecasts concern the official UK category price index, not a particular brand's future weight or shelf price. A separate conservative output retains the model only where its reported test error beats no change; this rule was added after evaluation and has no independent validation.

Ten case files cover Quality Street, Doritos, McVitie’s Digestives, Snickers, Oreo Bites, M&M’s Chocolate, Galaxy Minstrels, Revels and two separate Maltesers changes. Nine have price comparisons: seven named-retailer shelf comparisons, one reported Maltesers price with retailer unspecified and one Snickers RRP comparison. The 2016 Maltesers prices remain unknown; the separate 2017 case records 103g→93g at a reported unchanged £1.50. Ingredient snapshots for Digestives now compare a government record of a 2008 purchase with a retailer specification updated in 2022, separately from the 2018/2019 size example. Exact transition dates remain unknown.

The separate recipe detective also compares Penguin Original’s 2008 government label transcription with its official manufacturer declaration checked in 2026: milk chocolate becomes milk chocolate flavour coating in the description. The date of the recipe transition remains unknown, and coating percentage is kept distinct from cocoa percentage. Both recipe comparisons retain original sources and qualified ingredient facts.

## Train and inspect models

For the broader exploratory tuning follow-up, use `./tune_models.sh --as-of 2026-11-08 --offline` and read `TUNING.md`. It preserves the original experiment below and writes separate model-search/policy folders. The website retains the original evaluation as default and can switch to either the expanded model search or averaging/selection experiment. Gains were small and inconsistent: chocolate MAE 1.5747 → 1.5640 pp for model selection, while crisps 1.3520 → 1.3383 pp for policy selection; the other category worsened in each experiment, and crisps still failed the no-change baseline. These are previously examined months, so the follow-up is exploratory.

```sh
./run_models.sh --as-of 2026-11-08 --offline
./run.sh
```

The first command reproduces the experiments from frozen local data; omit `--offline` only when acquiring missing source files. It installs the pinned optional modelling environment if needed. ONS snapshots are immutable and reused; this command does not silently refresh them. See `MODELS.md` for the dataset, release delays, interpretation and folder layout.

Separate model/feature-group folders under `data/experiments/category_forecast/` contain configuration, validation/test predictions, metrics and fitted models. Ridge regression and histogram gradient-boosted trees are compared with four baselines. Hyperparameters and the overall winner use only pre-test validation data; final-test outcomes do not choose the winner.

| Category | Validation-selected model | Later test months | Test MAE | No-change MAE |
| --- | --- | ---: | ---: | ---: |
| Chocolate | Boosted trees + weekly commodities | 33 | 1.5747 pp | 1.9770 pp |
| Crisps | Ridge, price history only | 33 | 1.3520 pp | 1.2648 pp |

Comparing each family’s feature group chosen on pre-test validation, chocolate trees score **1.5747 pp** versus Ridge **1.9092 pp**. Crisps Ridge scores **1.3520 pp** versus trees **1.4973 pp**, but no change is better at **1.2648 pp**. Subsequent RSI features did not produce a useful improvement or replace these original defaults. These are monthly category-index forecasts, separate from the individual-product evidence.

Chocolate's seasonal baseline scores 1.6158 pp, and history-only boosted trees score 1.5948 pp, so the incremental commodity improvement is small. Crisps did not beat no change on the later test. Both outcomes are shown. Models are experimental category-index forecasts, with no calibrated product-specific probabilities or prediction intervals.

The saved 8 November 2026 issue forecasts December 2026 category changes of **+2.3167% for chocolate** and **+0.4791% for crisps**. These are predictions, not observed changes. Inputs use ONS observations through September plus available weekly benchmarks; archive-vintage and availability-buffer assumptions remain explicit.

## Original product-level feasibility audit

The retail panel spans **9 January–13 April 2024**. Under the sampling rules, **39,920 mass-price pairs** share a single eligible target month, **March 2024**. There are no earlier eligible training target months followed by a later eligible test month. Original commodity release/vintage timing and price-linked family-response histories are also unresolved.

| Requested model | Chronological comparison | Held-out MAE / RMSE |
| --- | --- | --- |
| No-change baseline | Not run | Unavailable |
| Linear regression | Not run | Unavailable |
| Gradient-boosted trees | Not run | Unavailable |

Predicting zero change for the observed mass-price pairs gives a **descriptive MAE of 8.0784 percentage points** and **RMSE of 20.1500 pp**. These are single-period observed errors, not held-out model scores, forecast accuracy or evidence of future skill. Commodity and previous-response improvements for individual products are **unknown**. No product-level model was trained on this short panel. Category experiments above use separate, longer ONS histories.

The fallback remains valid for the original product-level target. The forecast page now shows the separately trained category experiments. Exact product-level feasibility and collection requirements remain in `data/reports/evaluation.json` and `data/reports/evaluation.md`.

## Demo snapshot and research data

The repository includes the public demo JSON and attributed source photographs, curated evidence, trained-model experiments, the small frozen ONS inputs and the weekly commodity table used by the category models. Dependencies, build output, caches and multi-gigabyte retail/catalogue downloads stay local. Original model/provenance artifacts are retained; absolute paths inside historical manifests describe their original run, not required checkout locations. Public UI metadata uses relative project paths. Third-party data/image attribution is retained in `DATA_GUIDE.md`, the evidence views and source manifests; the repository does not include full cached newspaper articles.

To explicitly refresh the demo from research inputs:

```sh
./run.sh --refresh-data
```

This can acquire several gigabytes if raw/processed research inputs are missing. It re-exports data and saved forecasts without retraining models. The normal launch reuses the committed snapshot.

## Reproduce the data

```sh
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare --offline
```

This rebuilds from saved raw inputs and curated evidence. Full raw research downloads are excluded from Git; acquire them first on a new checkout by omitting `--offline`. Downloads stay in `data/raw/`; source metadata and SHA-256 hashes are retained. See `DATA_GUIDE.md` for schemas, quantity rules, provenance and limitations. The original `PROJECT_HANDOFF.md` remains the historical concept/decisions record.

For just the demo export/evaluation:

```sh
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare --offline --stages snack-cases evaluation app-export
```

Useful outputs:

- `data/processed/shrinkflation.duckdb`: views over prepared Parquet files.
- `data/reports/preparation-summary.json`, `schema.json`, `raw-inventory.json`: coverage, columns and source checksums.
- `data/curated/snack-cases.json`: reviewed factual inputs with sources and precision notes.
- `data/app-public/data/demo.json`: the compact real-data UI contract.
- `data/app-dist/`: the local production bundle.

## Demo and remaining work

Use **DEMO.md** for a three-minute walkthrough. **PROGRESS.md** records implementation progress; **VERIFICATION.md** records checked runtime and browser behavior.

Before product-level model evaluation, obtain more complete overlapping retail months, review dated replacement links and offer conditions, establish historical commodity publication/revision policies, and fill genuine weekly sugar, edible-oil and relevant dairy gaps. Similarity candidates, selected changed products and current OFF quantities do not supply that evidence. The separate category models are already trained and evaluated as described above.
