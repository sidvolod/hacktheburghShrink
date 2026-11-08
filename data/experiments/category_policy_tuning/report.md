# Second-stage aggregation-policy experiment

Designed after examining initial retuning results; no untouched test remains. Category CPI only.

Ten policies and the36-month/min12 past-policy-error selection rule were frozen before computing this experiment's outer metrics. No model was retrained.
Each historical forecast records both policy-selection availability and candidate-ranking availability. Fixed policy scores are descriptive; they do not choose the live policy.

| Category | Months | Nested policy MAE pp | First tuning MAE pp | Original MAE pp |
|---|---:|---:|---:|---:|
| UK chocolate | 33 | 1.6511 | 1.5640 | 1.5747 |
| UK crisps | 33 | 1.3383 | 1.4478 | 1.3520 |

This is a retrospective second-stage replay after earlier results were examined. There is no fresh holdout, calibrated interval, or individual-product accuracy claim.
