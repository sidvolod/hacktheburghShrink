# Category forecast experiments

UK grocery category CPI monthly change, not individual SKU unit price or shrink events

Models are chosen on pre-2024 validation outcomes available by 8 December 2023. Test outcomes never choose the winner.
Each expanding training fold includes only labels available by that forecast's cutoff. Weekly commodity features retain documented source-availability assumptions.

| Category | Validation-selected model | Test months | MAE pp | Zero-change MAE pp |
|---|---|---:|---:|---:|
| UK chocolate | hist_gradient_boosting / history_plus_weekly_commodities | 33 | 1.5747 | 1.9770 |
| UK crisps | ridge / history_only | 33 | 1.3520 | 1.2648 |

The forecast is a monthly category-index percentage change. It does not predict an individual brand's shelf price, price per gram, shrink mechanism or recipe change.
No prediction intervals are emitted because independent post-selection calibration is not established.
If a baseline wins validation, that baseline remains the selected forecast, including when another model scores better on the later test.

Full per-model configuration, validation/test predictions, metrics and fitted learned-model artifacts are in separate model/feature-group folders.
