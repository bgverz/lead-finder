#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# prepare_reveal.sh  —  Show leads worth revealing and estimate Apollo credits
# Run from the project root:  ./scripts/prepare_reveal.sh
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
echo ">>> python -m lead_pipeline prepare-reveal"
echo ""

python -m lead_pipeline prepare-reveal
