from datetime import date

from src.models import BusinessEntity, Lead
from src.scoring.scorer import LeadScorer
from src.utils.config import load_config


def test_scorer_assigns_hot_lead():
    scorer = LeadScorer(load_config("config/config.example.yaml"))
    lead = Lead(
        name="Jordan Whitaker",
        property_value=3_500_000,
        property_address="12 Round Hill Road",
        area_income=175_000,
        property_count=2,
        business_entities=[
            BusinessEntity(
                name="Whitaker Capital Partners Inc",
                entity_type="Corporation",
                role="President",
                filing_date=date(2025, 2, 1),
            )
        ],
        sec_match=True,
        phone="+12035550101",
        phone_valid=True,
        phone_line_type="mobile",
    )

    scored = scorer.score(lead, as_of=date(2026, 4, 30))

    assert scored.lead_score == 100
    assert scored.score_tier == "Hot"


def test_tier_assignment_boundaries():
    scorer = LeadScorer(load_config("config/config.example.yaml"))

    assert scorer.assign_tier(80) == "Hot"
    assert scorer.assign_tier(79) == "Warm"
    assert scorer.assign_tier(60) == "Warm"
    assert scorer.assign_tier(59) == "Cool"
    assert scorer.assign_tier(40) == "Cool"
    assert scorer.assign_tier(39) == "Skip"
