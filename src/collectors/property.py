"""Property record ingestion and public/API adapter boundary."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.models import PropertyRecord, TargetArea
from src.utils.config import Config
from src.utils.logger import setup_logger

logger = setup_logger("collectors.property")


class PropertyRecordCollector:
    """Load property records from sample CSV or a configured API adapter."""

    def __init__(self, config: Config):
        self.config = config

    def collect(self, target_areas: list[TargetArea]) -> list[PropertyRecord]:
        if self.config.sources.mode == "api":
            if not self.config.api_keys.attom:
                raise RuntimeError(
                    "ATTOM/property API mode requires api_keys.attom. "
                    "Use sources.mode: sample to run locally without paid APIs."
                )
            logger.info(
                "ATTOM property/address enrichment is enabled and runs after leads are created; "
                "no bulk property records are collected from target areas."
            )
            return []

        path = Path(self.config.sources.sample_properties)
        if not path.exists():
            raise FileNotFoundError(f"Sample property file not found: {path}")
        frame = pd.read_csv(path)

        area_codes = {area.code for area in target_areas if area.geography_type in {"zip", "state"}}
        has_zip_targets = any(area.geography_type == "zip" for area in target_areas)
        has_state_targets = any(area.geography_type == "state" for area in target_areas)

        records: list[PropertyRecord] = []
        for row in frame.to_dict("records"):
            zip_code = str(row.get("zip_code", "")).zfill(5)
            state = str(row.get("state", "")).upper()
            if has_zip_targets and zip_code not in area_codes:
                continue
            if has_state_targets and state not in area_codes:
                continue
            if float(row.get("property_value", 0) or 0) < self.config.targeting.min_property_value:
                continue
            records.append(
                PropertyRecord(
                    owner_name=str(row["owner_name"]).strip(),
                    property_address=str(row["property_address"]).strip(),
                    city=str(row.get("city", "")).strip(),
                    state=state,
                    zip_code=zip_code,
                    property_value=float(row["property_value"]),
                    owner_type=str(row.get("owner_type", "individual")).strip(),
                    purchase_date=_parse_date(row.get("purchase_date")),
                    source=str(row.get("source", "sample_property_records")),
                    area_income=_optional_float(row.get("area_income")),
                    area_home_value=_optional_float(row.get("area_home_value")),
                )
            )
        return records


def _parse_date(value: object) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return date.fromisoformat(str(value)[:10])


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value) or value == "":
        return None
    return float(value)
