# Isolated RSI experiment

Everything new for this experiment lives here:

```text
data/experiments/category_rsi/
```

Delete this entire folder to remove the experiment. No application imports,
website settings, existing model files or project dependencies are changed.

From this folder, run:

```sh
./run.sh > training.log 2>&1
```

It uses the existing project `.venv`, runs focused RSI checks, then reproduces
the original boosted-tree control and compares four fixed feature sets on
exactly the original 34 validation and 33 later evaluation months:

1. Original price-history and weekly-commodity inputs.
2. Those inputs plus weekly commodity RSI.
3. Original inputs plus monthly grocery-category RSI.
4. Original inputs plus both RSI groups.

Weekly Wilder RSI uses 14 changes in the existing weekly benchmark values
(weekly averages/quotes, including the FX ratio of weekly means). It is also
computed at the issue date three calendar months earlier. The existing seven
or fourteen-day release buffers and 35-day staleness rule apply at each issue.
Category RSI uses six monthly changes in the index level, ending at the latest
published CPI month. An initial arithmetic-mean seed is followed by Wilder's
recursion. Calendar gaps reset the chain; missing values remain missing. The
existing fold-local imputer handles them without discarding evaluation dates.

Model settings, training-label availability and preprocessing are fixed. The
control must reproduce the saved original predictions to within 1e-10. A
manifest records the feature policy, model settings, runtime and input/code
checksums before new scores are computed. Hash-addressed folders under `runs/`
contain source snapshots, the enhanced dataset, feature-availability audits,
per-arm configurations/predictions/metrics/fitted models, paired monthly error
changes and plots. Root `summary.json` and `report.md` show the latest run.

These years were already examined. All new scores are retrospective exploratory,
not a new untouched test. They concern monthly category CPI changes, not an
individual product's price, size or recipe. An improvement over the fixed crisps
boosted-tree control does not necessarily beat the original displayed Ridge
model. No RSI variant is automatically selected or displayed in the website.

No downloads or cloud training are needed. Keep this folder until reviewing
`report.md`; deletion remains a separate choice.

## Result, 8 November 2026

The final run is `886740bec87faf02`. On the same 33 later months, RSI did not improve chocolate. Monthly grocery RSI slightly improved the crisps boosted-tree control, by 0.0087 percentage points of MAE (0.57%); its median monthly error change was slightly worse and it still trails the currently displayed Ridge model (1.3520 pp) and no change (1.2648 pp).

| Fixed feature set | Chocolate MAE pp | Crisps MAE pp |
| --- | ---: | ---: |
| Original boosted-tree inputs | 1.5747 | 1.5405 |
| Add weekly commodity RSI | 1.6557 | 1.5652 |
| Add monthly grocery RSI | 1.5985 | 1.5318 |
| Add both RSI groups | 1.6417 | 1.5802 |

Lower is better. These are previously examined years, so the comparison is exploratory. No RSI variant was promoted to the website.

Fifteen focused tests passed. The control exactly reproduced all 134 original validation/test predictions. Original columns were preserved, missing RSI values did not drop dates, and 1,721 protected existing files remained unchanged. Four feature sets per category produce 536 saved validation/test forecasts and eight fitted live models.

An initial run (`ab5230a822edfcb9`) is retained with its source snapshot. A timezone edge-case fix then made London-offset and equivalent UTC issue timestamps behave identically. The final run's predictions and live values are exactly identical to the initial run on the existing frozen data; the feature definitions and model settings were not adjusted after scoring.
