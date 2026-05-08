"""Phone validation abstraction."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from lead_pipeline.models import ContactInfo
from lead_pipeline.utils.config import Config


class PhoneValidator:
    """Validate phone data when available."""

    def __init__(self, config: Config):
        self.config = config
        self._contacts = self._load_sample() if config.sources.mode == "sample" else {}

    def validate_for_name(self, name: str) -> ContactInfo:
        if self.config.sources.mode == "sample":
            return self._contacts.get(_norm(name), ContactInfo())

        if not self.config.api_keys.numverify:
            return ContactInfo(source="numverify_missing_key")
        raise NotImplementedError(
            "NumVerify adapter boundary is ready. Expected request: "
            "GET http://apilayer.net/api/validate?access_key=...&number=..."
        )

    def validate_number(self, phone: str) -> ContactInfo:
        if not phone:
            return ContactInfo(source="missing_phone")
        if self.config.sources.mode == "api" and self.config.api_keys.numverify:
            response = requests.get(
                "http://apilayer.net/api/validate",
                params={"access_key": self.config.api_keys.numverify, "number": phone},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return ContactInfo(
                phone=phone,
                phone_valid=bool(data.get("valid")),
                phone_line_type=str(data.get("line_type", "")),
                source="numverify",
            )
        return ContactInfo(phone=phone, phone_valid=True, phone_line_type="unknown")

    def _load_sample(self) -> dict[str, ContactInfo]:
        path = Path(self.config.sources.sample_contacts)
        if not path.exists():
            return {}
        frame = pd.read_csv(path)
        return {
            _norm(str(row.get("name", ""))): ContactInfo(
                phone=str(row.get("phone", "") or ""),
                phone_valid=bool(row.get("phone_valid", False)),
                phone_line_type=str(row.get("phone_line_type", "") or ""),
                email=str(row.get("email", "") or ""),
                source=str(row.get("source", "sample_contacts")),
            )
            for row in frame.to_dict("records")
        }


def _norm(value: str) -> str:
    return " ".join(value.lower().replace(".", "").split())
