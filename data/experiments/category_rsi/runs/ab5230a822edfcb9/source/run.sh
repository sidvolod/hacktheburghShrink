#!/bin/sh
# All new code, logs, caches and results stay inside this removable folder.
set -eu
EXPERIMENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$EXPERIMENT_DIR/../../.." && pwd)
export PYTHONPATH="$PROJECT_DIR/src:$EXPERIMENT_DIR"
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR="$EXPERIMENT_DIR/.cache/matplotlib"
export TMPDIR="$EXPERIMENT_DIR/.cache/tmp"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4
export NUMEXPR_MAX_THREADS=4
mkdir -p "$MPLCONFIGDIR" "$TMPDIR"
if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  printf '%s\n' 'The existing project Python environment is required; no global packages will be installed.' >&2
  exit 1
fi
cd "$EXPERIMENT_DIR"
"$PROJECT_DIR/.venv/bin/python" -B -m unittest discover -s . -p 'test_*.py'
exec "$PROJECT_DIR/.venv/bin/python" -B "$EXPERIMENT_DIR/run.py" "$@"
