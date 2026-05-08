#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_vc_pe.sh  —  Search for VC and PE professionals (Apollo: vc_pe profile)
# Run from the project root:  ./scripts/run_vc_pe.sh
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
echo ">>> python -m lead_pipeline run --mode api --profile vc_pe --limit 25 --open"
echo ""

python -m lead_pipeline run --mode api --profile vc_pe --limit 25 --open
