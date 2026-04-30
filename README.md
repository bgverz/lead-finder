# Accredited Investor Lead Generation Pipeline

An automated pipeline that identifies, enriches, and scores potential accredited investors ($5M+ net worth) using public data sources and Apollo.io integration.

Built for pre-IPO / secondary market sales teams selling shares in late-stage private companies.

## What It Does

1. **Targets wealthy zip codes** using Census Bureau income and home value data
2. **Pulls property records** for $2M+ homes from county assessor databases
3. **Identifies business owners** via state corporation filings and OpenCorporates
4. **Finds prior investors** through SEC EDGAR Form D filings
5. **Enriches with Apollo** to get work email, title, company, and LinkedIn
6. **Validates phone numbers** via NumVerify
7. **Scores and ranks** every prospect from 0-100
8. **Outputs formatted Excel** sorted by lead quality tier

## Quick Start

```bash
# Clone and install
git clone (https://github.com/bgverz/lead-finder)
cd investor-lead-pipeline
pip install -r requirements.txt

# Configure
cp config/config.example.yaml config/config.yaml

# Run the pipeline
python -m src.main --config config/config.yaml --zip-codes 06830,06831

# Run for an entire state
python -m src.main --config config/config.yaml --state CT
```

## Project Structure

```
investor-lead-pipeline/
├── config/
│   ├── config.example.yaml      # Template config (commit this)
│   └── config.yaml              # Your config with API keys (DO NOT commit)
├── src/
│   ├── main.py                  # CLI entry point & pipeline orchestrator
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── census.py            # Census Bureau API - geographic targeting
│   │   ├── property.py          # County assessor / ATTOM - property records
│   │   ├── business.py          # State SOS / OpenCorporates - entity matching
│   │   └── sec_edgar.py         # SEC EDGAR - Form D filing search
│   ├── enrichment/
│   │   ├── __init__.py
│   │   ├── apollo.py            # Apollo.io API - contact enrichment
│   │   └── phone.py             # NumVerify - phone validation
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── scorer.py            # Weighted scoring engine
│   ├── output/
│   │   ├── __init__.py
│   │   └── excel.py             # Formatted Excel output
│   └── utils/
│       ├── __init__.py
│       ├── config.py            # Config loader
│       ├── database.py          # SQLite storage layer
│       ├── rate_limiter.py      # API rate limiting
│       └── logger.py            # Structured logging
├── data/
│   ├── raw/                     # Raw API responses (cached)
│   ├── processed/               # Intermediate processed data
│   └── output/                  # Final Excel output files
├── tests/
│   ├── test_census.py
│   ├── test_scorer.py
│   └── test_pipeline.py
├── docs/
│   └── api_setup_guide.md       # How to get API keys
├── requirements.txt
├── .gitignore
└── README.md
```

## Data Sources

| Source | What It Provides | Cost |
|--------|-----------------|------|
| Census Bureau API | Median income, home values by zip/tract | Free |
| County Assessor / ATTOM | Property values, owner names, sale history | Free / ~$0.10/record |
| State Secretary of State | LLC/Corp filings, officers | Free |
| SEC EDGAR | Form D filings, investor/officer names | Free |
| OpenCorporates | Company records, linked officers | Free (500 req/mo) |
| Apollo.io | Work email, title, company, LinkedIn, phone | Existing subscription |
| NumVerify | Phone validation, line type | Free (100/mo) |

## Configuration

All scoring weights, thresholds, and target areas are configurable in `config.yaml`. See `config/config.example.yaml` for documentation of every option.

## License

Private - Internal use only.
