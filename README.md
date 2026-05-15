# Accredited Investor Lead Pipeline

This is a Python CLI that searches Apollo.io for accredited investor leads — founders, VCs, PE professionals, family office managers, and C-suite executives — enriches each candidate with US Census income/home-value data, SEC EDGAR Form D filings, and optional ATTOM property records, scores every lead on a 0–100 scale, and exports a color-coded Excel workbook sorted by tier. A SQLite database tracks every lead across runs, suppresses recently-surfaced candidates to keep results fresh, and records outreach status so you never double-contact the same person.

---

## Quick Start — For New Users

This section walks you through setup from scratch and your first live search. It assumes you are on a Mac and have Python installed. You will only need to do steps 1–5 once.

### Step 1 — Open Terminal

Press **Command + Space**, type **Terminal**, and press Enter. A black or white window with a blinking cursor will open.

### Step 2 — Navigate to the project folder

Type the following and press Enter (replace the path if you saved the project somewhere else):

```
cd ~/lead-finder
```

If you are not sure where the folder is, type `cd ` (with a space after it), then drag the lead-finder folder from Finder into the Terminal window. The path will fill in automatically. Press Enter.

### Step 3 — Run the one-time setup script

```
./scripts/setup_local.sh
```

This will take about 2 minutes. It creates a private Python environment, installs all the software the tool needs, and creates a `.env` file for your API keys. You will see a message at the end that says **Setup complete.**

You only need to do this once. If you get a "permission denied" error, run `chmod +x scripts/setup_local.sh` first, then try again.

### Step 4 — Add your API keys

Open the `.env` file in any text editor (TextEdit works fine):

```
open -e .env
```

Fill in your Apollo key. The other keys are optional — leave them blank if you do not have them:

```
APOLLO_API_KEY=paste-your-key-here
CENSUS_API_KEY=paste-your-key-here
SEC_USER_AGENT=LeadPipeline/1.0 your-real-email@example.com
```

Save and close the file.

Then copy the config template and open it:

```
cp config/config.example.yaml config/config.yaml
open -e config/config.yaml
```

In `config/config.yaml`, find the `targeting:` section near the top and set the states you want to search:

```yaml
targeting:
  states: ["CT", "FL"]   # change to the states you want
```

Save and close.

### Step 5 — Verify everything is set up

```
./scripts/check_setup.sh
```

This runs a quick check of your keys and connectivity. Every line should say **OK**. If anything says **MISSING**, the message will tell you what to fix. The most common issue is a missing API key — go back to `.env` and fill it in.

### Step 6 — Run your first search

```
./scripts/run_founders.sh
```

This will take 30–90 seconds while it searches Apollo and processes results. When it finishes, a spreadsheet will open automatically. Each row is a lead. The **Hot** and **Warm** tabs are the ones to focus on first.

---

## Everyday Usage — For Non-Technical Users

You do not need to remember any commands. All day-to-day tasks have a simple script. Run everything from the lead-finder folder in Terminal.

### Finding leads

| What you want to do | Command to run |
|---|---|
| Find founders and company owners | `./scripts/run_founders.sh` |
| Find VC and PE professionals | `./scripts/run_vc_pe.sh` |
| Find C-suite executives | `./scripts/run_c_suite.sh` |

Each search fetches up to 100 leads from Apollo, scores them, saves them to the database, and opens the spreadsheet automatically when done. Run a different script each day to get variety — the tool automatically suppresses leads you have already seen in the last 30 days.

### Working with results

| What you want to do | Command to run |
|---|---|
| Open the most recent spreadsheet (without running a search) | `python -m lead_pipeline open-latest` |
| See which leads are worth revealing in Apollo and how many credits it will cost | `./scripts/prepare_reveal.sh` |
| See which search type is producing the best leads over time | `python -m lead_pipeline compare-profiles` |

### Updating lead status after outreach

After you contact leads, you can record the outcome so the tool tracks it. Create a CSV file (you can make one in Excel or Numbers) with two columns — `name` and `status`:

```
name,status
Jane Smith,contacted
Robert Chen,skipped
```

Valid status values: `new`, `revealed`, `contacted`, `skipped`, `converted`, `do_not_contact`

Then run:

```
python -m lead_pipeline import-feedback path/to/your-file.csv
```

To preview what would change without actually saving anything, add `--dry-run`:

```
python -m lead_pipeline import-feedback path/to/your-file.csv --dry-run
```

### Understanding the spreadsheet

| Column | What it means |
|---|---|
| `score_tier` | **Hot** (80–100), **Warm** (60–79), **Cool** (40–59), or **Skip** (below 40). Start with Hot and Warm. |
| `lead_score` | The 0–100 number behind the tier. Higher is better. |
| `lead_summary` | Plain-English summary of why this lead scored the way it did. |
| `next_action` | What to do next — e.g. "Reveal in Apollo – high priority" or "Skip – weak role". |
| `contact_reveal_priority` | `high`, `medium`, or `low` — how worthwhile it is to spend an Apollo credit to reveal this person's contact info. |
| `apollo_title` / `apollo_organization` | Their job title and company from Apollo. |
| `contact_quality` | `full` = email + phone ready. `partial` = one channel available. `none` = no contact info yet. |

---

## Troubleshooting — For Non-Technical Users

**"command not found" when running a script**

You need to activate the virtual environment first. Run:

```
source venv/bin/activate
```

Then try the script again. If you still get an error, run `./scripts/setup_local.sh` to rebuild the environment.

**"Permission denied" when running a script**

Make the script executable:

```
chmod +x scripts/run_founders.sh
```

**API key errors or "not configured" warnings**

Open `.env` and check that your keys are filled in with no extra spaces. Then run `./scripts/check_setup.sh` — it will tell you exactly which keys are missing.

**"No leads found" or very few results**

- Try a different profile: `./scripts/run_vc_pe.sh` instead of `./scripts/run_founders.sh`
- Your recent leads may be suppressed (30-day cooldown). Try again tomorrow or run with a different profile
- Check that your Apollo account is active and the key in `.env` is correct

**"SEC enrichment disabled" warning**

Open `.env` and make sure `SEC_USER_AGENT` contains a real email address, not `contact@example.com`. Change it to your actual email.

**Want to re-run the setup health check**

```
./scripts/check_setup.sh
```

or equivalently:

```
python -m lead_pipeline doctor --mode api
```

---

## Developer Reference

### All CLI commands

The entry point is `python -m lead_pipeline <command>`. All commands accept `--config <path>` to point at a non-default config file.

---

#### `run` — Generate leads

```
python -m lead_pipeline run [OPTIONS]
```

The main pipeline command. Fetches Apollo candidates, enriches with Census/SEC/ATTOM, scores, deduplicates, persists to SQLite, and writes an Excel workbook.

| Flag | Default | Description |
|---|---|---|
| `--mode` | `mock` | `mock` or `sample` = offline sample data only. `api` = real providers (Apollo, Census, SEC) with optional ATTOM. `strict-real` = requires all configured production providers. |
| `--profile` | _(none)_ | Apollo search profile. Overrides `config.yaml` title filters. See profiles below. |
| `--state` | _(none)_ | Two-letter state code to target (e.g. `CT`). |
| `--zip-codes` | _(none)_ | Comma-separated ZIP codes (e.g. `06830,06831`). |
| `--limit` | _(no limit)_ | Maximum number of leads to write to the workbook. |
| `--open` | _(off)_ | Open the generated workbook automatically when the run finishes. |
| `--output` | _(auto)_ | Custom path for the output `.xlsx` file. |
| `--no-persist` | _(off)_ | Skip SQLite persistence for this run. |
| `--config` | `config/config.yaml` | Path to a non-default YAML config. |

Examples:

```bash
# Quick offline test
python -m lead_pipeline run --mode mock

# Live search, founders profile, Connecticut, open when done
python -m lead_pipeline run --mode api --profile founders --state CT --open

# Live search with a lead cap
python -m lead_pipeline run --mode api --profile vc_pe --limit 50
```

---

#### `doctor` — Health check

```
python -m lead_pipeline doctor [--mode mock|api]
```

Checks Python version, all required imports, `.env`, config file, API key presence, directory structure, Apollo connectivity (live probe if key is set), and sample-mode runability. Use `--mode api` to see API-mode readiness. Exits with code 1 if anything is missing.

---

#### `smoke-test` — Offline end-to-end test

```
python -m lead_pipeline smoke-test
```

Runs a complete pipeline pass in mock mode using sample data, verifies leads are produced, and writes a temporary workbook. Use this after any code change to confirm nothing is broken without spending API credits.

---

#### `open-latest` — Open most recent workbook

```
python -m lead_pipeline open-latest
```

Finds the newest `.xlsx` in the configured output directory (and the `output/` fallback) and opens it with the OS default application. Equivalent to the `--open` flag on `run`, but can be called any time after a run.

---

#### `prepare-reveal` — Apollo credit planner

```
python -m lead_pipeline prepare-reveal [--min-score 45] [--limit 100]
```

Queries the SQLite database for leads that have not yet been revealed and shows a breakdown by reveal priority (high / medium / low) with an estimated Apollo credit cost. Leads with status `revealed` or `do_not_contact` are excluded automatically.

| Flag | Default | Description |
|---|---|---|
| `--min-score` | `45` | Minimum lead score to consider. |
| `--limit` | `100` | Maximum number of leads to display in the output. |

---

#### `compare-profiles` — Profile effectiveness table

```
python -m lead_pipeline compare-profiles
```

Reads the SQLite database and prints a table of Apollo search profile effectiveness: total leads, average score, and Hot/Warm/Cool/Skip counts per profile. Useful for deciding which profiles to run more often.

---

#### `import-feedback` — Record outreach outcomes

```
python -m lead_pipeline import-feedback <csv_path> [--dry-run]
```

Applies lead status updates from a CSV file to the SQLite database. Required CSV columns: `name`, `status`. Optional: `property_address` (to match precisely when names collide), `notes`.

Valid status values: `new`, `revealed`, `contacted`, `skipped`, `converted`, `do_not_contact`

The `--dry-run` flag previews changes without writing anything.

---

### Shell scripts

All scripts in `scripts/` require the `venv/` virtual environment to exist (run `./scripts/setup_local.sh` first). Each script prints the exact `python -m lead_pipeline` command it runs, so you can always see — and modify — what is happening.

| Script | Wraps | Description |
|---|---|---|
| `setup_local.sh` | _(setup)_ | One-time setup: creates venv, installs deps, copies `.env.example` to `.env`, creates data dirs. |
| `setup.sh` | _(setup)_ | Minimal setup script. Referenced by `make setup`. |
| `setup.ps1` | _(setup)_ | Windows PowerShell equivalent of `setup.sh`. |
| `check_setup.sh` | `doctor --mode api` | Verifies API-mode readiness: keys, connectivity, config. |
| `run_founders.sh` | `run --mode api --profile founders --limit 100 --open` | Live search for founders and company operators. |
| `run_vc_pe.sh` | `run --mode api --profile vc_pe --limit 100 --open` | Live search for VC and PE professionals. |
| `run_c_suite.sh` | `run --mode api --profile c_suite --limit 100 --open` | Live search for C-suite executives. |
| `prepare_reveal.sh` | `prepare-reveal` | Shows reveal candidates and credit cost estimate. |
| `test_apollo.py` | _(standalone)_ | Manual Apollo connectivity probe. Run with `python scripts/test_apollo.py`. Not a pytest test. |

**Makefile shortcuts:**

```bash
make setup       # → sh scripts/setup.sh
make doctor      # → python -m lead_pipeline doctor
make smoke-test  # → python -m lead_pipeline smoke-test
make test        # → pytest -q
make run         # → python -m lead_pipeline run --mode mock
```

---

### Apollo search profiles

Profiles live in [`lead_pipeline/utils/profiles.py`](lead_pipeline/utils/profiles.py). Pass any profile name via `--profile` on the `run` command or the shell scripts.

| Profile | Description | Employee range |
|---|---|---|
| `founders` | Founders and operators of private companies | 1–1,000 |
| `vc_pe` | Venture capital and private equity professionals | 1–200 |
| `c_suite` | C-level executives (CEO, CFO, CTO, COO, CIO, President, Chairman, Owner) | 5–500 |
| `family_office` | Family office and private wealth management professionals | 1–100 |
| `real_estate` | Real estate founders, developers, and investors | 1–500 |
| `healthcare` | Healthcare and biotech founders and executives | 1–500 |
| `broad_hnw` | Broad high-net-worth search across all investor/founder roles | 1–2,000 |

The base config's `excluded_organizations` and `excluded_titles` lists always apply regardless of which profile is active.

**To add a new profile:** add a `SearchProfile` entry to the `PROFILES` dict in [`lead_pipeline/utils/profiles.py`](lead_pipeline/utils/profiles.py):

```python
"my_profile": SearchProfile(
    name="my_profile",
    description="Short description",
    person_titles=("Title A", "Title B"),
    employee_count_min=1,
    employee_count_max=500,
),
```

Then run `./scripts/run_founders.sh` with `--profile my_profile` (or call `python -m lead_pipeline run --mode api --profile my_profile`) to use it.

---

### Project structure

```
lead-finder/
├── lead_pipeline/
│   ├── __main__.py              # Entry point: python -m lead_pipeline
│   ├── cli.py                   # All CLI commands (run, doctor, smoke-test, etc.)
│   ├── pipeline.py              # Pipeline orchestration (see flow below)
│   ├── models.py                # Lead dataclass and all output fields
│   ├── collectors/
│   │   ├── census.py            # Census Bureau ACS5 county-level queries
│   │   ├── property.py          # Property record collector (sample or real)
│   │   ├── business.py          # Business entity matcher (sample or OpenCorporates)
│   │   └── sec_edgar.py         # SEC EDGAR Form D matcher
│   ├── enrichment/
│   │   ├── apollo.py            # Apollo people search and contact reveal
│   │   ├── attom.py             # ATTOM property enrichment
│   │   └── phone.py             # Phone validation (NumVerify / AbstractAPI)
│   ├── scoring/
│   │   ├── scorer.py            # 0–100 lead scorer
│   │   └── signals.py           # Affinity signal detection (tech, investor, etc.)
│   ├── output/
│   │   └── excel.py             # Excel workbook exporter
│   └── utils/
│       ├── config.py            # Config dataclasses and loader
│       ├── database.py          # SQLite persistence layer
│       ├── dedupe.py            # Lead deduplication
│       ├── profiles.py          # Built-in Apollo search profiles
│       ├── logger.py            # Logger setup
│       └── rate_limiter.py      # API rate limiting
├── config/
│   ├── config.example.yaml      # Fully-documented template (commit this)
│   └── config.yaml              # Live config with real keys (gitignored)
├── data/
│   ├── input/                   # Optional: lead_addresses.csv for manual ATTOM lookups
│   ├── sample/                  # Mock CSVs used by sample/mock mode
│   │   ├── properties.csv
│   │   ├── business_entities.csv
│   │   ├── sec_matches.csv
│   │   └── contacts.csv
│   ├── output/                  # Generated Excel workbooks (gitignored)
│   ├── processed/               # SQLite database (gitignored)
│   └── raw/                     # ATTOM cache and intermediate data (gitignored)
├── docs/
│   └── SETUP_REQUIRED.md        # Detailed per-provider setup and compliance notes
├── scripts/                     # Shell script shortcuts (see table above)
├── tests/                       # pytest test suite
├── requirements.txt
├── pytest.ini
├── Makefile
├── .env.example                 # API key template — copy to .env
└── .gitignore
```

---

### How the pipeline works end-to-end

```
1. Apollo fetch
   └─ Loads previously-seen Apollo IDs from SQLite (cooldown filter)
   └─ Picks a search_rotation variant (or --profile override) randomly
   └─ Pages through Apollo mixed_people/api_search results
   └─ Filters by excluded_titles and excluded_organizations (client-side)
   └─ If all fresh IDs are suppressed → cooldown fallback (marked "recycled")
   └─ Saves new IDs to seen_apollo_candidates table

2. Census targeting
   └─ Queries ACS5 county-level data (income, home value, population)
   └─ Filters by configured states/ZIPs/metros
   └─ Returns target_areas list for property collection

3. Property collection
   └─ sample mode: reads data/sample/properties.csv
   └─ api mode: real adapter (ATTOM or county assessor — configure per area)

4. Business, SEC, phone enrichment (per property-record lead)
   └─ Business: sample CSV or OpenCorporates
   └─ SEC: EDGAR full-text search for Form D filings (3 retries, exponential backoff)
   └─ Phone: sample CSV or NumVerify / AbstractAPI

5. Apollo leads merged into the same lead list

6. Deduplication
   └─ Deduplicates by configured dedup_by fields (default: ["name"])

7. ATTOM enrichment
   └─ Runs against leads that have a street address
   └─ Leads missing address are flagged address_needed; not sent to ATTOM
   └─ Matches by name+address; min_match_confidence threshold filters weak matches
   └─ Optionally reads data/input/lead_addresses.csv to supply addresses for Apollo leads

8. Scoring (0–100)
   └─ property_value (30 pts max)
   └─ multi_property (10 pts)
   └─ business_ownership (25 pts)
   └─ sec_filing_match (10 pts)
   └─ area_wealth_index (10 pts)
   └─ phone_reachability (10 pts)
   └─ recency_signal (5 pts)
   └─ affinity_bonuses (small optional bonus from inferred signal tags)
   └─ Tier: Hot ≥ 80, Warm ≥ 60, Cool ≥ 40, Skip < 40

9. Sort by score descending, apply --limit if set

10. SQLite persistence
    └─ Upserts leads into `leads` table
    └─ Preserves existing statuses (contacted/revealed/converted/etc.) on re-runs
    └─ Auto-migrates schema when new columns are added

11. Excel export
    └─ Writes data/output/investor_leads_<timestamp>.xlsx
    └─ Sheets: All Leads + Hot, Warm, Cool, Skip tabs
    └─ Color-coded by tier
    └─ Cleans up old workbooks per keep_last_n_workbooks setting
```

---

### Database

**Location:** `data/processed/prospects.db` (default; configurable via `pipeline.database_path` in `config.yaml`)

**Tables:**

- **`leads`** — Every scored lead across all runs. Key columns: `name`, `property_address` (composite unique key), `lead_score`, `score_tier`, `lead_status`, `status_updated_at`, `status_notes`, `apollo_search_profile`, `payload` (full JSON of all lead fields), `updated_at`.

- **`seen_apollo_candidates`** — Apollo person IDs that have been surfaced. Used to suppress repeats for `seen_ids_cooldown_days` days. Key columns: `person_id`, `organization`, `title`, `surfaced_at`.

**Lead statuses:** `new` → `revealed` → `contacted` → `converted` or `skipped` or `do_not_contact`

Statuses set to `contacted`, `revealed`, `converted`, `do_not_contact`, or `skipped` are preserved across pipeline re-runs (not overwritten by a fresh search result).

---

### Running the test suite

```bash
pytest -q          # full suite
make test          # same via Makefile
make smoke-test    # standalone end-to-end offline run
```

Tests use mocked providers — no live API calls. `scripts/test_apollo.py` is a separate manual probe for live Apollo connectivity (not part of the test suite).

---

## Setup & Config Details

### API keys — what each one is for

| Key | Where to get it | Required? |
|---|---|---|
| `APOLLO_API_KEY` | Apollo account → Settings → API | **Required** for live lead searches |
| `CENSUS_API_KEY` | [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html) | Recommended for API mode; free |
| `SEC_USER_AGENT` | No account — set to `YourApp/1.0 your@email.com` | Required for SEC EDGAR enrichment; must be a real email |
| `ATTOM_API_KEY` | [api.gateway.attomdata.com](https://api.gateway.attomdata.com) | Optional; paid per record |
| `OPENCORPORATES_API_KEY` | [opencorporates.com/api_accounts/new](https://opencorporates.com/api_accounts/new) | Optional; free tier available |
| `NUMVERIFY_API_KEY` | [numverify.com](https://numverify.com) | Optional; free tier (100/mo) |
| `ABSTRACT_PHONE_API_KEY` | [abstractapi.com](https://www.abstractapi.com) | Optional; alternative to NumVerify |

Keys can be set in either `.env` or directly in `config/config.yaml` under `api_keys:`. `.env` values take precedence.

The pipeline runs in `mock`/`sample` mode without any keys. Only `APOLLO_API_KEY` is strictly required for live searches.

---

### Full `config.yaml` field reference

```yaml
api_keys:
  census: ""                    # Census Bureau API key (or use CENSUS_API_KEY env var)
  attom: ""                     # ATTOM API key (or ATTOM_API_KEY)
  opencorporates: ""            # OpenCorporates key (or OPENCORPORATES_API_KEY)
  sec_user_agent: "..."         # Must be a real email (or SEC_USER_AGENT)
  apollo: ""                    # Apollo API key (or APOLLO_API_KEY)
  numverify: ""                 # NumVerify key (or NUMVERIFY_API_KEY)
  abstractapi: ""               # Abstract API key (or ABSTRACT_PHONE_API_KEY)

targeting:
  states: ["CT", "FL"]         # Two-letter state codes to search
  metros: []                    # Metro area names (future use)
  counties: []                  # County names (future use)
  zip_codes: []                 # ZIP codes (can also pass via --zip-codes flag)
  census_tracts: []             # Census tract IDs (future use)
  min_median_income: 100000     # Minimum Census median household income to include an area
  min_median_home_value: 750000 # Minimum Census median home value to include an area
  min_property_value: 1500000   # Minimum individual property value to include a lead
  countries:                    # Server-side Apollo country filter. [] = no filter.
    - US

sources:
  mode: "sample"                # "sample" = offline mock data. "api" = real providers.
  sample_properties: "data/sample/properties.csv"
  sample_business_entities: "data/sample/business_entities.csv"
  sample_sec_matches: "data/sample/sec_matches.csv"
  sample_contacts: "data/sample/contacts.csv"

apollo:
  enabled: true
  per_page: 25                  # Results per Apollo API page (not the lead limit)
  max_pages: 5                  # Maximum pages to fetch per run
  reveal_contacts: false        # Set true only to spend Apollo reveal credits
  max_reveals_per_run: 0        # How many contacts to reveal per run (0 = none)
  employee_count_min: 5         # Server-side employee count lower bound
  employee_count_max: 500       # Server-side employee count upper bound
  random_page_offset_max: 10    # Randomise starting page for search diversity
  seen_ids_cooldown_days: 30    # Suppress Apollo IDs seen in the last N days (0 = forever)
  filters:
    person_titles: [...]        # Base title list (overridden by search_rotation or --profile)
  target_industries: [...]      # Informational only — not sent to Apollo as a filter
  excluded_titles: [...]        # Drop leads whose title contains these strings (client-side)
  excluded_titles_unless_containing:
    associate: [...]            # Keep "Associate" if title also contains one of these
  excluded_organizations: [...]  # Drop leads from these companies (substring, client-side)
  search_rotation: [...]        # List of named title-set variants; one picked randomly each run

attom:
  enabled: true
  max_requests_per_run: 25      # ATTOM API request cap per run (not a lead limit)
  min_match_confidence: 0.45    # Minimum address-match confidence to apply property data
  lead_addresses_path: "data/input/lead_addresses.csv"  # Optional manual address input

census:
  enabled: true

sec:
  enabled: true

scoring:
  weights:
    property_value: 30          # Max points from property value
    multi_property: 10          # Bonus for owning multiple properties
    business_ownership: 25      # Points for business entity match
    sec_filing_match: 10        # Points for SEC Form D match
    area_wealth_index: 10       # Points from Census area income/home-value
    phone_reachability: 10      # Points for valid, reachable phone
    recency_signal: 5           # Points for recent purchase or filing
  tiers:
    hot: 80                     # Hot if score >= 80
    warm: 60                    # Warm if score >= 60
    cool: 40                    # Cool if score >= 40
    skip: 0                     # Skip below 40
  affinity_bonuses:             # Small optional bonuses from inferred signal tags
    investor_aligned_tags: 3
    startup_ecosystem_tags: 2
    vc_pe_family_office_tags: 5

output:
  output_dir: "data/output"     # Where Excel workbooks are written
  filename_prefix: "investor_leads"
  separate_sheets_by_tier: true # Write Hot/Warm/Cool/Skip as separate tabs
  color_code_tiers: true        # Color rows by tier in the workbook
  keep_last_n_workbooks: 10     # Delete older workbooks after each run (0 = keep all)

pipeline:
  batch_size: 50
  retry_attempts: 3
  retry_delay_seconds: 2
  dedup_by: ["name"]            # Fields used to deduplicate leads across sources
  log_level: "INFO"
  database_path: "data/processed/prospects.db"
```

---

## License

Private — internal use only.
