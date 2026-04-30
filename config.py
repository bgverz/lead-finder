"""Configuration loader for the pipeline."""

import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class APIKeys:
    apollo: str = ""
    census: str = ""
    attom: str = ""
    opencorporates: str = ""
    numverify: str = ""


@dataclass
class TargetingConfig:
    states: list[str] = field(default_factory=lambda: ["CT", "NY", "CA"])
    min_median_income: int = 120_000
    min_median_home_value: int = 750_000
    min_property_value: int = 2_000_000


@dataclass
class ScoringWeights:
    property_value: int = 25
    multi_property: int = 8
    business_ownership: int = 20
    sec_filing_match: int = 15
    apollo_title_seniority: int = 10
    apollo_company_revenue: int = 7
    area_wealth_index: int = 5
    phone_reachability: int = 5
    recency_signal: int = 5


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    property_brackets: list[dict] = field(default_factory=list)
    title_scores: dict = field(default_factory=dict)
    tiers: dict = field(default_factory=lambda: {
        "hot": 80, "warm": 60, "cool": 40, "skip": 0
    })


@dataclass
class PipelineConfig:
    batch_size: int = 50
    max_concurrent_requests: int = 5
    retry_attempts: int = 3
    retry_delay_seconds: int = 2
    dedup_by: list[str] = field(default_factory=lambda: ["name", "address"])
    log_level: str = "INFO"


@dataclass
class Config:
    api_keys: APIKeys = field(default_factory=APIKeys)
    targeting: TargetingConfig = field(default_factory=TargetingConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    output_dir: str = "data/output"


def load_config(config_path: str | Path) -> Config:
    """Load and validate configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Copy config/config.example.yaml to config/config.yaml and fill in your API keys."
        )

    with open(path) as f:
        raw = yaml.safe_load(f)

    # Build config objects
    api_keys = APIKeys(**raw.get("api_keys", {}))
    targeting = TargetingConfig(**raw.get("targeting", {}))

    scoring_raw = raw.get("scoring", {})
    weights = ScoringWeights(**scoring_raw.get("weights", {}))
    scoring = ScoringConfig(
        weights=weights,
        property_brackets=scoring_raw.get("property_brackets", []),
        title_scores=scoring_raw.get("title_scores", {}),
        tiers=scoring_raw.get("tiers", {"hot": 80, "warm": 60, "cool": 40, "skip": 0}),
    )

    pipeline = PipelineConfig(**raw.get("pipeline", {}))
    output_dir = raw.get("output", {}).get("output_dir", "data/output")

    config = Config(
        api_keys=api_keys,
        targeting=targeting,
        scoring=scoring,
        pipeline=pipeline,
        output_dir=output_dir,
    )

    _validate_config(config)
    return config


def _validate_config(config: Config):
    """Validate that scoring weights sum to 100 and required keys are present."""
    w = config.scoring.weights
    total = (
        w.property_value + w.multi_property + w.business_ownership +
        w.sec_filing_match + w.apollo_title_seniority + w.apollo_company_revenue +
        w.area_wealth_index + w.phone_reachability + w.recency_signal
    )
    if total != 100:
        raise ValueError(f"Scoring weights must sum to 100, got {total}")

    # Warn about missing API keys (don't error — some modules work without them)
    missing = []
    if not config.api_keys.census:
        missing.append("census")
    if not config.api_keys.apollo:
        missing.append("apollo")
    if missing:
        import logging
        logging.warning(f"Missing API keys: {', '.join(missing)}. Some modules will be limited.")