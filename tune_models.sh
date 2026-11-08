#!/bin/sh
# Separate tuning run; original category experiments remain unchanged.
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$TASK_ROOT"
mkdir -p data/tmp data/.cache/pip data/.cache/matplotlib data/experiments/category_tuning
export TMPDIR="$TASK_ROOT/data/tmp"
export MPLCONFIGDIR="$TASK_ROOT/data/.cache/matplotlib"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4
export NUMEXPR_MAX_THREADS=4
export PYTHONPATH="$TASK_ROOT/src"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import duckdb, requests, pandas, sklearn, joblib, pyarrow, matplotlib' >/dev/null 2>&1; then
  .venv/bin/python -m pip install --cache-dir "$TASK_ROOT/data/.cache/pip" -r requirements-models.lock
fi
.venv/bin/python -m shrinkflation.category_tuning "$@"
exec .venv/bin/python -m shrinkflation.category_policy_tuning "$@"
