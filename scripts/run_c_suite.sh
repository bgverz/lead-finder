#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_c_suite.sh  —  Search for C-suite executives (Apollo: c_suite profile)
# Run from the project root:  ./scripts/run_c_suite.sh
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d "venv" ]; then
    echo ""
    echo "ERROR: Virtual environment not found."
    echo "Run ./scripts/setup_local.sh first to create it."
    echo ""
    exit 1
fi

source venv/bin/activate

echo ""
echo ">>> python -m lead_pipeline run --mode api --profile c_suite --limit 100 --open"
echo ""

python -m lead_pipeline run --mode api --profile c_suite --limit 100 --open
