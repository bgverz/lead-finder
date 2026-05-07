# Setup Required Before Real API Integrations

This project runs end-to-end in `sources.mode: sample` with no external credentials. Before switching to real data, create the accounts and confirm the compliance items below.

## Credential Storage

You can store credentials either in `config/config.yaml` or as environment variables. Environment variables fill blank YAML values automatically.

| Purpose | Config field | Environment variable |
| --- | --- | --- |
| Census Bureau API | `api_keys.census` | `CENSUS_API_KEY` |
| ATTOM/property data API | `api_keys.attom` | `ATTOM_API_KEY` |
| OpenCorporates | `api_keys.opencorporates` | `OPENCORPORATES_API_KEY` |
| SEC EDGAR User-Agent | `api_keys.sec_user_agent` | `SEC_USER_AGENT` |
| Apollo.io | `api_keys.apollo` | `APOLLO_API_KEY` |
| NumVerify | `api_keys.numverify` | `NUMVERIFY_API_KEY` |
| Abstract API phone validation | `api_keys.abstractapi` | `ABSTRACT_PHONE_API_KEY` |

Do not commit real credentials. `config/config.yaml`, `data/output/`, and local databases are ignored by git.

## Data Sources

### US Census Bureau API

- Purpose: Geographic targeting by ZIP/ZCTA, tract, state, income, home value, and population.
- Signup URL placeholder: `https://api.census.gov/data/key_signup.html`
- Required credentials: Census API key. Some low-volume calls may work without a key, but real runs should use one.
- Expected config field: `api_keys.census`
- Environment variable: `CENSUS_API_KEY`
- Cost: Free.
- Optional or required: Optional for sample mode; recommended/required for reliable real Census API runs.
- Fallback if missing: Sample mode uses local CSV property rows and does not call Census. API mode attempts keyless Census calls where supported.

### County Assessor / County GIS Portals

- Purpose: Public property ownership, parcel data, assessed value, sale date, and tax information.
- Signup URL placeholder: County-specific. Examples: county assessor, GIS, parcel search, tax collector, recorder portals.
- Required credentials: Varies by county. Some portals are public; some require account approval, API keys, bulk-data agreements, or manual downloads.
- Expected config field: Not yet implemented as a single field; choose `targeting.counties`, `targeting.metros`, or `targeting.states` first so county adapters can be built intentionally.
- Environment variable: None yet; county-specific adapters should define their own names only after a portal is chosen.
- Cost: Usually free public records; some counties charge for bulk exports or API access.
- Optional or required: Required for real free-public-record property collection if not using ATTOM.
- Fallback if missing: Sample mode reads `data/sample/properties.csv`. API mode currently raises a clear setup error for property data if no provider is configured.

### County Recorder / Deed Transfer Portals

- Purpose: Purchase dates, deed transfers, mortgage amounts, liens, and recency signals.
- Signup URL placeholder: County-specific recorder or clerk portal.
- Required credentials: Varies by county.
- Expected config field: Future county-specific adapter fields.
- Environment variable: Future county-specific names.
- Cost: Usually free search; documents or bulk exports may cost money.
- Optional or required: Optional enrichment source; property records can still run without recorder data.
- Fallback if missing: Recency can come from sample data, ATTOM-style property data, or business filing dates.

### ATTOM Data API

- Purpose: Paid property data provider for assessed values, owner names, sale history, equity estimates, and neighborhood statistics.
- Signup URL placeholder: `https://api.gateway.attomdata.com/`
- Required credentials: ATTOM API key.
- Expected config field: `api_keys.attom`
- Environment variable: `ATTOM_API_KEY`
- Cost: Paid, commonly per-record or tiered.
- Optional or required: Optional if county public portals are used; required for the current real property adapter path.
- Fallback if missing: Sample mode reads `data/sample/properties.csv`. Real API mode prints/raises that `api_keys.attom` or `ATTOM_API_KEY` is missing.

### State Secretary of State / Corporation Records

- Purpose: Business ownership, officer, manager, member, registered agent, entity type, and filing date signals.
- Signup URL placeholder: State-specific SOS business search or bulk data portal.
- Required credentials: Varies by state. Many searches are free; bulk/API access may require accounts or agreements.
- Expected config field: Future state-specific adapter fields, plus `targeting.states`.
- Environment variable: Future state-specific names.
- Cost: Usually free for search; bulk/API access varies.
- Optional or required: Required for real state-specific business ownership enrichment; optional if using OpenCorporates only.
- Fallback if missing: Sample mode reads `data/sample/business_entities.csv`.

### OpenCorporates

- Purpose: Business entity and officer matching across public company registries.
- Signup URL placeholder: `https://opencorporates.com/api_accounts/new`
- Required credentials: API token for reliable/high-volume use.
- Expected config field: `api_keys.opencorporates`
- Environment variable: `OPENCORPORATES_API_KEY`
- Cost: Free tier available; paid plans for higher usage.
- Optional or required: Optional enrichment source; recommended for real business matching.
- Fallback if missing: Sample mode reads `data/sample/business_entities.csv`. Real business adapter is not implemented yet and will fail clearly before making assumptions.

### SEC EDGAR

- Purpose: Form D, disclosure, issuer, officer/director, Schedule 13D/G, and proxy statement matching.
- Signup URL placeholder: No account required. SEC fair-access guidance applies: `https://www.sec.gov/os/accessing-edgar-data`
- Required credentials: No API key, but a descriptive User-Agent with contact info is required.
- Expected config field: `api_keys.sec_user_agent`
- Environment variable: `SEC_USER_AGENT`
- Cost: Free.
- Optional or required: Required for polite real EDGAR API access; optional in sample mode.
- Fallback if missing: Sample mode reads `data/sample/sec_matches.csv`. If still set to the placeholder contact, the CLI warns that real EDGAR setup is incomplete.

### Apollo.io

- Purpose: Optional work email, title, company, LinkedIn, seniority, and additional phone enrichment.
- Signup URL placeholder: `https://www.apollo.io/`
- Required credentials: Apollo API key from an active Apollo account.
- Expected config field: `api_keys.apollo`
- Environment variable: `APOLLO_API_KEY`
- Cost: Paid or plan-dependent.
- Optional or required: Optional. The core lead score can run without Apollo.
- Fallback if missing: Current adapter returns `apollo_missing_key`; sample mode uses `data/sample/contacts.csv`.

### NumVerify

- Purpose: Phone validation, active/inactive signal, and mobile vs. landline classification.
- Signup URL placeholder: `https://numverify.com/`
- Required credentials: NumVerify API key.
- Expected config field: `api_keys.numverify`
- Environment variable: `NUMVERIFY_API_KEY`
- Cost: Free tier plus paid tiers.
- Optional or required: Optional, but required for real phone reachability scoring if Abstract API is not used.
- Fallback if missing: Sample mode reads `data/sample/contacts.csv`. Real phone validation returns a missing-key marker if called without credentials.

### Abstract API Phone Validation

- Purpose: Alternative phone validation provider for line type and reachability.
- Signup URL placeholder: `https://www.abstractapi.com/phone-validation-api`
- Required credentials: Abstract API key.
- Expected config field: `api_keys.abstractapi`
- Environment variable: `ABSTRACT_PHONE_API_KEY`
- Cost: Free tier plus paid tiers.
- Optional or required: Optional alternative to NumVerify.
- Fallback if missing: If both NumVerify and Abstract API are missing, real phone validation setup is incomplete. Sample mode still works.

### IRS SOI Tax Stats

- Purpose: Optional ZIP-level income distribution and AGI bracket enrichment.
- Signup URL placeholder: `https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi`
- Required credentials: Usually none for public downloads.
- Expected config field: Future optional source path or download URL.
- Environment variable: None expected.
- Cost: Free.
- Optional or required: Optional future geographic enrichment.
- Fallback if missing: Census income and sample area income fields are enough for the current pipeline.

### BLS / FRED

- Purpose: Optional metro-level employment, wage, and economic context.
- Signup URL placeholder: `https://fred.stlouisfed.org/docs/api/api_key.html` or BLS public data docs.
- Required credentials: FRED API key if using FRED API; BLS may allow limited keyless access.
- Expected config field: Future optional economic-data fields.
- Environment variable: Future names such as `FRED_API_KEY` only if implemented.
- Cost: Free.
- Optional or required: Optional future geographic enrichment.
- Fallback if missing: Not used by the current pipeline.

## Manual County/State Choices Needed

Before real property and state business integrations, choose:

- Target states, metros, counties, ZIP codes, or census tracts.
- Which property source to use per area: county assessor/GIS, county recorder, ATTOM, or another licensed provider.
- Which state SOS portals are allowed for automated lookup, bulk download, or API use.
- Whether each county/state source allows automated access, has rate limits, requires an account, or requires manual export.
- Whether the sales team wants only individuals, trusts, LLC-owned properties, or all owner types.

Add the target geography to `targeting.states`, `targeting.counties`, `targeting.metros`, `targeting.zip_codes`, or CLI options after the choices are made.

## Legal, ToS, and Compliance Checks

Confirm these before production use:

- Only use public records, licensed APIs, or datasets whose terms allow this business purpose.
- Do not scrape people-search sites or any website whose Terms of Service prohibit automated collection.
- Review county/state portal ToS, robots/rate-limit guidance, and bulk-data restrictions.
- Confirm SEC EDGAR fair-access requirements and use a real contact in `SEC_USER_AGENT`.
- Confirm Apollo, ATTOM, OpenCorporates, NumVerify, and Abstract API terms permit lead generation and commercial sales workflows.
- Confirm phone/email outreach complies with TCPA, CAN-SPAM, state privacy laws, internal securities-sales policies, and any broker-dealer compliance requirements.
- Treat PII minimally: store only fields needed for lead scoring and outreach, restrict access to generated Excel files, and avoid committing output files.
- Have counsel/compliance review scoring and outreach language before using generated leads for securities sales.

## What Runs Without Credentials

`sources.mode: sample` runs all core pipeline stages without external accounts:

- Geographic targeting uses configured states/ZIPs and sample rows.
- Property records come from `data/sample/properties.csv`.
- Business ownership matches come from `data/sample/business_entities.csv`.
- SEC matches come from `data/sample/sec_matches.csv`.
- Phone/contact validation comes from `data/sample/contacts.csv`.
- Scoring, deduplication, SQLite persistence, and Excel export all run locally.

The app prints a message that sample mode is active and lists the missing real-data setup items.

## Commands After Adding Credentials

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Copy and edit the config:

```bash
cp config/config.example.yaml config/config.yaml
```

Option A: add credentials to your shell environment:

```bash
export CENSUS_API_KEY="..."
export ATTOM_API_KEY="..."
export OPENCORPORATES_API_KEY="..."
export SEC_USER_AGENT="InvestorLeadPipeline/1.0 your-email@example.com"
export APOLLO_API_KEY="..."
export NUMVERIFY_API_KEY="..."
export ABSTRACT_PHONE_API_KEY="..."
```

Option B: add credentials directly to `config/config.yaml` under `api_keys`.

Run sample mode before using any real APIs:

```bash
python -m src.main --config config/config.yaml
pytest -q
```

Run a targeted sample ZIP test:

```bash
python -m src.main --config config/config.yaml --zip-codes 06830,06831
```

When real integrations are implemented and credentials are present, switch:

```yaml
sources:
  mode: "api"
```

Then run:

```bash
python -m src.main --config config/config.yaml --state CT
```

If setup is incomplete, the CLI prints the missing account, key, or manual county/state choice before the pipeline reaches provider-specific code.
