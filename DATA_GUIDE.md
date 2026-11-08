# Data preparation

The pipeline prepares **monthly grocery unit-price outcomes from dated retail observations** and **weekly commodity inputs**. A local TypeScript demo exposes seven curated snack reveals, dated retail histories and comparisons; launch it with `./run.sh`. The original product-level audit retains its unavailable fallback. A separate category module now trains Ridge and boosted trees using longer ONS chocolate/crisps indices and existing genuine weekly benchmarks. See `MODELS.md` and `data/experiments/category_forecast/` for trained results; category CPI does not replace or validate product-level unit-price predictions. See `data/reports/preparation-summary.json` and `schema.json` for the original preparation pipeline.

## Reproduce the outputs

From the project directory, the existing environment is ready:

```sh
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare --offline
```

This uses only cached raw inputs. To acquire missing inputs and prepare them:

```sh
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare
```

Downloads are cached, checksum-recorded and stored under `data/raw/`. Existing snapshots are retained. A changed URL/content requires an explicit new snapshot path or source-pin update, rather than silently blending releases. The retail source has a pinned content hash; OFF uses a pinned dataset revision and publisher hash. A new OFF acquisition may need its roughly 8 GB global Parquet because thousands of small row groups made remote range filtering slow. The UK projection and prepared catalogue are much smaller. All raw, derived, cache and temporary data stays inside `data/`.

Stages can be rerun independently, respecting dependencies:

```sh
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare --offline --stages open-prices evidence
PYTHONPATH=src .venv/bin/python -m shrinkflation prepare --offline --stages retail monthly features inventory
```

The complete order is `open-prices evidence retail catalogue commodities monthly linking features snack-cases evaluation app-export inventory`. `linking` needs both catalogue and retail outputs. `features` needs weekly commodities and monthly targets. `snack-cases` prepares the curated evidence registry; `evaluation` audits forecast feasibility; `app-export` creates the UI contract. `inventory` exposes every finished Parquet table through DuckDB and refreshes reports.

For a fresh environment:

```sh
mkdir -p data/tmp data/.cache/pip
python3 -m venv .venv
TMPDIR="$PWD/data/tmp" .venv/bin/python -m pip install --cache-dir "$PWD/data/.cache/pip" -r requirements.lock
```

Python 3.11 or later is supported for the base pipeline. The current environment uses Python 3.14, DuckDB and Requests, plus the optional pinned modelling environment in `requirements-models.lock`. Local UI dependencies are installed. `./run_models.sh` installs/checks the optional environment and trains; `./run.sh` exports completed category results without retraining.

## Files and lineage

| Location | Contents |
| --- | --- |
| `data/raw/` | Frozen public source responses and source metadata; originals retained |
| `data/interim/` | Rebuildable quantity-normalisation working files |
| `data/processed/` | Typed, compressed Parquet tables and a DuckDB file of views |
| `data/reports/` | Quality, coverage, schemas, checksums and provenance reports |
| `data/.cache/` | Local package/extension caches |
| `data/tmp/` | Bounded DuckDB spill and intermediate files |
| `research/` | Original handoff evidence and copied public photographs |

`research/source-manifest.json` remains the original copy manifest. `data/reports/raw-inventory.json` inventories acquired inputs with SHA-256 hashes; adjacent `.metadata.json` files record source URLs and retrieval times. Retrieval, database edit, price observation, reporting interval and article publication dates have separate meanings. Unknown dates remain null.

## Tables and what they establish

| Table/view | Meaning and limitations |
| --- | --- |
| `catalogue_products` | Current UK-tagged OFF states; raw multilingual names, ingredient declarations, quantities, images, revisions and database timestamps. No automatic historical dates or family membership. |
| `retail_products` | Provisional retailer plus exact raw-name identities. Pack sizes and counts remain part of the name identity until reviewed links bridge them. |
| `retail_prices` | Dated retailer observations with original rates, category/quality flags, declared-name quantities and dimension-specific unit-price bases. |
| `open_prices` | Explicit-GB, GBP observations with barcodes, store/proof references and promotion fields. Pack-unit prices are not divided by current enriched product quantities. |
| `open_prices_product_snapshots` | Current enrichment retained separately from dated prices; quantities are not historical proof. |
| `open_prices_exclusions` | Duplicate and out-of-market observations with source pointers and exclusion reasons. |
| `product_families`, `family_members` | Selected reported-case families and manually supported barcode membership; unknown validity boundaries remain null. |
| `reported_changes` | Five source-supported demonstration cases, raw evidence, source publication dates and recomputed unit-price changes. Exact event/transaction dates are unknown; excluded from monthly training labels. |
| `candidate_family_links` | Incomplete old/new barcode leads, separate from reviewed membership. |
| `retail_catalogue_candidates` | Top name-similarity candidates in 11 familiar snack groups, preserving size/count differences. Scores are uncalibrated and candidates need identity and temporal review. |
| `retail_monthly` | Monthly medians of observed daily unit prices, without filling missing days/months. Grams and millilitres are separate. |
| `monthly_targets` | Signed next-calendar-month changes, including falls and flat outcomes; missing targets remain null. This is a sampled-price target, not a verified shrink-event label. |
| `commodity_observations`, `commodity_daily` | Actual quotes and original source intervals, units, currencies, markets/stages, flags and raw-row lineage. |
| `commodity_weekly` | Real daily quotes aggregated to W-FRI buckets, or native weekly quotes mapped without anticipating their source intervals. No interpolation. |
| `commodity_monthly_support` | Existing World Bank monthly history, kept separate from weekly inputs. |
| `commodity_monthly_features` | Weekly summaries at monthly forecast cutoffs and the preparation-date cutoff. Exploratory and strict publication-aware modes are separate. |
| `snack_changes`, `snack_family_members` | Seven selected familiar-snack cases, unit-price calculations, price-basis labels and supported barcode membership. Quality Street shares the original reviewed family identifier. Missing prices/dates remain null. |

The app reads `data/app-public/data/demo.json`, containing eight real retailer listing histories and four same-day comparison snapshots as well as seven snack cases. Listing histories are not automatically attached as verified replacement chains. `data/reports/evaluation.json` records all three requested models as not run with null held-out metrics; its zero-change reference is descriptive, with 39,920 mass-price pairs and MAE 8.0784/RMSE 20.1500 percentage points. This single target month does not establish future model skill.

All tables can be queried with Python:

```python
import duckdb

con = duckdb.connect("data/processed/shrinkflation.duckdb", read_only=True)
print(con.sql("SHOW TABLES").fetchall())
print(con.sql("""
    SELECT target_month, count(*) AS pairs,
           median(next_month_unit_price_change_fraction) AS median_change
    FROM monthly_targets
    WHERE eligible_for_sampled_monthly_price_evaluation
    GROUP BY target_month ORDER BY target_month
""").fetchall())
```

DuckDB views reference the local Parquet paths and do not duplicate the large price table. If the project folder moves, rerun the offline `inventory` stage to update those paths.

## Cleaning rules

- Barcodes stay strings, preserving leading zeros. Retailer names are normalized for display while raw names remain available.
- Quantities preserve total mass, total volume, item quantity and pack count separately. Nested/multiple multipacks, conflicting totals, negative quantities and ambiguous thousands separators are flagged rather than guessed. No density assumption converts millilitres to grams.
- Retail duplicates across scraped categories collapse only when price/date/unit/name agree. Conflicting product/day values remain present and are excluded from canonical unit prices. Raw row references and grouping keys recover contributing source records.
- Unit-price rates are normalized only within their declared dimension. More than 5% disagreement with an unambiguous declared-name quantity is flagged; source values are retained. This threshold is a cleaning heuristic, not evidence that every remaining rate is correct. Finite positive values are required.
- Retail prices are the **lowest available price, including loyalty offers** according to the collector. Row-level loyalty/promotion status is unknown. They must not be described as base non-promoted prices.
- Human-food category filtering is provisional; broad categories can still contain inappropriate products. The full catalogue and retail tables remain available for review.
- Candidate links never automatically enter family membership, verified changes or monthly price histories. Different sizes/counts may be replacement evidence, but concurrent variants need to be ruled out.

## Monthly outcomes and weekly timing

For each retailer/listing, price basis, unit-price basis and dimension, the pipeline first calculates an observed daily unit price and then takes its monthly median. The target is the next calendar month's median divided by the current month's median minus one. A missing adjacent month is unknown; the join never skips a missing month or carries forward a price.

Default evaluation eligibility requires the source dataset to span both complete calendar months, at least three observed days in each, and observations within the first and last seven days of each month. These rules describe sampling coverage; they do not establish a continuously observed shelf price. January and April 2024 are partial source boundary months. The resulting strict monthly comparisons currently share only one target month. Many products do not create many independent time shocks.

Commodity weeks run Saturday through Friday. Daily trading quotes usually fall Monday-Friday. Native Mon-Sun reporting intervals retain their source dates and map to a following Friday, so Sunday information is never assigned to an earlier Friday. A weekly change requires adjacent weekly buckets; missing quotes/weeks are not filled. Oilseed quotes describe seeds, not crude edible oil. World cereal quotes labelled `$/ton` retain an unresolved ton definition rather than assuming metric tonnes.

Feature cutoffs are midnight **Europe/London** on the first day of the target month. Strict features require actual publication/vintage evidence available by that instant. All currently acquired commodity rows have unknown row-specific historical availability, so strict backtest eligibility remains false. `exploratory_observation_dates_only` summaries are usable for inspection but cannot support a claimed leakage-safe historical score. A normal publication schedule is not a recovered historical vintage.

## What remains before model evaluation

1. Review family candidates, separate concurrent variants from replacements, and collect dated pack/ingredient evidence. The current catalogue alone does not establish transitions.
2. Resolve outliers and choose a representative food cohort with consistent price conditions.
3. Obtain longer overlapping retail history; four calendar months are insufficient to evaluate broad 1/3/6-month commodity-response claims.
4. Establish commodity publication/revision policies, and fill genuine weekly sugar, crude edible-oil and relevant dairy gaps.
5. Choose chronological cutoffs and compare no-change/recent-price, history-only, commodity and response-pattern baselines on real data.

`data/source-registry.json` records considered sources that were deliberately not downloaded: restricted foodDB access, non-branded ONS basket microdata, unverified Trolley bulk access, and the short recent Yapp feed. Nothing in this preparation invents event dates, family chains, weekly movements, backtest results or model accuracy.

## Verification

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The checks cover source-unit dimensions, duplicate/conflicting records, leading-zero identifiers, current-versus-historical quantity evidence, multipack ambiguities, nonfinite values, adjacent monthly labels, missing targets, weekly boundaries, unknown/late publication and London daylight-saving cutoffs. Source-specific reports add actual-file counts and quality flags. Fixtures are synthetic test inputs only and are not exported as observed evidence.


## Receipt, whole-pack decisions and evaluation rule

The browser computes a hidden inflation receipt only for comparable known price bases and a documented mass reduction. Constant-weight cost is `new_price * old_mass / new_mass`. The missing-quantity amount is that cost minus `new_price`; the sticker contribution is `(new_price-old_price)/old_price`, and the sequential shrink contribution is `missing_quantity_amount/old_price`. Their sum equals the full unit-price increase. Full precision precedes display rounding. The constant-weight cost is hypothetical, with historical/RRP and retailer qualifications retained. Ghost-overlay area represents grams, not physical pack dimensions.

`wholePackMath.ts` finds the exact minimum checkout cost to meet a 50–1,000g target using integer packs from one given retailer/date/category snapshot. Prices must resolve to integer pence; gram values to integer milligrams, tolerating only representation noise. A greatest-common-divisor mass quantum keeps the dynamic program compact. With positive prices, a minimum-cost solution cannot contain a removable pack and lies below target plus largest pack mass. Equal costs choose lower excess, then fewer packs; remaining identity ties are deterministic. Invalid/unsupported data fails explicitly instead of silently discarding options. All 56 current options are retained. Recorded offers may require loyalty membership; stock, repeat-purchase eligibility and additional discount tiers are unknown.

`ForecastDecisionGate` applies a separate demonstration rule to the displayed category report: retain the model only if its test MAE is strictly below the no-change MAE over matching observation counts; otherwise use zero change. Missing or incompatible evidence yields no decision. The rule was designed after reviewing these test results, so it is prospective and unvalidated. It does not alter raw forecasts, historical metrics, model selection or stored predictions, and is not calibrated confidence or a detected regime.


## GitHub checkout and demo launch

The repository tracks `data/app-public` and the compact data/model/evidence inputs needed to view the demo. Default `./run.sh` validates that public snapshot, installs local runtime/dependencies as needed, builds and serves it without invoking research acquisition. `--refresh-data` explicitly runs the preparation/evaluation/export flow and can download several GB on a fresh checkout. Missing snapshots produce clear recovery instructions. Full raw downloads, the retail/catalogue Parquet tables, caches and browser HTML/test-result duplicates are excluded from Git. The weekly commodity table and small frozen ONS snapshots are included for category-model reproduction. Original frozen model manifests preserve historical provenance; public export paths are made relative in copied UI metadata without modifying those artifacts.
