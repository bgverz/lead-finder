$ErrorActionPreference = "Stop"

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

New-Item -ItemType Directory -Force -Path "data/input" | Out-Null
New-Item -ItemType Directory -Force -Path "data/output" | Out-Null
New-Item -ItemType Directory -Force -Path "data/processed" | Out-Null
New-Item -ItemType Directory -Force -Path "output" | Out-Null

Write-Host "Setup complete."
Write-Host "Next: edit .env, then run: python -m lead_pipeline doctor"
