from datetime import date

from lead_pipeline.models import BusinessEntity, Lead
from lead_pipeline.scoring.scorer import LeadScorer
from lead_pipeline.utils.config import load_config


def _scored_sample_lead() -> Lead:
    scorer = LeadScorer(load_config("config/config.example.yaml"))
    lead = Lead(
        name="Jordan Whitaker",
        property_value=4_250_000,
        property_address="12 Round Hill Road",
        area_income=178_000,
        property_count=2,
        business_entities=[
            BusinessEntity(
                name="Whitaker Capital Partners Inc",
                entity_type="Corporation",
                role="President",
                filing_date=date(2024, 2, 15),
            ),
            BusinessEntity(
                name="Round Hill Ventures LLC",
                entity_type="LLC",
                role="Managing Member",
                filing_date=date(2025, 5, 1),
            ),
        ],
        sec_match=True,
        sec_details=[
            {"company_name": "Round Hill Ventures Fund I LP", "filing_date": "2025-07-15", "form_type": "D"},
            {"company_name": "Whitaker Capital Partners Inc", "filing_date": "2024-06-03", "form_type": "D/A"},
        ],
        phone="+12035550101",
        phone_valid=True,
        phone_line_type="mobile",
    )
    return scorer.score(lead, as_of=date(2026, 4, 30))


def test_lead_summary_generation():
    lead = _scored_sample_lead()

    assert lead.lead_summary == (
        "Owns $4.25M property, linked to 2 business entities, "
        "appears in SEC filings, mobile reachable."
    )


def test_call_priority_assignment():
    hot_mobile = _scored_sample_lead()
    hot_landline = _scored_sample_lead()
    hot_landline.phone_line_type = "landline"
    warm_phone = Lead(
        name="Warm Lead",
        property_value=2_500_000,
        property_address="1 Main Street",
        lead_score=65,
        score_tier="Warm",
        phone="+12035550109",
        phone_valid=True,
        phone_line_type="landline",
    )
    cool = Lead(name="Cool Lead", property_value=1_600_000, property_address="2 Main", score_tier="Cool")
    skip = Lead(name="Skip Lead", property_value=900_000, property_address="3 Main", score_tier="Skip")

    assert hot_mobile.call_priority == "Call First"
    assert hot_landline.call_priority == "Research First"
    assert warm_phone.call_priority == "Call"
    assert cool.call_priority == "Low Priority"
    assert skip.call_priority == "Skip"


def test_data_confidence_assignment():
    assert _scored_sample_lead().data_confidence == "High"
    assert Lead(
        name="Medium Lead",
        property_value=2_000_000,
        property_address="1 Main",
        area_income=125_000,
    ).data_confidence == "Medium"
    assert Lead(name="Low Lead", property_value=2_000_000, property_address="1 Main").data_confidence == "Low"


def test_business_entity_parsing():
    lead = _scored_sample_lead()

    assert lead.entity_count == 2
    assert lead.entity_types == ["Corporation", "LLC"]
    assert lead.is_multi_entity_owner is True


def test_sec_detail_fields():
    lead = _scored_sample_lead()

    assert lead.sec_match_count == 2
    assert lead.sec_forms == ["D", "D/A"]
    assert lead.sec_recent_match is True
    assert lead.sec_last_filing_date == "2025-07-15"


def test_score_breakdown_fields_are_populated():
    lead = _scored_sample_lead()

    assert lead.property_score == 30
    assert lead.business_score == 35
    assert lead.sec_score == 10
    assert lead.area_score == 10
    assert lead.phone_score == 10
    assert lead.recency_score == 5
