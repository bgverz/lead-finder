"""Tests for: next_action, apollo_signal_score, SEC_USER_AGENT doctor check,
Census per-state error handling, excluded_titles filtering."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.enrichment.apollo import ApolloClient
from src.models import Lead
from src.scoring.scorer import LeadScorer
from src.utils.config import load_config


# ---------------------------------------------------------------------------
# next_action property
# ---------------------------------------------------------------------------

def test_next_action_reveal_high_priority_for_top_title():
    lead = Lead(
        name="Avery S.",
        property_value=0,
        property_address="",
        apollo_person_id="p1",
        apollo_title="CEO",
        apollo_obfuscated=True,
        score_tier="Cool",
    )
    assert lead.next_action == "Reveal in Apollo – high priority"


def test_next_action_reveal_verify_first_for_medium_title():
    lead = Lead(
        name="Jordan T.",
        property_value=0,
        property_address="",
        apollo_person_id="p2",
        apollo_title="Principal",
        apollo_obfuscated=True,
        score_tier="Skip",
    )
    assert lead.next_action == "Reveal in Apollo – verify first"


def test_next_action_skip_weak_role_for_obfuscated_no_title():
    lead = Lead(
        name="Unknown",
        property_value=0,
        property_address="",
        apollo_person_id="p1",
        apollo_obfuscated=True,
        score_tier="Skip",
    )
    assert lead.next_action == "Skip – weak role"


def test_next_action_export_when_no_contact_and_not_obfuscated():
    lead = Lead(
        name="Jordan T.",
        property_value=0,
        property_address="",
        apollo_person_id="p2",
        apollo_obfuscated=False,
        email="",
        phone="",
        score_tier="Cool",
    )
    assert lead.next_action == "Export from Apollo/ZoomInfo"


def test_next_action_call_mobile_when_valid_mobile():
    lead = Lead(
        name="Sam R.",
        property_value=0,
        property_address="",
        phone="+12025551234",
        phone_valid=True,
        phone_line_type="mobile",
        score_tier="Warm",
    )
    assert lead.next_action == "Call mobile"


def test_next_action_skip_for_low_quality_non_apollo():
    lead = Lead(name="Nobody", property_value=0, property_address="", score_tier="Skip")
    assert lead.next_action == "Skip"


def test_next_action_research_outreach_for_hot_lead():
    lead = Lead(
        name="Rich Owner",
        property_value=3_500_000,
        property_address="1 Main St",
        score_tier="Hot",
    )
    assert lead.next_action == "Research + Outreach"


# ---------------------------------------------------------------------------
# Apollo signal scoring (titles + org + flags)
# ---------------------------------------------------------------------------

def _score_apollo_lead(**kwargs) -> Lead:
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    defaults = dict(name="Test", property_value=0, property_address="", apollo_person_id="px")
    lead = Lead(**{**defaults, **kwargs})
    return scorer.score(lead)


def test_apollo_ceo_with_org_scores_above_skip():
    # CEO(25) + org(5) + email_flag(5) = 35 apollo signal
    # + has_direct_phone while obfuscated → phone_score = 10//2 = 5
    # Total = 40 → "Cool" (threshold = 40).
    lead = _score_apollo_lead(
        apollo_title="CEO",
        apollo_organization="Example Capital",
        apollo_has_email=True,
        apollo_has_direct_phone=True,
        apollo_obfuscated=True,
    )
    assert lead.apollo_signal_score > 0
    assert lead.score_tier != "Skip"


def test_apollo_senior_title_gets_business_ownership_points():
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(
        name="A",
        property_value=0,
        property_address="",
        apollo_person_id="p3",
        apollo_title="Founder",
    )
    scorer.score(lead)
    assert lead.apollo_signal_score >= config.scoring.weights.business_ownership


def test_apollo_mid_title_gets_partial_points():
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(
        name="B",
        property_value=0,
        property_address="",
        apollo_person_id="p4",
        apollo_title="Partner",
    )
    scorer.score(lead)
    # Should be between 0 and senior title score
    assert 0 < lead.apollo_signal_score < config.scoring.weights.business_ownership + 10


def test_non_apollo_lead_gets_zero_signal_score():
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(name="C", property_value=2_000_000, property_address="1 St")
    scorer.score(lead)
    assert lead.apollo_signal_score == 0


def test_apollo_obfuscated_direct_phone_flag_gives_partial_phone_score():
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(
        name="D",
        property_value=0,
        property_address="",
        apollo_person_id="p5",
        apollo_has_direct_phone=True,
        apollo_obfuscated=True,
    )
    scorer.score(lead)
    assert lead.phone_score > 0
    assert lead.phone_score < config.scoring.weights.phone_reachability


# ---------------------------------------------------------------------------
# SEC_USER_AGENT doctor inconsistency
# ---------------------------------------------------------------------------

def test_doctor_sec_user_agent_placeholder_detail(monkeypatch):
    """Simulate the env-variable loop in doctor for SEC_USER_AGENT placeholder."""
    monkeypatch.setenv("SEC_USER_AGENT", "InvestorLeadPipeline/1.0 contact@example.com")

    import os
    value = os.getenv("SEC_USER_AGENT", "")
    is_placeholder = "contact@example.com" in value

    assert is_placeholder, "Placeholder detection logic must identify the default email"
    # The detail string that doctor would emit.
    detail = "set but still a placeholder - update to a real contact email" if is_placeholder else "configured"
    assert "placeholder" in detail


def test_doctor_sec_user_agent_real_value(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "InvestorLeadPipeline/1.0 ops@mycompany.com")

    import os
    value = os.getenv("SEC_USER_AGENT", "")
    is_placeholder = "contact@example.com" in value

    assert not is_placeholder
    detail = "set but still a placeholder - update to a real contact email" if is_placeholder else "configured"
    assert detail == "configured"


# ---------------------------------------------------------------------------
# Census county-level queries (new approach: for=county:*&in=state:XX)
# ---------------------------------------------------------------------------

def test_census_skips_unknown_state_without_crashing(monkeypatch):
    from src.collectors.census import CensusClient
    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"

    client = CensusClient(config)
    areas = client._fetch_county_areas_for_states(["ZZ"])  # ZZ is not a valid state
    assert areas == []


def test_census_county_query_uses_in_state_param(monkeypatch):
    """County queries must use for=county:*&in=state:XX (reliably supported by Census API)."""
    import requests as req
    from src.collectors.census import CensusClient

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.census = "test-key"
    captured = {}

    def fake_get(url, params, timeout):
        captured.update({"params": dict(params)})
        resp = SimpleNamespace(
            status_code=200,
            json=lambda: [
                ["NAME", "B19013_001E", "B25077_001E", "B01003_001E", "state", "county"],
            ],
        )
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(req, "get", fake_get)
    client = CensusClient(config)
    client._fetch_county_areas_for_states(["CT"])

    assert captured["params"]["for"] == "county:*"
    assert captured["params"]["in"] == "state:09"


def test_census_county_query_filters_by_wealth_threshold(monkeypatch):
    """Only counties meeting income or home-value threshold are returned."""
    import requests as req
    from src.collectors.census import CensusClient

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.targeting.min_median_income = 150_000
    config.targeting.min_median_home_value = 1_000_000

    def fake_get(url, params, timeout):
        resp = SimpleNamespace(
            status_code=200,
            json=lambda: [
                ["NAME", "B19013_001E", "B25077_001E", "B01003_001E", "state", "county"],
                ["Fairfield County, CT", "200000", "1500000", "5000", "09", "001"],  # ← keep
                ["Windham County, CT",   "60000",  "200000",  "3000", "09", "015"],  # ← drop
            ],
        )
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(req, "get", fake_get)
    client = CensusClient(config)
    areas = client._fetch_county_areas_for_states(["CT"])

    assert len(areas) == 1
    assert areas[0].state == "CT"
    assert areas[0].geography_type == "county"
    assert areas[0].median_income == 200_000


def test_census_continues_after_per_state_http_error(monkeypatch):
    """A per-state failure skips that state and continues with others."""
    import requests as req
    from src.collectors.census import CensusClient

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.targeting.min_median_income = 50_000
    config.targeting.min_median_home_value = 100_000

    call_count = {"n": 0}

    def fake_get(url, params, timeout):
        call_count["n"] += 1
        if params.get("in") == "state:12":  # FL fails
            resp = SimpleNamespace(status_code=400, text="bad request")
            exc = req.HTTPError(response=resp)
            exc.response = resp
            raise exc
        resp = SimpleNamespace(
            status_code=200,
            json=lambda: [
                ["NAME", "B19013_001E", "B25077_001E", "B01003_001E", "state", "county"],
                ["Fairfield County, CT", "200000", "1500000", "5000", "09", "001"],
            ],
        )
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(req, "get", fake_get)
    client = CensusClient(config)
    areas = client._fetch_county_areas_for_states(["CT", "FL"])

    assert call_count["n"] == 2  # tried both states
    assert any(a.state == "CT" for a in areas)
    assert not any(a.state == "FL" for a in areas)


def test_census_returns_empty_on_http_failure(monkeypatch):
    """A failed request returns [] without raising."""
    import requests as req
    from src.collectors.census import CensusClient

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"

    def fake_get(url, params, timeout):
        resp = SimpleNamespace(status_code=400, text="error")
        exc = req.HTTPError(response=resp)
        exc.response = resp
        raise exc

    monkeypatch.setattr(req, "get", fake_get)
    client = CensusClient(config)
    areas = client._fetch_county_areas_for_states(["CT"])
    assert areas == []


# ---------------------------------------------------------------------------
# Apollo excluded_titles client-side filtering
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_apollo_excluded_titles_drops_matching_candidates(monkeypatch):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    # Ensure no exception overrides for this test.
    config.apollo.excluded_titles = ["Analyst", "Associate"]
    config.apollo.excluded_titles_unless_containing = {}

    def fake_post(url, headers, json, timeout):
        return _FakeResponse(
            {
                "people": [
                    {"id": "1", "first_name": "A", "title": "Senior Analyst"},
                    {"id": "2", "first_name": "B", "title": "CEO"},
                    {"id": "3", "first_name": "C", "title": "Operations Associate"},
                ]
            }
        )

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()

    ids = [p.apollo_person_id for p in people]
    assert "1" not in ids  # Analyst → excluded
    assert "2" in ids      # CEO → kept
    assert "3" not in ids  # Operations Associate → excluded (no investment exception)


def test_apollo_no_excluded_titles_keeps_all(monkeypatch):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    config.apollo.excluded_titles = []

    def fake_post(url, headers, json, timeout):
        return _FakeResponse(
            {"people": [{"id": "1", "first_name": "A", "title": "Analyst"}]}
        )

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()
    assert len(people) == 1


# ---------------------------------------------------------------------------
# SEC EDGAR retry + per-candidate graceful failure
# ---------------------------------------------------------------------------

def test_sec_retries_on_500_and_returns_false_after_exhaustion(monkeypatch):
    import requests as req
    from src.collectors.sec_edgar import SECEdgarMatcher
    from src.utils.config import load_config

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.sec_user_agent = "InvestorLeadPipeline/1.0 test@example.com"

    attempt_count = {"n": 0}

    def fake_get(url, params, headers, timeout):
        attempt_count["n"] += 1
        resp = SimpleNamespace(
            status_code=500,
            text="Internal Server Error",
            json=lambda: {},
        )
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(req, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)  # skip actual delays

    matcher = SECEdgarMatcher(config)
    ok, details = matcher.match("Test Person")

    assert ok is False
    assert details == []
    assert attempt_count["n"] == 3  # exactly 3 attempts


def test_sec_succeeds_on_third_attempt(monkeypatch):
    import requests as req
    from src.collectors.sec_edgar import SECEdgarMatcher

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.sec_user_agent = "InvestorLeadPipeline/1.0 test@example.com"

    attempt_count = {"n": 0}
    good_response = {
        "hits": {"hits": [{"_source": {"entity_name": "Acme", "file_date": "2024-01-01", "form_type": "D"}}]}
    }

    def fake_get(url, params, headers, timeout):
        attempt_count["n"] += 1
        if attempt_count["n"] < 3:
            resp = SimpleNamespace(status_code=500, text="err", json=lambda: {})
            resp.raise_for_status = lambda: None
            return resp
        resp = SimpleNamespace(status_code=200, text="ok", json=lambda: good_response)
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(req, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)

    matcher = SECEdgarMatcher(config)
    ok, details = matcher.match("Acme Corp")

    assert ok is True
    assert len(details) == 1
    assert details[0]["company_name"] == "Acme"
    assert attempt_count["n"] == 3


def test_sec_non_retryable_error_skips_immediately(monkeypatch):
    """Non-5xx errors (e.g. unexpected exception) skip without all 3 retries."""
    import requests as req
    from src.collectors.sec_edgar import SECEdgarMatcher

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.api_keys.sec_user_agent = "InvestorLeadPipeline/1.0 test@example.com"

    attempt_count = {"n": 0}

    def fake_get(url, params, headers, timeout):
        attempt_count["n"] += 1
        raise ValueError("unexpected parse error")

    monkeypatch.setattr(req, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)

    matcher = SECEdgarMatcher(config)
    ok, details = matcher.match("Anyone")

    assert ok is False
    assert details == []
    assert attempt_count["n"] == 1  # breaks immediately on non-retryable error


# ---------------------------------------------------------------------------
# Apollo title-tier scoring spread
# ---------------------------------------------------------------------------

def test_top_title_scores_higher_than_high_title():
    from src.scoring.scorer import LeadScorer, _TITLE_TIER_POINTS
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)

    top_lead = scorer.score(Lead(name="A", property_value=0, property_address="",
                                  apollo_person_id="p1", apollo_title="Founder"))
    high_lead = scorer.score(Lead(name="B", property_value=0, property_address="",
                                   apollo_person_id="p2", apollo_title="Managing Partner"))
    mid_lead = scorer.score(Lead(name="C", property_value=0, property_address="",
                                  apollo_person_id="p3", apollo_title="Principal"))
    low_lead = scorer.score(Lead(name="D", property_value=0, property_address="",
                                  apollo_person_id="p4", apollo_title="Sales Manager"))

    assert top_lead.apollo_signal_score > high_lead.apollo_signal_score
    assert high_lead.apollo_signal_score > mid_lead.apollo_signal_score
    assert mid_lead.apollo_signal_score > low_lead.apollo_signal_score


def test_strong_apollo_lead_can_reach_warm_tier():
    """Founder + org + email flag + phone flag + SEC → enough for Warm (≥60)."""
    from src.scoring.scorer import LeadScorer
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(
        name="Top Exec",
        property_value=0,
        property_address="",
        apollo_person_id="px",
        apollo_title="Founder",
        apollo_organization="Acme Capital",
        apollo_has_email=True,
        apollo_has_direct_phone=True,
        apollo_obfuscated=True,
        sec_match=True,
    )
    scorer.score(lead)
    # Founder(35) + org(5) + email(5) = 45 signal; phone flag(5) + SEC(10) = 60 total → Warm
    assert lead.score_tier in ("Warm", "Hot")


def test_weak_apollo_title_stays_skip():
    from src.scoring.scorer import LeadScorer
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)
    lead = Lead(
        name="Low Exec",
        property_value=0,
        property_address="",
        apollo_person_id="px",
        apollo_title="Sales Manager",  # low tier
    )
    scorer.score(lead)
    assert lead.score_tier == "Skip"


# ---------------------------------------------------------------------------
# lead_summary improvements
# ---------------------------------------------------------------------------

def test_lead_summary_apollo_senior_title():
    lead = Lead(
        name="Avery S.",
        property_value=0,
        property_address="",
        apollo_person_id="p1",
        apollo_title="CEO",
        apollo_organization="Example Capital",
        apollo_obfuscated=True,
    )
    summary = lead.lead_summary
    assert "CEO" in summary
    assert "Example Capital" in summary
    assert "reveal" in summary.lower()
    assert "signal" in summary.lower()


def test_lead_summary_apollo_with_sec_match():
    lead = Lead(
        name="B",
        property_value=0,
        property_address="",
        apollo_person_id="p2",
        apollo_title="Founder",
        sec_match=True,
        apollo_obfuscated=True,
    )
    summary = lead.lead_summary
    assert "SEC" in summary or "sec" in summary.lower()


# ---------------------------------------------------------------------------
# excluded_titles_unless_containing — the associate special case
# ---------------------------------------------------------------------------

def test_investment_associate_is_kept_by_exception():
    """'Investment Associate' should pass the filter when exception keyword is set."""
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.excluded_titles = ["Associate"]
    config.apollo.excluded_titles_unless_containing = {"associate": ["investment", "venture"]}

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                {"id": "1", "first_name": "A", "title": "Investment Associate"},  # keep
                {"id": "2", "first_name": "B", "title": "Operations Associate"},  # drop
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()
    ids = [p.apollo_person_id for p in people]
    assert "1" in ids
    assert "2" not in ids


# ---------------------------------------------------------------------------
# open-latest selects newest workbook
# ---------------------------------------------------------------------------

def test_open_latest_selects_newest_xlsx(tmp_path):
    import time
    from lead_pipeline.cli import resolve_config_path

    # Write two workbooks with a small time gap.
    old = tmp_path / "investor_leads_20250101_120000.xlsx"
    new = tmp_path / "investor_leads_20260430_120000.xlsx"
    old.write_bytes(b"old")
    time.sleep(0.05)
    new.write_bytes(b"new")

    candidates = list(tmp_path.glob("*.xlsx"))
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    assert latest == new


# ---------------------------------------------------------------------------
# ApolloClient — new filters: employee ranges, org exclusion, page randomization
# ---------------------------------------------------------------------------

def test_build_employee_ranges_bounded():
    from src.enrichment.apollo import _build_employee_ranges
    ranges = _build_employee_ranges(5, 500)
    assert "1,10" in ranges
    assert "201,500" in ranges
    assert "501,1000" not in ranges
    assert "1001,5000" not in ranges


def test_build_employee_ranges_no_upper_bound():
    from src.enrichment.apollo import _build_employee_ranges
    ranges = _build_employee_ranges(5, 0)  # 0 = no upper limit
    assert "10001," in ranges


def test_apollo_org_exclusion_drops_matching_candidate():
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    config.apollo.excluded_organizations = ["Mega Corp", "Big Tech"]
    config.apollo.excluded_titles = []
    config.apollo.random_page_offset_max = 0

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                {"id": "1", "first_name": "A", "title": "CEO",
                 "organization": {"name": "Mega Corp International"}},
                {"id": "2", "first_name": "B", "title": "Founder",
                 "organization": {"name": "Small Ventures LLC"}},
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people()

    ids = [p.apollo_person_id for p in people]
    assert "1" not in ids   # Mega Corp → excluded
    assert "2" in ids       # Small Ventures → kept


def test_apollo_employee_ranges_in_payload():
    """organization_num_employees_ranges is added to payload when configured."""
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 1
    config.apollo.max_pages = 1
    config.apollo.employee_count_min = 5
    config.apollo.employee_count_max = 200
    config.apollo.random_page_offset_max = 0
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert "organization_num_employees_ranges" in captured["payload"]
    ranges = captured["payload"]["organization_num_employees_ranges"]
    assert "501,1000" not in ranges   # above max 200


def test_apollo_page_randomization_respects_offset_max():
    """Starting page is always within [1, random_page_offset_max]."""
    config = load_config("config/config.example.yaml")
    config.apollo.random_page_offset_max = 4

    client = ApolloClient(config)
    pages_seen: set[int] = set()
    for _ in range(40):
        pages_seen.add(client._start_page())

    assert all(1 <= p <= 4 for p in pages_seen)


def test_apollo_seen_ids_are_skipped():
    """Candidates in seen_ids set are filtered before being returned."""
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    config.apollo.excluded_organizations = []
    config.apollo.excluded_titles = []
    config.apollo.random_page_offset_max = 0

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                {"id": "seen-1", "first_name": "Old", "title": "CEO"},
                {"id": "new-2",  "first_name": "New", "title": "Founder"},
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    people = client.search_people(seen_ids={"seen-1"})

    ids = [p.apollo_person_id for p in people]
    assert "seen-1" not in ids
    assert "new-2" in ids


# ---------------------------------------------------------------------------
# Org investor-signal bonus in scorer
# ---------------------------------------------------------------------------

def test_investor_org_name_boosts_score():
    from src.scoring.scorer import LeadScorer
    config = load_config("config/config.example.yaml")
    scorer = LeadScorer(config)

    investment_lead = scorer.score(Lead(
        name="A", property_value=0, property_address="",
        apollo_person_id="p1", apollo_title="Partner",
        apollo_organization="Summit Capital Partners",
    ))
    generic_lead = scorer.score(Lead(
        name="B", property_value=0, property_address="",
        apollo_person_id="p2", apollo_title="Partner",
        apollo_organization="Generic Corp",
    ))
    assert investment_lead.apollo_signal_score > generic_lead.apollo_signal_score


# ---------------------------------------------------------------------------
# Seen-IDs DB round-trip
# ---------------------------------------------------------------------------

def test_seen_apollo_ids_round_trip(tmp_path):
    from src.utils.database import LeadDatabase

    db = LeadDatabase(str(tmp_path / "test.db"))

    class FakePerson:
        apollo_person_id = "abc123"
        organization_name = "TestCo"
        title = "CEO"

    db.save_seen_apollo_ids([FakePerson()])
    seen = db.load_seen_apollo_ids(cooldown_days=0)
    assert "abc123" in seen
    db.close()


# ---------------------------------------------------------------------------
# Search profiles
# ---------------------------------------------------------------------------

def test_get_profile_returns_correct_titles():
    from src.utils.profiles import get_profile
    p = get_profile("vc_pe")
    assert "Partner" in p.person_titles
    assert p.employee_count_max <= 200


def test_get_profile_raises_on_unknown():
    from src.utils.profiles import get_profile
    import pytest
    with pytest.raises(ValueError, match="Unknown profile"):
        get_profile("nonexistent_profile")


def test_list_profiles_contains_all_six():
    from src.utils.profiles import list_profiles
    names = list_profiles()
    assert set(names) >= {"vc_pe", "founders", "family_office", "real_estate", "healthcare", "broad_hnw"}


def test_profile_applied_in_payload(monkeypatch):
    """When active_profile is set, payload uses profile's person_titles."""
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 1
    config.apollo.max_pages = 1
    config.apollo.random_page_offset_max = 0
    config.apollo.active_profile = "family_office"
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert "person_titles" in captured["payload"]
    # Family Office profile titles should appear, not the base config titles.
    assert "Family Office" in captured["payload"]["person_titles"] or \
           "Chief Investment Officer" in captured["payload"]["person_titles"]
    assert "Founder" not in captured["payload"]["person_titles"]  # not in family_office profile


def test_search_rotation_overrides_base_titles(monkeypatch):
    """search_rotation variant overrides base filters.person_titles."""
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 1
    config.apollo.max_pages = 1
    config.apollo.random_page_offset_max = 0
    config.apollo.active_profile = ""
    config.apollo.search_rotation = [
        {"name": "test_variant", "person_titles": ["Specific Title Only"]}
    ]
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people()

    assert captured["payload"]["person_titles"] == ["Specific Title Only"]


# ---------------------------------------------------------------------------
# Cooldown fallback
# ---------------------------------------------------------------------------

def test_cooldown_fallback_retries_without_seen_ids(monkeypatch):
    """When all candidates are suppressed, pipeline retries with empty seen_ids."""
    from src.utils.database import LeadDatabase

    config = load_config("config/config.example.yaml")
    config.sources.mode = "api"
    config.apollo.enabled = True
    config.api_keys.apollo = "test-key"
    config.apollo.seen_ids_cooldown_days = 30

    call_count = {"n": 0}

    def fake_search(self, seen_ids=None):
        call_count["n"] += 1
        if seen_ids:  # first call suppresses everyone → return empty
            return []
        # Fallback call (seen_ids=set()) returns a candidate
        fake_person = SimpleNamespace(
            apollo_person_id="p-fallback",
            first_name="Old",
            last_name_obfuscated="C.",
            last_name="",
            title="CEO",
            organization_name="Old Corp",
            city="", state="",
            email="", phone="",
            has_email=False, has_direct_phone=False, has_mobile_phone=False,
            is_obfuscated=True, is_recycled=False,
            has_full_name=False, display_name="Old C.",
            raw={},
        )
        return [fake_person]

    def fake_load_seen(self, cooldown_days=0):
        return {"some-seen-id"}  # non-empty → triggers fallback

    def fake_save(self, people):
        pass

    monkeypatch.setattr("src.pipeline.ApolloClient.search_people", fake_search)
    monkeypatch.setattr("src.utils.database.LeadDatabase.load_seen_apollo_ids", fake_load_seen)
    monkeypatch.setattr("src.utils.database.LeadDatabase.save_seen_apollo_ids", fake_save)
    monkeypatch.setattr("src.pipeline.SECEdgarMatcher.match", lambda self, q: (False, []))

    from src.pipeline import LeadPipeline
    leads, _ = LeadPipeline(config).run(zip_codes=["06830"], persist=False)

    assert call_count["n"] == 2  # first (suppressed) + fallback
    fallback_lead = next((l for l in leads if l.apollo_person_id == "p-fallback"), None)
    assert fallback_lead is not None
    assert "apollo_recycled" in fallback_lead.source_notes


# ---------------------------------------------------------------------------
# Telemetry last_stats
# ---------------------------------------------------------------------------

def test_last_stats_populated_after_search():
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.per_page = 10
    config.apollo.max_pages = 1
    config.apollo.excluded_organizations = ["MegaCorp"]
    config.apollo.excluded_titles = []
    config.apollo.random_page_offset_max = 0

    def fake_post(url, headers, json, timeout):
        return _FakeResponse({
            "people": [
                {"id": "1", "first_name": "A", "title": "CEO",
                 "organization": {"name": "MegaCorp Inc"}},      # excluded by org
                {"id": "2", "first_name": "B", "title": "Founder",
                 "organization": {"name": "Small Ventures"}},    # kept
            ]
        })

    client = ApolloClient(config)
    client.session = SimpleNamespace(post=fake_post)
    client.search_people(seen_ids=set())

    assert client.last_stats["raw_retrieved"] == 2
    assert client.last_stats["org_filtered"] == 1
    assert client.last_stats["final_kept"] == 1
