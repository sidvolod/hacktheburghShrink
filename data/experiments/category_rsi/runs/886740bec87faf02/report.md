# Fixed boosted-tree RSI experiment

Retrospective exploratory comparison: the 2024–2026 outcomes were already inspected before this feature experiment.

Monthly UK category CPI changes; not product-level prices or shrinkflation probabilities

All new files stay inside `data/experiments/category_rsi/`. Delete that folder to remove this experiment. The website does not read it.

Each category keeps its original saved boosted-tree configuration and original history-plus-weekly inputs. Only RSI inputs change; no retuning, row dropping or promotion of a test winner.

| Category | Arm | Validation MAE pp | Later 33-month MAE pp | Reduction vs identical tree without RSI |
|---|---|---:|---:|---:|
| UK chocolate | Original boosted trees + weekly inputs | 1.6786 | 1.5747 | +0.00% |
| UK chocolate | Add weekly commodity RSI | 1.6784 | 1.6557 | -5.14% |
| UK chocolate | Add monthly category RSI | 1.6954 | 1.5985 | -1.51% |
| UK chocolate | Add both RSI groups | 1.7185 | 1.6417 | -4.25% |
| UK crisps | Original boosted trees + weekly inputs | 2.2364 | 1.5405 | +0.00% |
| UK crisps | Add weekly commodity RSI | 2.2313 | 1.5652 | -1.60% |
| UK crisps | Add monthly category RSI | 2.2497 | 1.5318 | +0.57% |
| UK crisps | Add both RSI groups | 2.2441 | 1.5802 | -2.57% |

## Context

- UK chocolate: currently displayed original model MAE 1.5747 pp; no-change MAE 1.9770 pp. The crisps original winner is Ridge, so an RSI gain over a boosted-tree control is not automatically a gain over the displayed model.
- UK crisps: currently displayed original model MAE 1.3520 pp; no-change MAE 1.2648 pp. The crisps original winner is Ridge, so an RSI gain over a boosted-tree control is not automatically a gain over the displayed model.

## How this was checked

The no-RSI model is refitted and must reproduce every saved original validation/test prediction within 1e-10. Every fit retains original publication-aware training rows and fold-local imputation. RSI gaps stay missing and do not remove target months.

Weekly Wilder RSI uses 14 level differences, an initial arithmetic-mean seed and alpha=1/14 recursion. Each applicable benchmark is computed at the current issue and three calendar months earlier, reapplying publication buffers and staleness. Category-level RSI uses six monthly differences and ends at the latest published CPI observation. Flat sequences use 50. Missing periods reset the chain; no filling.

The manifest is frozen before this run computes new scores. This does not turn previously seen outcomes into a new holdout. Forecasts remain category-index changes rather than specific product prices, pack sizes or shrink probabilities. Current-archive and availability-buffer assumptions remain.

Each arm has saved configuration, validation/test CSVs, paired monthly error changes, yearly metrics and a fitted live model. There is no newly selected live winner or calibrated prediction interval.
