from lead_pipeline.cli import apply_mode, setup_blockers, setup_warnings
from src.pipeline import _safe_error
from src.utils.config import load_config


def test_api_mode_does_not_block_on_attom_or_opencorporates():
    config = load_config("config/config.example.yaml")
    apply_mode(config, "api")
    config.api_keys.apollo = "apollo-key"
    config.api_keys.census = "census-key"
    config.api_keys.sec_user_agent = "InvestorLeadPipeline/1.0 ops@example.com"
    config.api_keys.attom = ""
    config.api_keys.opencorporates = ""

    assert setup_blockers(config, "api") == []
    warnings = setup_warnings(config, "api")
    assert any("ATTOM" in warning for warning in warnings)
    assert any("OpenCorporates" in warning for warning in warnings)


def test_strict_real_blocks_on_missing_production_providers():
    config = load_config("config/config.example.yaml")
    apply_mode(config, "strict-real")
    config.api_keys.apollo = "apollo-key"
    config.api_keys.census = "census-key"
    config.api_keys.sec_user_agent = "InvestorLeadPipeline/1.0 ops@example.com"
    config.api_keys.attom = ""
    config.api_keys.opencorporates = ""

    blockers = setup_blockers(config, "strict-real")

    assert any("ATTOM" in blocker or "Property" in blocker for blocker in blockers)
    assert any("OpenCorporates" in blocker for blocker in blockers)


def test_safe_error_redacts_query_keys():
    message = _safe_error(
        RuntimeError(
            "400 for url: https://api.census.gov/data?get=NAME&key=secret-value&for=zip:*"
        )
    )

    assert "secret-value" not in message
    assert "key=REDACTED" in message
