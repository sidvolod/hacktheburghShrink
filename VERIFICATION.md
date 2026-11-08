# Verification record

8 November 2026, GitHub preparation. Default launch now validates and reuses the committed demo snapshot; `--refresh-data` explicitly invokes research preparation/export. Public metadata paths are portable copies; frozen artifacts are untouched. Checks pass **66 Python tests, 22 TypeScript tests and 39 Chromium desktop/phone browser checks**, with one expected skip. Log: `data/reports/github-publish-check.log`. A checkout of exactly the staged files, without the large retail/catalogue/raw downloads, also passed all 66 Python and 22 TypeScript tests plus production build. Installed runtime/dependency caches were reused for this check. Log: `data/reports/github-clean-checkout.log`. All 1,778 local frozen experiment files remain unchanged.

8 November 2026, receipt and decision follow-up. **59 Python tests, 22 TypeScript tests and 39 Chromium desktop/phone browser checks pass**, with one expected phone-only skip on desktop. TypeScript and production build pass. Logs: `data/reports/receipt-upgrade-build.log` and `receipt-upgrade-browser-check.log`. The temporary browser server stopped; the existing preview on port 4173 serves the updated app/data with HTTP 200.

Verified quiz keyboard controls, hidden/revealed receipt, exact Revels £3.66/+33.0% arithmetic, additive contribution reconciliation, source-modal focus, reset/case-switch behavior, RRP/missing-retailer qualifiers, ghost proportions and unchanged evidence views. The whole-pack planner matches an independent exhaustive oracle on 12 real baskets (four snapshots × 300/500/1,000g); helper tests add 80 independently enumerated problems and all 20 UI target weights for each real snapshot. Browser checks verify actual totals, quantities and extra grams against that independent oracle. The conservative output preserves raw forecasts and visibly declares its post-evaluation, unvalidated status. Existing charts/downloads and mobile containment pass. Receipt/planner/gate screenshots were visually reviewed on desktop/phone.

All 1,778 existing model-experiment files are checksum-identical. No training or test-score changes were made. The removed scatter page remains absent. Independent arithmetic/optimization audit: `data/reports/receipt-upgrade-independent-audit.json`.

8 November 2026, requested feature removal. Removed the exploratory price-change page, its navigation, export hook, implementation, dedicated tests and generated payload. The three original views remain: detective, historical price comparison and forecast lab. Final checks pass **59 Python tests, seven TypeScript tests and 35 Chromium desktop/phone browser checks**, with one expected phone-only skip on desktop. Production build passed. Current log: `data/reports/removed-jumps-browser-check.log`. All 1,778 existing model-experiment files are byte-for-byte unchanged. Existing preview endpoints return HTTP 200; the temporary verification server stopped. No replacement features were added.

8 November 2026, demo evidence follow-up. Added three source-supported size/price cases: Maltesers 2017, Revels 2025 and Galaxy Minstrels 2025. Ten size-change cases now have nine price comparisons; the 2016 Maltesers prices remain unknown. Added separate Snickers single-bar, Revels and Minstrels price trails: eleven listings and 976 dated observations in total. Digestives and standalone Penguin Original now have dated ingredient-declaration comparisons, separate from shrink events and model labels.

Final verification passed **59 Python tests, seven TypeScript checks and 35 Chromium desktop/phone browser checks**, with one expected phone-only skip on desktop. Production build passed. New before/after price values, source/date views, recipe summaries, expandable interpretation notes, downloads and keyboard/mobile behavior are verified. Desktop/phone recipe screenshots were visually inspected; the offscreen skip link no longer leaks into long element captures. The existing preview serves the new bundle and data with HTTP 200.

Current log: `data/reports/demo-gap-browser-check.log`; export/inventory log: `data/reports/demo-gap-export.log`; evidence coverage: `data/reports/snack-cases-audit.json`. The original 79-file model experiment remains byte-for-byte unchanged. Source-cache hashes match all four added captures/access notes. Independent reviews found no evidence or export/UI blockers. No new model training was performed.

8 November 2026, tuning follow-up. Final verification passed **57 Python tests, seven TypeScript checks and 27 Chromium desktop/phone browser checks**, with one expected phone-only skip on desktop. Production build passed. Both exploratory views, original-default switching, category metrics, saved historical forecasts, downloads and mobile containment are verified. Desktop and phone screenshots were visually reviewed. The existing loopback preview serves all three reports with HTTP 200.

Current log: `data/reports/tuning-browser-check.log`; browser results/screenshots are under `data/reports/browser/`. The command `./run.sh --check --browser-check --port 4174` completed with exit status 0; temporary verification server stopped. The existing user preview on port 4173 remains running.

Independent reconstruction checked 9,558 candidate forecasts/cutoffs, 1,344 policy forecasts, 3,082 component predictions/weights and 66 outer policy choices, plus live values and 238 frozen base-source checksums. Original 79-file experiment checksum remains `e0619b2fefb8f3c049bf3ab706dccfc1485ef9e4ea6a1a9381a2c8af5f0699b4`. Exact final sources are archived in run folders. See `TUNING.md`: the final scores are exploratory because these years had already been inspected. The original default is retained; gains are small and inconsistent, and crisps still fails the no-change baseline.

The earlier category-model and original MVP records below are historical and are superseded by this follow-up where applicable.

8 November 2026, Europe/London. The latest category-model update passes **41 Python checks, seven TypeScript checks and 27 Chromium desktop/phone browser checks**, with one expected phone-only skip on desktop. TypeScript and production build pass. Forecast cards, both categories, model metrics, the historical reveal, failed-baseline notice and actual report download are verified. Current desktop/phone forecast screenshots were visually inspected.

Current logs: `data/reports/category-build.log`, `category-training.log`, `category-browser-check.log`, and `data/reports/browser/results.json`. The browser run completed with exit status 0 in 18.6 seconds after launching Chromium outside the execution sandbox; the initial sandboxed attempt could not launch Chromium. Independent artifact review reconstructed all 1,072 validation/test CSV rows, checked each training availability cutoff and metric, and reproduced the two live predictions from reloaded fitted models. No final-test tuning was performed.

The December 2026 forecasts are **category CPI changes**, not SKU prices or shrink-event probabilities. Chocolate selects boosted trees with weekly inputs (MAE 1.5747 pp vs no-change 1.9770 and seasonal 1.6158); crisps selects history-only Ridge (1.3520 vs no-change 1.2648, a failed comparison). See `MODELS.md` for full interpretation. No probability or prediction interval is emitted.

The original product-level unavailable fallback remains valid. The detailed original MVP verification below is a historical record, superseded by the current category-model results where applicable.

## Reproduce the checks

```sh
./run.sh --check --browser-check --port 4174
```

This command exports real data, checks/builds TypeScript, starts a temporary local server, runs project-local headless Chromium, and stops the temporary server. It completed with exit status 0.

| Check | Result |
| --- | --- |
| Python data/evidence/model/calculation checks | 41 passed |
| TypeScript calculation/state/evidence checks | 7 passed |
| Desktop and phone browser checks | 27 passed |
| Expected skip | 1 phone-only check skipped on desktop |
| Unexpected browser failures / flaky tests | 0 / 0 |
| TypeScript and production build | Passed |
| Complete offline preparation, HTTP requests disabled | Passed |

Authoritative logs and reports:

- `data/reports/browser/release-browser-check.log`
- `data/reports/browser/results.json`
- `data/reports/browser/html/index.html`
- `data/reports/final-offline-pipeline.log`
- `data/reports/completion-audit.json`

## Browser scope and visual review

Playwright 1.65.0, full Chromium, desktop **1440 × 1000** and phone emulation **390 × 844**. This does not claim physical-iPhone, Safari or Firefox testing. Browser binaries/profiles, screenshots and reports stay under `data/`.

The actual production bundle was tested for:

1. All seven documented cases, exact weights and displayed prices/unit prices, including RRP, a falling pack price and unavailable prices.
2. Case search, empty results and slash-key focus.
3. Quality Street evidence: source URLs, both barcodes, unknown transaction/transition dates, three loaded photographs, attribution/licence and recipe-history status.
4. Escape, close-button and backdrop dismissal, restoring focus to the exact source-count or footer opener.
5. Switching from the last point of a longer price history to a shorter history, recorded-date slider selection and chart keyboard navigation.
6. All 56 comparison entries across four same-date retailer/category snapshots, equivalent-weight calculations, and simultaneous phone visibility of names, pack facts and price per 100g.
7. Trained category status, both categories, saved monthly predictions, validation/test scores, failed-baseline notice, historical reveal and downloading the actual category comparison JSON. The test retains the explicit fallback path when no trained category report exists.
8. Skip-to-content preserving the active route, phone text/control sizes and no page-level horizontal overflow.
9. No page/console errors or missing local resources during the successful suite.

Screenshots of the historical detective, source evidence, photographs, price trail, comparison and forecast screen were captured and visually inspected. Examples:

- `data/reports/browser/screenshots/detective-preview.png`
- `data/reports/browser/screenshots/desktop-historical-detective.png`
- `data/reports/browser/screenshots/phone-historical-detective.png`
- `data/reports/browser/screenshots/phone-quality-detail.png`
- `data/reports/browser/screenshots/phone-price-comparison.png`
- `data/reports/browser/screenshots/phone-forecast-reference.png`

## Fixes found through verification

- Clamped/reset chart selection to prevent a 92-point → 84-point history-switch crash.
- Kept incomparable prices and pending barcode candidates from becoming verified percentage/evidence claims.
- Corrected mobile grid and hidden-label containment instead of hiding document overflow.
- Put phone pack facts and unit prices on screen together; retained the full desktop table.
- Restored modal-opener focus for all dismissal methods.
- Restricted comparison formats to actual chocolate bars/fingers/pouches/buttons and crisps/chips, excluding drinks, dips, desserts, cereal and unrelated branded products.
- Formatted visible gram quantities to avoid floating-point artefacts, preserving raw numeric data and calculations.

## Data and forecast evidence

The complete frozen-input pipeline rebuilt **20 Parquet views**, inventoried **88 raw files**, and verified **39 original copied-file checksums** with HTTP requests disabled. The final UI evidence was semantically identical before/after this full rebuild; only generation timestamps changed. The built and exported demo JSON match exactly.

The UI contains seven selected snack cases, eight independent dated 2024 retailer listing histories and four same-day comparison groups with 56 entries. Quality Street has one reviewed old/new barcode replacement pair. Other candidates and exact dates remain unverified. Current OFF quantities are never treated as historical Open Prices pack proof.

The original mass-price evaluation cohort contains **39,920 pairs** sharing **one eligible target month, March 2024**. Original commodity availability/vintages and price-linked family-response histories remain unresolved. Therefore that original product-level report retains null model metrics and no SKU forecast. The category models use separate longer ONS outcomes with explicit conservative availability assumptions, as described above.

The zero-change reference is **descriptive only**: MAE **8.0784 percentage points**, RMSE **20.1500 pp**. It is not a held-out backtest, future accuracy or evidence that commodity/response features help. These improvements remain unknown. Exact scope and collection requirements are in `data/reports/evaluation.json` and `evaluation.md`.

## Launch and future work

```sh
./run.sh
```

Open `http://127.0.0.1:4173`; stop with Ctrl+C. The earlier `--prepare-only` path also completed successfully. See `DEMO.md` for the three-minute walkthrough.

All preview/test servers started for verification were stopped after the final audit; `./run.sh` starts a fresh local session.

Future modelling needs longer overlapping retail histories, reviewed dated family links and ingredient-label pairs, commodity publication/revision policies, and genuine weekly sugar, edible-oil and dairy feeds. Similarity candidates, selected changed products and monthly interpolation do not supply that evidence.

The former connected-browser failure was resolved by the user's explicit headless-browser authorisation. Full Chromium was used because the headless-shell screenshot path was unreliable on this host. There is no remaining browser-verification blocker.
