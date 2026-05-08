"""Business ownership enrichment from public corporate records."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from lead_pipeline.models import BusinessEntity
from lead_pipeline.utils.config import Config


class BusinessEntityMatcher:
    """Match prospect names to business entity/officer records."""

    def __init__(self, config: Config):
        self.config = config
        self._index = self._load_sample_index() if config.sources.mode == "sample" else {}

    def match(self, owner_name: str) -> list[BusinessEntity]:
        if self.config.sources.mode == "api":
            raise NotImplementedError(
                "OpenCorporates/state SOS adapter boundary is ready. "
                "Expected lookup: officer/name search plus state registry normalization."
            )
        return list(self._index.get(_norm(owner_name), []))

    def _load_sample_index(self) -> dict[str, list[BusinessEntity]]:
        path = Path(self.config.sources.sample_business_entities)
        if not path.exists():
            return {}
        frame = pd.read_csv(path)
        index: dict[str, list[BusinessEntity]] = {}
        for row in frame.to_dict("records"):
            entity = BusinessEntity(
                name=str(row.get("entity_name", "")).strip(),
                role=str(row.get("role", "")).strip(),
                entity_type=str(row.get("entity_type", "")).strip(),
                filing_date=_parse_date(row.get("filing_date")),
                source=str(row.get("source", "sample_business_records")),
            )
            index.setdefault(_norm(str(row.get("owner_name", ""))), []).append(entity)
        return index


def _norm(value: str) -> str:
    return " ".join(value.lower().replace(".", "").split())


def _parse_date(value: object) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return date.fromisoformat(str(value)[:10])
