# shrincflationTrack — project handoff

Prepared 8 November 2026, Europe/London. This is a substantive handoff from the original Codex chat, not a verbatim transcript. The user requested a new Desktop folder named exactly `shrincflationTrack`, opened in VS Code, so implementation can continue there with the full project context.

## Read this first

The agreed idea is a UK grocery shrinkflation and recipe-change detective, with a forecasting layer. Familiar products make the hidden history relatable: “I swear Snickers used to be bigger.” Show the evidence that it did change, what happened to the price per gram, and what may happen next.

**The user clarified the cadence repeatedly: MONTHLY grocery-price changes are the forecasting target; WEEKLY commodity movements are the explanatory inputs.** Do not reinterpret this as a seven-day grocery forecast or insist on weekly retail changes. Daily retail snapshots can help reconstruct monthly outcomes, but the desired prediction is monthly.

No grocery application, model, matching module or backtesting system has been built. Research and small public-data downloads exist. The latest request is to set up this folder, open VS Code and hand over context. The user intends to give the coding instruction in that workspace; do not treat this handoff as an instruction to start an autonomous full build before that next instruction.

## Team, event and motivation

- Three people on the team. The user last estimated 6–12 hours until submission during the preceding discussion. This is a historical estimate, not a current countdown; the exact deadline and multiple-track entry rules remain unconfirmed.
- G-Research track: “Make the invisible visible.” Reveal hard-to-observe facts, show how we found them, and what can be done with them.
- HRT track: “Best Use of Data for Predictions & Decision Making.” The user reports the sponsor is interested in cool technical projects, not only finance. Historical backtests and a useful forecast/decision layer matter.
- User wants a memorable, visually polished demo around products judges recognise: Snickers, Maltesers, Milky Way, crisps such as Doritos/Walkers/Pringles, and other familiar snacks. Prefer everyday products to an exclusively seasonal Easter-egg showcase.
- A previous project, EchoSense, attempted iPhone acoustic sonar. It received coherent chirps and promising book echoes but did not demonstrate reliable hand tracking or spatial room mapping. This grocery project is a separate pivot. Do not bring its app code or personal recordings into this project.
- Available hardware: M4 Mac and iPhone 16 Pro Max. Cloud training was discussed as an option, not a requirement. Dataset preparation and baseline tree models can start locally.

## The user's complete product concept

1. **Historical detective.** Search or scan a product and reconstruct its UK history across barcodes: pack mass, item count, ingredient declarations, shelf prices, and price per 100g. Show old/new packaging and ingredient-label differences with source links and evidence dates. The emotionally compelling reveal is that the shopper's memory was right.
2. **Learn responses.** Align verified size/price/recipe changes with preceding weekly movements in relevant commodities: cocoa, sugar, wheat, oils, and appropriate dairy inputs, plus relevant currency/cost features if available. Look for lagged responses rather than assuming an immediate effect.
3. **Forecast monthly unit-price changes.** Use the latest commodity movements, current shop prices, and the product/brand's prior actions to predict next month's change in price per gram.
4. **Predict how the increase may happen.** A smaller pack at the same price, the same pack at a higher price, or both can produce a higher unit price. Previous actions and time since each action may be informative. The user suggested that a brand might alternate shrink and shelf-price rises. Treat this as a learnable hypothesis/feature, not a universal hard-coded rule.
5. **Support a decision.** Compare documented alternatives by unit price and the shopper's ingredient preferences. Recommendations require actual dated prices or explicitly entered assumptions.

The historical reveal supplies the G-Research story; the evaluated forecasting layer supplies the HRT story. The two should share the same product histories.

## Preferred technical direction

User agrees with Python for preparation/modelling/backtesting and TypeScript for a beautiful interface. Specific libraries were recommendations, not installed or irrevocably selected:

- Python, DuckDB and Parquet for large-table filtering/joins; pandas for smaller inspection tables.
- RapidFuzz or similar name similarity for candidate ranking, followed by evidence-based review.
- Start with linear regression and a small gradient-boosted tree model, comparing against no-change/recent-price baselines. A small ReLU network is an option only if it adds value.
- MLForecast was suggested for panel forecasting and chronological rolling backtests. Skforecast was also researched for probabilistic forecasting/bootstrapped intervals. Pick one suitable approach rather than accumulating frameworks.
- React + TypeScript + Vite, Tailwind, shadcn/ui and Recharts were suggested for UI.
- Initially export prepared histories, evidence and predictions as versioned JSON. Add FastAPI if interactive backend calculations are needed.
- Do not add C++, a GNN, a large language model, cloud infrastructure or deep learning merely for complexity. A custom data pipeline, product-family reconstruction, verified evidence and measured backtest are the substantive technical work.

## Forecast specification and evaluation

**Inputs:** weekly commodity histories available before the forecast date, prior monthly retail/unit-price history, current pack mass/count and recipe facts known then, retailer/brand/category, previous response types, and time since previous adjustments.

**Targets:** next-month or next-30-day unit-price change; optionally probability of an increase, magnitude conditional on an increase, and likely mechanism when sufficient verified event labels exist. Keep signed price falls/pack expansions and flat outcomes in the data, too.

Useful candidate features include weekly changes over the preceding 4–12 weeks, cumulative changes, volatility, acceleration, persistent cost pressure, previous one/two/three change types, and time since the last change. Test 1/3/6-month lag relationships only where the overlapping retail history supports them.

Price consistency:

`price_per_100g = 100 * pack_price / total_net_mass_g`

The unit-price ratio is `(new_price / new_mass) / (old_price / old_mass)`. A 100g→90g reduction at unchanged price means 10% less product and about 11.11% higher price per gram. Preserve individual-item mass, pack count and total mass separately. Compare millilitres to millilitres; do not assume density of 1g/ml.

Backtest using historical cutoffs and only information available at each cutoff. Do not randomly split repeated product-day observations. Account for overlapping next-30-day labels and use a later test period. Product-family holdouts test generalisation to unseen products where that is an explicit goal. Missing later observations are unknown/censored, not evidence of no change.

Compare these models/features:

1. No change / recent-price or rolling-median baseline.
2. Product-price history alone.
3. Product history + weekly commodity changes.
4. The above + previous shrink/price-change response patterns.

Report actual improvement, errors in unit-price change, and appropriate event precision/recall where applicable. For probabilistic forecasts, measure interval coverage and width; a nominal 80% interval needs empirical testing. Tree regression combines numeric predictions from many trees; it is not a conversational sequence of repeated yes/no questions. Classifier probabilities need evaluation/calibration before being displayed as reliable probabilities.

Commodity correlation alone does not establish causality or reveal confidential manufacturer contracts/margins. The user once suggested results could be “kinda fake”; no fabricated observations, model results, backtests or claimed accuracy were accepted. Explicit simulations may illustrate scenarios, separately labelled from actual evidence and held-out performance. Avoid moralising; make claims concrete and support them with data.

**Monte Carlo is optional.** After a useful model exists, simulate whether changes occur and their sizes, or use appropriate blocks of held-out forecast errors. Represent stepped changes/promotions where supported. Simulations do not supply missing evidence. A user-controlled commodity shock is a scenario, not a measured probability. A useful demo extension is “rewind”: hide future history, show a forecast, then reveal what actually happened.

## Data model and matching corrections

Use a product-family identifier above individual barcodes/product versions. The barcode identifies a version; it is not the entire history.

Recommended linked tables:

- Product observations/versions: raw and normalised name/brand, barcode, explicit market, flavour/format, total quantity/unit, individual quantity, pack count, raw ingredient text, image/revision references and source.
- Price observations: version/barcode or source product ID, retailer/store/channel, actual observation date, price/currency, promotion/loyalty conditions and proof.
- Candidate family links: old/new candidates, identity evidence, uncalibrated similarity scores, review status and rejection reasons.
- Verified changes: confirmed link, before/after size/count/ingredients, dates or bounded date intervals, evidence grade and supporting sources.
- Weekly commodity features, with source, units, currency and publication/availability dates.

Important corrections from the discussion:

- GS1 requires a new GTIN for declared net-content changes. Same-barcode revisions alone miss compliant shrinkflation. ONS also reconstructs relaunches across identifiers.
- A count of repeated barcodes is only a same-barcode coverage audit. The user correctly challenged treating it as the limit of product-family history. Cross-GTIN linking and multiple sources can recover more histories; actual family-level coverage has not yet been measured.
- Different pack sizes can be sold simultaneously. Similar names and brands do not alone establish a replacement.
- **Do not require the same multipack count as a hard matching gate.** Five bars becoming four may be precisely the event. Preserve the difference and investigate identity/temporal evidence.
- Preserve raw text and quantities. Normalise units, brand aliases and punctuation, but retain flavour, dietary variant, pack format and declared percentages. Large recipe changes may be the target; do not automatically discard them as incompatible matches.
- OFF creation/edit/image-upload dates are database events, not proven product launch, reformulation or on-sale dates. Event dates may be intervals.
- Compare raw ingredient declarations and label photos. Changes in computed taxonomies or scores can be processing changes rather than reformulation. Record “ingredient added/removed” and declared percentage changes; do not infer exact amounts or cost savings from ingredient order alone.
- A broad catalogue, selected positive demonstration cases, and a representative forecasting panel are different data assets. Keep them separate.

## Sources checked and actual status

### 1. Official Open Food Facts catalogue and revisions

- Official dataset: https://huggingface.co/datasets/openfoodfacts/product-database
- Candidate direct food file: https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet
- Viewer showed roughly 4.98 million global rows / 8.11GB across the dataset. Research checked the food file at 8,035,571,362 bytes. Counts/sizes are observations at research time, not fixed constants.
- Filter `countries_tags` for `en:united-kingdom`; UK row count and field completeness were NOT audited.
- Current snapshot is not all historical revisions and does not contain retail-price histories.
- Historical guidance: https://support.openfoodfacts.org/help/en-gb/12-api-data-reuse/105-how-can-i-access-historical-data
- Individual history example: `/api/v2/product/BARCODE?rev=1`.
- API guidance: https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/
- At research time, official guidance said 15 product reads/minute/IP and 10 searches/minute/IP. Cache requests and verify current limits before ingestion. General full-text search is not available through every structured API endpoint; local catalogue search is suitable.
- OFF global structured search returned HTTP503 in one root-agent request; a large catalogue was NOT downloaded. Other research requests successfully retrieved individual product records/photos.
- OFF data: ODbL; images: CC-BY-SA. Preserve attribution and source links.
- An old CSV staleness bug, issue15024, was closed via15053. Do NOT repeat the outdated claim that CSV is currently stale. Audit actual content timestamps.

### 2. Larger UK retail-price panel — promising, not yet audited/downloaded

- Original: https://www.kaggle.com/datasets/declanmcalinden/time-series-uk-supermarket-data
- Consolidated Parquet: https://huggingface.co/datasets/Rif-SQL/time-series-uk-retail-supermarket-price-data
- Viewer reports 9,529,242 rows, five retailers, capture dates 2024-01-09 to 2024-04-13, and columns `supermarket_name`, `price_gbp`, `price_unit_gbp`, `unit`, `product_name`, `capture_date`, `category_name`, `is_own_brand`.
- Curator says this is an unchanged merge of five source CSVs; card states Apache2.0. Verify original provenance, licensing, completeness, unique products, duplication, dates and units before reliance. The card mentions sales/demand uses although the displayed schema has no sales quantities; do not invent sales data.
- No barcode or ingredient field appears in the inspected schema. Joining to OFF will require retailer/name/quantity family matching and manual evidence.
- Millions of product-day rows do not create years of common monthly commodity shocks. Audit actual overlapping time coverage and change events. This limits long-lag causal claims, not the usefulness of the entire product panel.

### 3. Open Prices — already downloaded as a small supplementary source

- Docs: https://openfoodfacts.github.io/open-prices/
- Data model: https://openfoodfacts.github.io/open-prices/topics/core/
- Query: https://prices.openfoodfacts.org/api/v1/prices?currency=GBP
- Downloaded all21 pages, 100 rows/page maximum in this query. Returned2,049 GBP observations spanning 2024-06-21 to2026-11-02. Public raw pages and coverage summary are copied into this folder.
- Root audit after duplicates and explicit GB-location filtering:2,036 observations,2,021 barcoded observations,1,590 barcodes;237 barcodes had at least2 distinct dates;3 had6 distinct months;127 barcode-store pairs had2 dates;1 pair had6 dates.
- The saved original `coverage-report.json` contains the broader GBP audit:2,042 nonduplicate observations,2,027 barcoded observations,1,596 barcodes. These are different scopes, not contradictory counts.
- These counts do NOT count reconstructed cross-barcode product families, and do NOT demonstrate that family-level forecasting is impossible. Some GBP entries had non-GB locations; currency is not a substitute for market filtering.
- Nested product objects include current quantities and names. A current product object is not itself dated proof of the old quantity. Validate historical unit-price denominators.
- Proofs/receipts, discounts, locations and dates help verify comparisons. No forecasting model was trained.

### 4. Commodity inputs

- World Bank: https://www.worldbank.org/en/research/commodity-markets
- Monthly workbook successfully downloaded from: https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx
- It is copied as supporting monthly history. **It does not fulfil the agreed WEEKLY commodity input requirement.** Obtain genuine daily/weekly data, aggregate daily to weekly if suitable, and preserve units, currencies, publication dates and any futures-contract/roll conventions.
- Do not interpolate monthly observations and claim newly observed weekly movements. Monthly averages are not OHLC candles. Historical commodity data is not the main unresolved issue; reliable overlap with product outcomes is.

### 5. Selected documented cases

Copied research includes five selected UK cases from Which?, with date limitations and evidence grades. These are deliberately selected changed products, not a representative training sample:

| Product / retailer | Earlier | Later |
|---|---|---|
| Quality Street / Morrisons |600g,£6|550g,£7|
| Galaxy XL Easter Egg / Asda |252g,£4.98|210g,£5.97|
| M&M's Crispy Easter Egg / Asda |192g,£3.48|156g,£3.97|
| Maltesers Easter Egg / Tesco |231g,£6|194g,£7|
| Cadbury Mini Eggs Easter Egg / Morrisons |193.5g,£4|181g,£5|

- Quality Street source: https://www.which.co.uk/news/article/shrinkflation-the-brands-charging-you-more-for-less-atUkT4m2GjuP (28Oct2025). Old barcode8445290146434; new8445291609181. Old OFF quantity600gm, corroborated by https://www.centralcoop.co.uk/food/products/8445290146434 . New label photo visibly shows550g and its barcode. The source does not give an exact transaction/transition day; do not invent one. The copied case file corrects an earlier inferred old-year label.
- Easter source: https://www.which.co.uk/news/article/is-your-favourite-easter-egg-shrinking-atsR95I73wSF (20Mar2026). Compares2025/2026 base non-promoted prices at named retailers. Exact transaction dates and most OFF barcode/photo pairs remain unverified.

Everyday snack evidence researched later (not yet full OFF-barcode chains):

- **Snickers single bar58g→48g in2013.** Government report records manufacturer-reported sizes: https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/709008/Sugar_reduction_progress_report.pdf . The Grocer reports unchanged51p recommended price, not an observed shop transaction: https://www.thegrocer.co.uk/news/mars-bars-shrink-but-price-stays-the-same/352754.article . Reported motivation included a calorie commitment; do not automatically label commodity costs the cause.
- **Maltesers sharing pouch121g→103g inNov2016, then93g reportedMar2017.** https://news.sky.com/story/mars-blames-rising-costs-for-maltesers-reduction-10662160 and https://www.the-independent.com/news/business/malteser-m-ms-minstrels-packs-smaller-shrinkflation-15-per-cent-reduction-size-a7651576.html . Separately,189g→175g replacement reported29Jul2022: https://www.thegrocer.co.uk/news/maltesers-sharing-packs-shrunk-as-owner-mars-cracks-down-on-costs/669955.article . Do not assume all different pouch formats form one continuous chain.
- **Doritos sharing bag200g→180g, £1 unchanged atAsda.** https://www.which.co.uk/news/article/shrinking-products-are-we-paying-more-for-less-a0Px52J4CFU1 (23Feb2019). The change was already reportedApr2017, so article publication is not the transition date: https://www.thegrocer.co.uk/news/peperami-and-doritos-get-smaller-as-shrinkflation-hits-snacks/551079.article .
- **Cadbury Oreo Bites Tesco110g→100g, £1.75 unchanged; M&M's Chocolate More to Share Sainsbury's220g→200g, £3.60 unchanged.** https://www.thegrocer.co.uk/news/cadbury-and-mars-wrigley-shrink-chocolate-packs-amid-cocoa-inflation/701463.article (25Feb2025). Recompute percentages from raw figures; some percentage statements in the article were inconsistent.
- Pringles and McVitie's examples: https://www.which.co.uk/news/article/shrinkflation-on-the-rise-which-reveals-the-items-that-have-shrunk-in-size-but-not-in-price-az2376B4mj5T . Keep exact format/date/retailer and price evidence distinct.
- Milky Way is a user-preferred candidate; the government report records21.9g→21.5g in2013. A stronger visually dramatic, fully evidenced history was not established.
- Recipe leads include Penguin/Club/Toffee Crisp. Current manufacturer descriptions or news reports alone are not a complete historical ingredient comparison. Two Dairy Milk barcode/image leads in the research JSON are explicitly incomplete and must not silently become verified training examples.

### 6. Other sources considered

- Oxford foodDB has relevant UK longitudinal product data, but branded product-level access is not freely downloadable. A2026 primary study states access arrangements are needed: https://www.nature.com/articles/s43016-026-01384-3 (Data availability). Do not depend on obtaining access within the hackathon or contact anyone without user authorisation.
- https://github.com/RDeconomist/prices advertises43million UK prices1988–2022. Its ONS basket-item metadata is not a branded barcode/ingredients catalogue. IndicatorW means weight/volume change, not necessarily shrinkage. Source: https://doc.ukdataservice.ac.uk/doc/7022/mrdoc/pdf/7022_cpi_microdata_metadata_2017.pdf . It does not directly solve the OFF join.
- https://data.yappman.com/mcp/ documents a free CC-BY4 daily212-item UK basket from24Sep2026, with dates, retailer IDs, available EANs, pack sizes, prices and loyalty details. Short history and limited coverage; not downloaded/audited.
- https://www.trolley.co.uk/grocery-price-index/ has historical comparisons, but a bulk download/API was not verified. Do not assume access or a licence to ingest its full dataset.
- ONS relaunch methodology: https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/introducinggroceryscannerdataintoconsumerpricestatistics . Some retailer IDs bridge barcode changes, others need explicit links.
- GS1 net-content standard: https://ref.gs1.org/standards/gtin-management/ section2.3.

## What is actually in this folder

- `AGENTS.md`: concise instructions to load this handoff.
- `PROJECT_HANDOFF.md`: this context.
- `README.md`: short start instructions.
- `research/reported-cases.json`: selected factual cases and evidence links; not training labels with exact event dates.
- `research/dataset-plan.json`: earlier OFF-led research, supplemented and corrected by this handoff.
- `research/images/`: downloaded public label photographs, including incomplete leads. Preserve OFF attribution; inspect before use.
- `data/raw/open-prices/`:21 downloaded GBP pages plus original coverage/fetch reports.
- `data/raw/commodities/worldbank-monthly.xlsx`: supporting monthly commodity workbook.
- `research/source-manifest.json`: provenance and hashes for copied files.

No package installation, UI scaffold, trained model, model score, large retail-panel download, weekly commodity feed or verified family-wide join exists yet. Earlier proposed matching code was stopped before files/tests were written when the user said to keep planning.

## Suggested first coding task when the user starts it

Start with a bounded data audit and an end-to-end vertical slice. Inspect the larger UK retail panel; normalise quantities and unit prices; select familiar product families; link versions and retain evidence/confidence; count actual changes and overlapping weekly commodity coverage. Build a small reproducible baseline/backtest before polishing its forecast presentation. A family-matching audit and a documented historical reveal can proceed in parallel with the UI.

Keep status concrete: files obtained, products linked, changes verified, monthly histories available, features known at cutoff and held-out performance. Prefer a small working demonstration with transparent coverage to a search box that invents a timeline for every item. The user wants ambitious, funny, technically interesting work; routine reversible implementation can proceed autonomously once requested. Do not repeatedly ask the user to restate this project or its monthly-target/weekly-input setup.
