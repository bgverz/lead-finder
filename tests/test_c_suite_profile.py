from click.testing import CliRunner

from lead_pipeline.cli import main
from src.enrichment.apollo import ApolloClient
from src.models import Lead
from src.scoring.scorer import LeadScorer
from src.utils.config import load_config
from src.utils.profiles import get_profile, list_profiles


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = "ok"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_c_suite_profile_exists():
    profile = get_profile("c_suite")

    assert "c_suite" in list_profiles()
    assert "CEO" in profile.person_titles
    assert "Chief Investment Officer" in profile.person_titles
    assert profile.employee_count_min == 5
    assert profile.employee_count_max == 500


def test_c_suite_profile_title_filters_are_applied(monkeypatch):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.active_profile = "c_suite"
    config.apollo.random_page_offset_max = 0
    config.apollo.search_rotation = []
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return _FakeResponse({"people": []})

    client = ApolloClient(config)
    client.session.post = fake_post
    client.search_people()

    assert captured["payload"]["person_titles"] == list(get_profile("c_suite").person_titles)
    assert captured["payload"]["organization_num_employees_ranges"] == [
        "1,10",
        "11,50",
        "51,200",
        "201,500",
    ]


def test_c_suite_profile_keeps_mega_company_exclusions(monkeypatch):
    config = load_config("config/config.example.yaml")
    config.api_keys.apollo = "key"
    config.apollo.enabled = True
    config.apollo.active_profile = "c_suite"
    config.apollo.random_page_offset_max = 0
    config.apollo.search_rotation = []

    def fake_post(url, headers, json, timeout):
        return _FakeResponse(
            {
                "people": [
                    {
                        "id": "mega",
                        "first_name": "Mega",
                        "title": "CEO",
                        "organization": {"name": "Microsoft Ventures"},
                    },
                    {
                        "id": "small",
                        "first_name": "Small",
                        "title": "CEO",
                        "organization": {"name": "Regional AI Ventures"},
                    },
                ]
            }
        )

    client = ApolloClient(config)
    client.session.post = fake_post
    people = client.search_people()

    assert [person.apollo_person_id for person in people] == ["small"]


def test_c_suite_scoring_nuance():
    scorer = LeadScorer(load_config("config/config.example.yaml"))

    founder = scorer.score(Lead(name="A", property_value=0, property_address="", apollo_person_id="1", apollo_title="Founder"))
    cfo = scorer.score(Lead(name="B", property_value=0, property_address="", apollo_person_id="2", apollo_title="CFO"))
    cto = scorer.score(Lead(name="C", property_value=0, property_address="", apollo_person_id="3", apollo_title="CTO"))
    generic_chief = scorer.score(
        Lead(name="D", property_value=0, property_address="", apollo_person_id="4", apollo_title="Chief People Officer")
    )

    assert founder.apollo_signal_score > cfo.apollo_signal_score
    assert cfo.apollo_signal_score > cto.apollo_signal_score
    assert cto.apollo_signal_score > generic_chief.apollo_signal_score
    assert "financial decision-maker signal" in Lead(
        name="B",
        property_value=0,
        property_address="",
        apollo_person_id="2",
        apollo_title="Chief Financial Officer",
    ).lead_summary
    assert "technology operator signal" in Lead(
        name="C",
        property_value=0,
        property_address="",
        apollo_person_id="3",
        apollo_title="Chief Technology Officer",
    ).lead_summary


def test_cli_accepts_c_suite_profile(monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("APOLLO_API_KEY", "test-apollo")
    monkeypatch.setenv("CENSUS_API_KEY", "test-census")
    monkeypatch.setenv("SEC_USER_AGENT", "InvestorLeadPipeline/1.0 ops@example.com")

    def fake_run(self, zip_codes=None, state="", output_path=None, persist=True, limit=None):
        return [], "data/output/test.xlsx"

    monkeypatch.setattr("lead_pipeline.cli.LeadPipeline.run", fake_run)
    result = runner.invoke(
        main,
        ["run", "--mode", "api", "--profile", "c_suite", "--limit", "1", "--no-persist"],
    )

    assert result.exit_code == 0
    assert "Profile            : c_suite" in result.output
