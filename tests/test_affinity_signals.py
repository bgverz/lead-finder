from src.models import Lead
from src.scoring.scorer import LeadScorer
from src.scoring.signals import apply_affinity_signals
from src.utils.config import load_config


def test_affinity_signals_generate_tags_from_apollo_metadata():
    config = load_config("config/config.example.yaml")
    lead = Lead(
        name="Avery S.",
        property_value=0,
        property_address="",
        apollo_person_id="person-1",
        apollo_title="Founder and Managing Partner",
        apollo_organization="Example AI Ventures Family Office",
        apollo_industry="Venture Capital",
    )

    apply_affinity_signals(lead, config)

    assert "AI/Tech" in lead.interest_tags
    assert "Venture Capital" in lead.interest_tags
    assert "Family Office" in lead.interest_tags
    assert "Startup Ecosystem" in lead.interest_tags
    assert lead.tech_signal is True
    assert lead.investor_signal is True
    assert lead.networking_signal is True


def test_affinity_score_bonus_is_configurable():
    config = load_config("config/config.example.yaml")
    lead = Lead(
        name="Avery S.",
        property_value=0,
        property_address="",
        apollo_person_id="person-1",
        apollo_title="Founder",
        apollo_organization="Example Ventures Family Office",
        apollo_industry="Venture Capital",
    )

    LeadScorer(config).score(lead)

    expected_bonus = (
        config.scoring.affinity_bonuses["investor_aligned_tags"]
        + config.scoring.affinity_bonuses["startup_ecosystem_tags"]
        + config.scoring.affinity_bonuses["vc_pe_family_office_tags"]
    )
    assert lead.affinity_score == expected_bonus
    assert lead.lead_score >= lead.affinity_score
