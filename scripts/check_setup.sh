#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# check_setup.sh  —  Verify the pipeline is ready to run in API mode
# Run from the project root:  ./scripts/check_setup.sh
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
echo ">>> python -m lead_pipeline doctor --mode api"
echo ""

python -m lead_pipeline doctor --mode api
