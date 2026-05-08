#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_local.sh  —  One-time local environment setup
# Run from the project root:  ./scripts/setup_local.sh
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

echo ""
echo "=== Lead Pipeline — Local Setup ==="
echo ""

# 1. Create virtual environment if it doesn't exist.
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "  venv created."
else
    echo "  venv already exists — skipping creation."
fi

# 2. Activate and install requirements.
echo ""
echo "Installing / updating dependencies..."
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  Dependencies installed."

# 3. Copy .env.example to .env if missing.
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  .env created from .env.example."
    echo ""
    echo "  *** ACTION REQUIRED ***"
    echo "  Open .env and fill in your API keys before running the pipeline:"
    echo "    APOLLO_API_KEY=..."
    echo "    CENSUS_API_KEY=..."
    echo "    SEC_USER_AGENT=YourApp/1.0 your@email.com"
    echo ""
else
    echo ""
    echo "  .env already exists — skipping copy."
fi

# 4. Create required directories.
mkdir -p data/input data/output data/processed output

# 5. Done.
echo ""
echo "=== Setup complete. ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys  (if you haven't already)"
echo "  2. ./scripts/check_setup.sh      (verify everything is configured)"
echo "  3. ./scripts/run_founders.sh     (run your first live search)"
echo ""
