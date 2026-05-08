#!/usr/bin/env bash
set -euo pipefail

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
fi

mkdir -p data/input data/output data/processed output

echo "Setup complete."
echo "Next: edit .env, then run: python -m lead_pipeline doctor"
