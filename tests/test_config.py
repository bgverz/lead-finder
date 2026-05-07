from pathlib import Path

import pytest

from src.utils.config import load_config


def test_load_config_accepts_sample_config():
    config = load_config("config/config.example.yaml")

    assert config.sources.mode == "sample"
    assert config.scoring.weights.property_value == 30
    assert config.pipeline.dedup_by == ["name"]


def test_load_config_rejects_bad_weight_total(tmp_path: Path):
    config_file = tmp_path / "bad.yaml"
    config_file.write_text(
        """
scoring:
  weights:
    property_value: 1
    multi_property: 1
    business_ownership: 1
    sec_filing_match: 1
    area_wealth_index: 1
    phone_reachability: 1
    recency_signal: 1
"""
    )

    with pytest.raises(ValueError, match="sum to 100"):
        load_config(config_file)


def test_load_config_fills_blank_api_keys_from_env(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
api_keys:
  census: ""
"""
    )
    monkeypatch.setenv("CENSUS_API_KEY", "env-census-key")

    config = load_config(config_file)

    assert config.api_keys.census == "env-census-key"


def test_load_config_env_overrides_placeholder_sec_user_agent(tmp_path: Path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
api_keys:
  sec_user_agent: "InvestorLeadPipeline/1.0 contact@example.com"
"""
    )
    monkeypatch.setenv("SEC_USER_AGENT", "InvestorLeadPipeline/1.0 ops@example.com")

    config = load_config(config_file)

    assert config.api_keys.sec_user_agent == "InvestorLeadPipeline/1.0 ops@example.com"
