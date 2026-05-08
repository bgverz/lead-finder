"""Tests for US-only geographic filtering in Apollo searches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lead_pipeline.enrichment.apollo import ApolloClient, ApolloPerson, _US_COUNTRY_NAMES
from lead_pipeline.models import Lead
from lead_pipeline.utils.config import load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _us_config(countries: list[str] | None = None):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "test-key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    config.apollo.excluded_organizations = []
    config.apollo.excluded_titles = []
    config.apollo.random_page_offset_max = 0
    if countries is not None:
        config.targeting.countries = countries
    else:
        config.targeting.countries = ["US"]
    return config


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _person_row(person_id: str, country: str, title: str = "CEO") -> dict:
    return {"id": person_id, "first_name": "Test", "title": title, "country": country}


# ---------------------------------------------------------------------------
# Server-side: person_country_codes in payload
# ---------------------------------------------------------------------------

def test_us_country_code_added_to_payload():
    """person_country_codes: ['US'] must appear in Apollo search payload."""
    config = _us_config(["US"])
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert "person_country_codes" in captured["payload"]
    assert captured["payload"]["person_country_codes"] == ["US"]


def test_multiple_country_codes_added_to_payload():
    config = _us_config(["US", "CA"])
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert set(captured["payload"]["person_country_codes"]) == {"US", "CA"}


def test_no_country_codes_in_payload_when_countries_empty():
    """When targeting.countries is [], no geo filter should be sent."""
    config = _us_config([])
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert "person_country_codes" not in captured["payload"]


def test_country_codes_uppercased_in_payload():
    """Config may store 'us' lowercase; payload must be uppercase."""
    config = _us_config(["us"])
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert captured["payload"]["person_country_codes"] == ["US"]


# ---------------------------------------------------------------------------
# Client-side fallback: _is_target_country
# ---------------------------------------------------------------------------

def _make_person(country: str, city: str = "", state: str = "") -> ApolloPerson:
    return ApolloPerson(
        apollo_person_id="p1",
        country=country,
        city=city,
        state=state,
    )


def test_client_filter_keeps_us_iso_code():
    config = _us_config(["US"])
    client = ApolloClient(config)
    person = _make_person("US")
    assert client._is_target_country(person, ["US"]) is True


def test_client_filter_keeps_united_states_full_name():
    config = _us_config(["US"])
    client = ApolloClient(config)
    for name in ("United States", "United States of America", "united states", "USA"):
        person = _make_person(name)
        assert client._is_target_country(person, ["US"]) is True, f"Failed for: {name}"


def test_client_filter_drops_explicit_non_us_country():
    config = _us_config(["US"])
    client = ApolloClient(config)
    for country in ("United Kingdom", "GB", "Canada", "CA", "India", "IN", "Germany"):
        person = _make_person(country)
        assert client._is_target_country(person, ["US"]) is False, f"Should filter: {country}"


def test_client_filter_passes_empty_country():
    """Empty country field means no geo data — give benefit of the doubt."""
    config = _us_config(["US"])
    client = ApolloClient(config)
    person = _make_person("")
    assert client._is_target_country(person, ["US"]) is True


def test_client_filter_disabled_when_countries_empty():
    """No filtering when target countries list is empty."""
    config = _us_config([])
    client = ApolloClient(config)
    person = _make_person("United Kingdom")
    assert client._is_target_country(person, []) is True


# ---------------------------------------------------------------------------
# End-to-end: non-US leads filtered from search results
# ---------------------------------------------------------------------------

def test_non_us_lead_dropped_from_results():
    """International candidates with explicit country must be excluded."""
    config = _us_config(["US"])

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                _person_row("us-1", "United States", "Founder"),
                _person_row("uk-1", "United Kingdom", "CEO"),
                _person_row("ca-1", "Canada", "Partner"),
                _person_row("gb-1", "GB", "Managing Director"),
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()

    ids = [p.apollo_person_id for p in people]
    assert "us-1" in ids
    assert "uk-1" not in ids
    assert "ca-1" not in ids
    assert "gb-1" not in ids


def test_us_leads_all_kept():
    """All candidates with US/United States country must survive filtering."""
    config = _us_config(["US"])

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                _person_row("p1", "United States", "Founder"),
                _person_row("p2", "US", "CEO"),
                _person_row("p3", "USA", "Partner"),
                _person_row("p4", "", "Managing Director"),  # empty → keep
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()

    ids = [p.apollo_person_id for p in people]
    assert "p1" in ids
    assert "p2" in ids
    assert "p3" in ids
    assert "p4" in ids


def test_geo_filtered_count_in_stats():
    """geo_filtered stat should reflect the number of non-US candidates dropped."""
    config = _us_config(["US"])

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                _person_row("us-1", "United States"),
                _person_row("uk-1", "United Kingdom"),
                _person_row("ca-1", "Canada"),
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert client.last_stats["geo_filtered"] == 2
    assert client.last_stats["final_kept"] == 1


def test_geo_filter_zero_when_no_international_leads():
    config = _us_config(["US"])

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                _person_row("p1", "United States"),
                _person_row("p2", "US"),
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert client.last_stats["geo_filtered"] == 0


def test_no_geo_filtering_when_countries_empty():
    """With countries=[], international leads must not be filtered."""
    config = _us_config([])

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                _person_row("uk-1", "United Kingdom"),
                _person_row("ca-1", "Canada"),
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()

    assert len(people) == 2
    assert client.last_stats["geo_filtered"] == 0


# ---------------------------------------------------------------------------
# Config: countries defaults and loading
# ---------------------------------------------------------------------------

def test_targeting_countries_defaults_to_us():
    from lead_pipeline.utils.config import TargetingConfig
    cfg = TargetingConfig()
    assert cfg.countries == ["US"]


def test_countries_loaded_from_yaml():
    config = load_config("config/config.example.yaml")
    assert "US" in config.targeting.countries


def test_countries_uppercased_when_read_from_config():
    """Config with lowercase 'us' must still produce uppercase in payload."""
    config = _us_config(["us", "ca"])
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    codes = captured["payload"]["person_country_codes"]
    assert all(c == c.upper() for c in codes)


# ---------------------------------------------------------------------------
# country field on Lead model and pipeline output
# ---------------------------------------------------------------------------

def test_lead_country_field_default_empty():
    lead = Lead(name="Test", property_value=0, property_address="")
    assert lead.country == ""


def test_lead_country_in_to_output_dict():
    lead = Lead(name="Test", property_value=0, property_address="", country="United States")
    d = lead.to_output_dict()
    assert "country" in d
    assert d["country"] == "United States"


def test_country_in_output_columns():
    from lead_pipeline.output.excel import OUTPUT_COLUMNS, CRM_EXPORT_COLUMNS
    assert "country" in OUTPUT_COLUMNS
    assert "country" in CRM_EXPORT_COLUMNS


# ---------------------------------------------------------------------------
# _US_COUNTRY_NAMES constant
# ---------------------------------------------------------------------------

def test_us_country_names_constant_coverage():
    """Ensure common US country name variants are recognized."""
    expected = {"united states", "united states of america", "usa", "us", "u.s.", "u.s.a."}
    assert expected.issubset(_US_COUNTRY_NAMES)
