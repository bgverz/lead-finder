from types import SimpleNamespace

from src.enrichment.attom import ATTOMClient
from src.models import Lead
from src.pipeline import LeadPipeline
from src.scoring.scorer import LeadScorer
from src.utils.config import load_config


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


def _attom_payload(value=3_250_000, owner="Avery Stone"):
    return {
        "property": [
            {
                "address": {
                    "line1": "12 Round Hill Road",
                    "locality": "Greenwich",
                    "countrySubd": "CT",
                    "postal1": "06831",
                },
                "avm": {"amount": {"value": value}},
                "assessment": {"assessed": {"assdttlvalue": 2_850_000}},
                "building": {"summary": {"proptype": "Single Family Residence"}},
                "owner": {"owner1": {"fullName": owner}, "propertycount": 2},
            }
        ]
    }


def test_attom_address_lookup_uses_apikey_header_and_maps_fields(monkeypatch, tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    captured = {}

    def fake_get(url, headers, params, timeout):
        captured.update({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return FakeResponse(_attom_payload())

    monkeypatch.setattr("src.enrichment.attom.requests.get", fake_get)
    client = ATTOMClient(config)
    lead = Lead(name="Avery Stone", property_value=0, property_address="12 Round Hill Road")

    match = client.lookup_address("12 Round Hill Road", "Greenwich, CT", lead)

    assert captured["url"].endswith("/property/address")
    assert captured["headers"]["APIKey"] == "attom-key"
    assert captured["params"] == {"address1": "12 Round Hill Road", "address2": "Greenwich, CT"}
    assert match.estimated_value == 3_250_000
    assert match.assessed_value == 2_850_000
    assert match.property_type == "Single Family Residence"
    assert match.owner_name == "Avery Stone"
    assert match.confidence >= 0.7


def test_attom_enrichment_updates_lead_and_scoring(monkeypatch, tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    monkeypatch.setattr(
        "src.enrichment.attom.requests.get",
        lambda url, headers, params, timeout: FakeResponse(_attom_payload()),
    )
    lead = Lead(
        name="Avery Stone",
        property_value=0,
        property_address="12 Round Hill Road",
        city="Greenwich",
        state="CT",
        apollo_person_id="p1",
        apollo_title="Founder",
    )

    ATTOMClient(config).enrich_leads([lead])
    LeadScorer(config).score(lead)

    assert lead.property_estimated_value == 3_250_000
    assert lead.property_assessed_value == 2_850_000
    assert lead.property_match_confidence >= 0.7
    assert "high-value" in lead.property_signal.lower() or "luxury" in lead.property_signal.lower()
    assert lead.property_score >= config.scoring.weights.property_value
    assert "matched high-value property" in lead.lead_summary.lower()


def test_attom_skips_leads_without_address(tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    lead = Lead(name="No Address", property_value=0, property_address="")

    client = ATTOMClient(config)
    client.enrich_leads([lead])

    assert client.telemetry.requests_attempted == 0
    assert client.telemetry.skipped_insufficient_data == 1
    assert lead.property_lookup_status == "insufficient_data"
    assert lead.address_needed is True


def test_attom_marks_city_state_zip_lead_as_needs_address(tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    lead = Lead(name="Avery Stone", property_value=0, property_address="", city="Greenwich", state="CT", zip_code="06831")

    client = ATTOMClient(config)
    client.enrich_leads([lead])

    assert client.telemetry.requests_attempted == 0
    assert client.telemetry.skipped_insufficient_data == 1
    assert lead.property_lookup_status == "needs_address"
    assert "street address is missing" in lead.property_lookup_reason
    assert lead.address_needed is True
    assert lead.next_action == "Reveal/export address before ATTOM property lookup"


def test_attom_loads_csv_address_by_company_then_runs_lookup(monkeypatch, tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    address_csv = tmp_path / "lead_addresses.csv"
    config.attom.lead_addresses_path = str(address_csv)
    address_csv.write_text(
        "name,company,street_address,city,state,zip_code,source\n"
        "Avery Stone,Avery Stone Ventures,12 Round Hill Road,Greenwich,CT,06831,manual_export\n"
    )
    captured = {}

    def fake_get(url, headers, params, timeout):
        captured.update({"params": params})
        return FakeResponse(_attom_payload(owner="Avery Stone"))

    monkeypatch.setattr("src.enrichment.attom.requests.get", fake_get)
    lead = Lead(
        name="Avery S.",
        property_value=0,
        property_address="",
        apollo_person_id="p1",
        apollo_organization="Avery Stone Ventures",
        apollo_title="Founder",
    )

    client = ATTOMClient(config)
    client.enrich_leads([lead])

    assert client.telemetry.csv_addresses_loaded == 1
    assert client.telemetry.requests_attempted == 1
    assert captured["params"] == {"address1": "12 Round Hill Road", "address2": "06831"}
    assert lead.property_lookup_status == "matched"
    assert lead.property_address == "12 Round Hill Road"
    assert lead.property_estimated_value == 3_250_000
    assert "address_csv:manual_export" in lead.source_notes


def test_pipeline_runs_attom_enrichment_for_apollo_org_address(monkeypatch, tmp_path):
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.attom = "attom-key"
    config.api_keys.apollo = "apollo-key"
    config.attom.cache_path = str(tmp_path / "attom_cache.json")
    config.pipeline.database_path = str(tmp_path / "leads.db")
    person = SimpleNamespace(
        apollo_person_id="p1",
        first_name="Avery",
        last_name_obfuscated="S.",
        last_name="",
        title="Founder",
        organization_name="Avery Stone Ventures",
        organization_address="12 Round Hill Road",
        industry="Venture Capital",
        city="Greenwich",
        state="CT",
        email="",
        phone="",
        has_email=True,
        has_direct_phone=False,
        is_obfuscated=True,
        is_recycled=False,
        has_full_name=False,
        display_name="Avery S.",
    )
    monkeypatch.setattr("src.pipeline.ApolloClient.search_people", lambda self, seen_ids=None: [person])
    monkeypatch.setattr("src.pipeline.SECEdgarMatcher.match", lambda self, q: (False, []))
    monkeypatch.setattr(
        "src.enrichment.attom.requests.get",
        lambda url, headers, params, timeout: FakeResponse(_attom_payload(owner="Avery Stone Ventures")),
    )

    leads, _ = LeadPipeline(config).run(zip_codes=["06831"], persist=False, limit=1)

    assert leads[0].property_estimated_value == 3_250_000
    assert leads[0].property_match_confidence >= 0.45
    assert "attom_property" in leads[0].source_notes
