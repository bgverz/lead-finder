import os
from pathlib import Path

from lead_pipeline.cli import apply_mode, load_local_env
from src.pipeline import LeadPipeline
from src.utils.config import load_config


def test_env_loading_from_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    (tmp_path / ".env").write_text("CENSUS_API_KEY=test-census-key\n")

    load_local_env()

    assert os.environ["CENSUS_API_KEY"] == "test-census-key"


def test_mock_pipeline_run_generates_excel(tmp_path: Path):
    config = load_config("config/config.example.yaml")
    apply_mode(config, "mock")
    config.output.output_dir = str(tmp_path / "output")
    config.pipeline.database_path = str(tmp_path / "prospects.db")

    leads, workbook = LeadPipeline(config).run(persist=True)

    assert leads
    assert Path(workbook).exists()
    assert any(lead.score_tier == "Hot" for lead in leads)
