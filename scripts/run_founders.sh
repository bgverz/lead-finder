#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_founders.sh  —  Search for founders and operators (Apollo: founders profile)
# Run from the project root:  ./scripts/run_founders.sh
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
echo ">>> python -m lead_pipeline run --mode api --profile founders --limit 25 --open"
echo ""

python -m lead_pipeline run --mode api --profile founders --limit 25 --open
