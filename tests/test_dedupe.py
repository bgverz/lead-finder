from lead_pipeline.models import BusinessEntity, Lead
from lead_pipeline.utils.dedupe import deduplicate_leads


def test_deduplicate_leads_merges_by_name_and_counts_properties():
    leads = [
        Lead(
            name="Jordan Whitaker",
            property_value=4_250_000,
            property_address="12 Round Hill Road",
            business_entities=[BusinessEntity(name="Whitaker Capital", role="President")],
        ),
        Lead(
            name="Jordan Whitaker",
            property_value=3_100_000,
            property_address="20 Field Point Circle",
            sec_match=True,
        ),
    ]

    deduped = deduplicate_leads(leads, ["name"])

    assert len(deduped) == 1
    assert deduped[0].property_count == 2
    assert deduped[0].sec_match is True
    assert deduped[0].business_entity_names == ["Whitaker Capital"]
