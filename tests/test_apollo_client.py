from types import SimpleNamespace

from src.enrichment.apollo import APOLLO_SEARCH_URL, ApolloClient
from src.pipeline import LeadPipeline
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


def test_apollo_search_uses_api_search_and_maps_obfuscated_fields(monkeypatch):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "test-key"
    config.apollo.enabled = True
    config.apollo.per_page = 1
    config.apollo.max_pages = 1
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "people": [
                    {
                        "id": "person-1",
                        "first_name": "Avery",
                        "last_name_obfuscated": "S.",
                        "title": "Founder",
                        "organization": {"name": "Example Capital", "industry": "Venture Capital"},
                        "has_email": True,
                        "has_direct_phone": True,
                    }
                ]
            }
        )

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)

    people = client.search_people()

    assert captured["url"] == APOLLO_SEARCH_URL
    assert captured["headers"]["X-Api-Key"] == "test-key"
    assert captured["json"]["per_page"] == 1
    assert people[0].apollo_person_id == "person-1"
    assert people[0].last_name_obfuscated == "S."
    assert people[0].organization_name == "Example Capital"
    assert people[0].industry == "Venture Capital"
    assert people[0].has_email is True
    assert people[0].is_obfuscated is True


def test_apollo_obfuscated_candidate_scores_via_signal_points(monkeypatch):
    """Obfuscated Apollo leads now score via title/org/flag signals — not Skip."""
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.apollo.enabled = True
    config.api_keys.apollo = "test-key"

    person = SimpleNamespace(
        apollo_person_id="person-1",
        first_name="Avery",
        last_name_obfuscated="S.",
        last_name="",
        title="Founder",
        organization_name="Example Capital",
        industry="Venture Capital",
        city="",
        state="",
        email="",
        phone="",
        has_email=True,
        has_direct_phone=True,
        is_obfuscated=True,
        has_full_name=False,
        display_name="Avery S.",
    )
    monkeypatch.setattr("src.pipeline.ApolloClient.search_people", lambda self, seen_ids=None: [person])
    monkeypatch.setattr("src.pipeline.SECEdgarMatcher.match", lambda self, search_term: (False, []))

    leads, _ = LeadPipeline(config).run(zip_codes=["06830"], persist=False)
    apollo_lead = next(lead for lead in leads if lead.apollo_person_id == "person-1")

    # Partial phone credit for has_direct_phone flag while obfuscated.
    assert apollo_lead.phone_score > 0
    assert apollo_lead.phone_score < config.scoring.weights.phone_reachability
    # Title + org + email flag give meaningful apollo_signal_score.
    assert apollo_lead.apollo_signal_score > 0
    # Lead is no longer automatically Skip.
    assert apollo_lead.score_tier != "Skip"
    # Obfuscation metadata is preserved.
    assert "apollo_search_obfuscated" in apollo_lead.source_notes
    assert apollo_lead.apollo_has_email is True
    assert apollo_lead.apollo_has_direct_phone is True
    # Founder is a top-tier title → high-priority reveal.
    assert apollo_lead.next_action == "Reveal in Apollo – high priority"
