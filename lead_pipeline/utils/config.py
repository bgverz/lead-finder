"""YAML configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

import yaml


@dataclass
class APIKeys:
    census: str = ""
    attom: str = ""
    opencorporates: str = ""
    sec_user_agent: str = "InvestorLeadPipeline/1.0 contact@example.com"
    apollo: str = ""
    numverify: str = ""
    abstractapi: str = ""


@dataclass
class TargetingConfig:
    states: list[str] = field(default_factory=list)
    metros: list[str] = field(default_factory=list)
    counties: list[str] = field(default_factory=list)
    zip_codes: list[str] = field(default_factory=list)
    census_tracts: list[str] = field(default_factory=list)
    min_median_income: int = 100_000
    min_median_home_value: int = 750_000
    min_property_value: int = 2_000_000
    # ISO 3166-1 alpha-2 country codes for Apollo server-side + client-side geo filter.
    # Defaults to US-only. Set to [] to disable country filtering.
    countries: list[str] = field(default_factory=lambda: ["US"])


@dataclass
class ScoringWeights:
    property_value: int = 30
    multi_property: int = 10
    business_ownership: int = 25
    sec_filing_match: int = 10
    area_wealth_index: int = 10
    phone_reachability: int = 10
    recency_signal: int = 5


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    tiers: dict[str, int] = field(
        default_factory=lambda: {"hot": 80, "warm": 60, "cool": 40, "skip": 0}
    )
    affinity_bonuses: dict[str, int] = field(
        default_factory=lambda: {
            "investor_aligned_tags": 0,
            "startup_ecosystem_tags": 0,
            "vc_pe_family_office_tags": 0,
        }
    )


@dataclass
class SignalsConfig:
    tech_keywords: list[str] = field(default_factory=list)
    investor_keywords: list[str] = field(default_factory=list)
    networking_keywords: list[str] = field(default_factory=list)
    real_estate_keywords: list[str] = field(default_factory=list)
    healthcare_keywords: list[str] = field(default_factory=list)


@dataclass
class SourcesConfig:
    mode: str = "sample"
    sample_properties: str = "data/sample/properties.csv"
    sample_business_entities: str = "data/sample/business_entities.csv"
    sample_sec_matches: str = "data/sample/sec_matches.csv"
    sample_contacts: str = "data/sample/contacts.csv"


@dataclass
class ApolloConfig:
    enabled: bool = False
    per_page: int = 5
    max_pages: int = 1
    reveal_contacts: bool = False
    max_reveals_per_run: int = 0
    # Web scraping fallback settings
    web_reveal_enabled: bool = False
    web_credentials: dict[str, str] = field(default_factory=dict)
    # Server-side filters sent directly to Apollo api_search payload.
    filters: dict[str, Any] = field(default_factory=dict)
    # Client-side title exclusions.
    excluded_titles: list[str] = field(default_factory=list)
    # Conditional override: keep a title that matches an excluded keyword if it
    # also contains one of these exception substrings.
    excluded_titles_unless_containing: dict[str, list[str]] = field(default_factory=dict)
    # Client-side: drop candidates whose organization name contains any of these
    # strings (case-insensitive substring match).
    excluded_organizations: list[str] = field(default_factory=list)
    # Server-side employee count filter (0 = no bound).
    employee_count_min: int = 0
    employee_count_max: int = 0
    # Soft industry targeting: keywords appended to q_keywords for industry signal.
    target_industries: list[str] = field(default_factory=list)
    # Randomise the starting page number (1..N) for run diversity. 0 = always page 1.
    random_page_offset_max: int = 0
    # Skip Apollo IDs already surfaced within this many days (0 = skip forever).
    seen_ids_cooldown_days: int = 30
    # List of filter-variant dicts; each is a partial payload override that is
    # randomly selected each run.  Keys matching Apollo api_search params are
    # merged over the base filters.  A "name" key is used only for logging.
    search_rotation: list[dict[str, Any]] = field(default_factory=list)
    # Active built-in profile name (set by --profile CLI flag).  Overrides
    # filters.person_titles and employee count bounds when non-empty.
    active_profile: str = ""


@dataclass
class ATTOMConfig:
    enabled: bool = True
    base_url: str = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
    cache_path: str = "data/raw/attom_cache.json"
    lead_addresses_path: str = "data/input/lead_addresses.csv"
    max_requests_per_run: int = 25
    request_delay_seconds: float = 0.35
    retry_attempts: int = 2
    retry_backoff_seconds: float = 1.0
    min_match_confidence: float = 0.45


@dataclass
class CensusConfig:
    enabled: bool = True


@dataclass
class SECConfig:
    enabled: bool = True


@dataclass
class PipelineConfig:
    batch_size: int = 50
    retry_attempts: int = 3
    retry_delay_seconds: int = 2
    dedup_by: list[str] = field(default_factory=lambda: ["name", "property_address"])
    log_level: str = "INFO"
    database_path: str = "data/processed/prospects.db"


@dataclass
class OutputConfig:
    output_dir: str = "data/output"
    filename_prefix: str = "investor_leads"
    separate_sheets_by_tier: bool = True
    color_code_tiers: bool = True
    keep_last_n_workbooks: int = 0  # 0 = keep all


@dataclass
class Config:
    api_keys: APIKeys = field(default_factory=APIKeys)
    targeting: TargetingConfig = field(default_factory=TargetingConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    signals: SignalsConfig = field(default_factory=SignalsConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    apollo: ApolloConfig = field(default_factory=ApolloConfig)
    attom: ATTOMConfig = field(default_factory=ATTOMConfig)
    census: CensusConfig = field(default_factory=CensusConfig)
    sec: SECConfig = field(default_factory=SECConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


ENV_KEY_MAP = {
    "census": ("CENSUS_API_KEY",),
    "attom": ("ATTOM_API_KEY",),
    "opencorporates": ("OPENCORPORATES_API_KEY", "OPENCORPORATES_API_TOKEN"),
    "sec_user_agent": ("SEC_USER_AGENT",),
    "apollo": ("APOLLO_API_KEY",),
    "numverify": ("NUMVERIFY_API_KEY",),
    "abstractapi": ("ABSTRACT_PHONE_API_KEY", "ABSTRACT_API_KEY"),
}


def _filter_fields(cls: type, values: dict[str, Any]) -> dict[str, Any]:
    allowed = set(cls.__dataclass_fields__.keys())
    return {key: value for key, value in values.items() if key in allowed}


def load_config(config_path: str | Path) -> Config:
    """Load a YAML config file into typed config objects."""

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml first."
        )

    raw = yaml.safe_load(path.read_text()) or {}
    raw_api_keys = _apply_env_api_keys(raw.get("api_keys", {}) or {})
    scoring_raw = raw.get("scoring", {}) or {}

    config = Config(
        api_keys=APIKeys(**_filter_fields(APIKeys, raw_api_keys)),
        targeting=TargetingConfig(
            **_filter_fields(TargetingConfig, raw.get("targeting", {}) or {})
        ),
        scoring=ScoringConfig(
            weights=ScoringWeights(
                **_filter_fields(ScoringWeights, scoring_raw.get("weights", {}) or {})
            ),
            tiers=scoring_raw.get(
                "tiers", {"hot": 80, "warm": 60, "cool": 40, "skip": 0}
            ),
            affinity_bonuses=scoring_raw.get(
                "affinity_bonuses",
                {
                    "investor_aligned_tags": 0,
                    "startup_ecosystem_tags": 0,
                    "vc_pe_family_office_tags": 0,
                },
            ),
        ),
        signals=SignalsConfig(**_filter_fields(SignalsConfig, raw.get("signals", {}) or {})),
        sources=SourcesConfig(**_filter_fields(SourcesConfig, raw.get("sources", {}) or {})),
        apollo=ApolloConfig(**_filter_fields(ApolloConfig, raw.get("apollo", {}) or {})),
        attom=ATTOMConfig(**_filter_fields(ATTOMConfig, raw.get("attom", {}) or {})),
        census=CensusConfig(**_filter_fields(CensusConfig, raw.get("census", {}) or {})),
        sec=SECConfig(**_filter_fields(SECConfig, raw.get("sec", {}) or {})),
        pipeline=PipelineConfig(
            **_filter_fields(PipelineConfig, raw.get("pipeline", {}) or {})
        ),
        output=OutputConfig(**_filter_fields(OutputConfig, raw.get("output", {}) or {})),
    )
    validate_config(config)
    return config


def _apply_env_api_keys(api_keys: dict[str, Any]) -> dict[str, Any]:
    """Fill blank API key config values from documented environment variables."""

    merged = dict(api_keys)
    for field_name, env_names in ENV_KEY_MAP.items():
        for env_name in env_names:
            env_value = os.getenv(env_name)
            if env_value and (
                not merged.get(field_name)
                or (
                    field_name == "sec_user_agent"
                    and "contact@example.com" in str(merged.get(field_name))
                )
            ):
                merged[field_name] = env_value
                break
    return merged


def validate_config(config: Config) -> None:
    """Validate cross-field constraints that should fail clearly."""

    weights = config.scoring.weights
    total = sum(getattr(weights, field_name) for field_name in weights.__dataclass_fields__)
    if total != 100:
        raise ValueError(f"Scoring weights must sum to 100, got {total}")

    tiers = config.scoring.tiers
    for key in ("hot", "warm", "cool", "skip"):
        if key not in tiers:
            raise ValueError(f"Missing scoring tier threshold: {key}")

    if config.sources.mode not in {"sample", "api"}:
        raise ValueError("sources.mode must be either 'sample' or 'api'")

    if config.targeting.min_property_value < 0:
        raise ValueError("targeting.min_property_value cannot be negative")


def missing_real_data_setup(config: Config) -> list[str]:
    """Return setup actions needed before switching from sample data to real data."""

    missing: list[str] = []
    if not config.api_keys.census:
        missing.append("Census API key: set api_keys.census or CENSUS_API_KEY")
    if not config.api_keys.attom:
        missing.append("Property data provider key: set api_keys.attom or ATTOM_API_KEY")
    if not config.api_keys.opencorporates:
        missing.append(
            "OpenCorporates token: set api_keys.opencorporates or OPENCORPORATES_API_KEY"
        )
    if "contact@example.com" in config.api_keys.sec_user_agent:
        missing.append(
            "SEC EDGAR User-Agent contact: set api_keys.sec_user_agent or SEC_USER_AGENT"
        )
    if not config.api_keys.numverify and not config.api_keys.abstractapi:
        missing.append(
            "Phone validation key: set api_keys.numverify/NUMVERIFY_API_KEY "
            "or api_keys.abstractapi/ABSTRACT_PHONE_API_KEY"
        )
    if not config.targeting.counties and not config.targeting.metros:
        missing.append(
            "County/state portal selection: choose target counties or metros for assessor/SOS adapters"
        )
    return missing


def missing_api_mode_setup(config: Config) -> list[str]:
    """Return only blockers for partial-real API mode."""

    missing: list[str] = []
    if config.apollo.enabled and not config.api_keys.apollo:
        missing.append("Apollo API key: set api_keys.apollo or APOLLO_API_KEY")
    if config.census.enabled and not config.api_keys.census:
        missing.append("Census API key: set api_keys.census or CENSUS_API_KEY")
    return missing


def optional_api_mode_warnings(config: Config) -> list[str]:
    """Return unavailable optional providers for partial-real API mode."""

    warnings: list[str] = []
    if not config.api_keys.attom:
        warnings.append("ATTOM/property provider unavailable; continuing without property records")
    if not config.api_keys.opencorporates:
        warnings.append(
            "OpenCorporates/state business provider unavailable; continuing without business matching"
        )
    if not config.api_keys.numverify and not config.api_keys.abstractapi:
        warnings.append("Phone validation provider unavailable; obfuscated/missing phones score 0")
    if config.sec.enabled and "contact@example.com" in config.api_keys.sec_user_agent:
        warnings.append("SEC EDGAR User-Agent not configured; SEC enrichment will be skipped")
    return warnings
