#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$TASK_ROOT"
mkdir -p data/tmp data/.cache/pip data/.cache/npm
export TMPDIR="$TASK_ROOT/data/tmp"
export NPM_CONFIG_CACHE="$TASK_ROOT/data/.cache/npm"
export NPM_CONFIG_AUDIT=false
export NPM_CONFIG_FUND=false
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import duckdb, requests' >/dev/null 2>&1; then
  .venv/bin/python -m pip install --cache-dir "$TASK_ROOT/data/.cache/pip" -r requirements.lock
fi
for TASK_ARG in "$@"; do
  if [ "$TASK_ARG" = "--check" ] && ! .venv/bin/python -c 'import pandas, sklearn, joblib, pyarrow, matplotlib' >/dev/null 2>&1; then
    .venv/bin/python -m pip install --cache-dir "$TASK_ROOT/data/.cache/pip" -r requirements-models.lock
  fi
done
export PYTHONPATH="$TASK_ROOT/src"
exec .venv/bin/python scripts/launch.py "$@"
