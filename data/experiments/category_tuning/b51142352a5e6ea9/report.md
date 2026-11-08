# Retrospective category tuning

2024+ outcomes were examined before this design; this is not a fresh untouched test.

The nested policy, search limits, source hashes and candidates were frozen before this run produced any scores.
Each inner fit uses only labels available at its issue; each outer choice uses only past OOF errors published by the outer issue.
No final outer scores choose the next live model. The live selector uses the same fixed trailing36-month policy.

| Category | Outer months | Nested MAE pp | Original MAE pp | Improvement pp |
|---|---:|---:|---:|---:|
| UK chocolate | 33 | 1.5640 | 1.5747 | 0.0107 |
| UK crisps | 33 | 1.4478 | 1.3520 | -0.0958 |

A negative improvement means the new nested selector performed worse. Individual candidate rankings are descriptive exploratory comparisons, not a post-hoc winner selection.
Forecasts concern category CPI changes, not individual products, shrink events or recipes. No calibrated prediction intervals are emitted.
