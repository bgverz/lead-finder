"""ATTOM property enrichment client.

Uses the trial-compatible property/address endpoint with conservative caching
and request limits. The endpoint is address-based, so leads without a usable
street address are skipped to avoid burning quota.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from src.models import Lead
from src.utils.config import Config
from src.utils.logger import setup_logger

logger = setup_logger("enrichment.attom")


@dataclass
class ATTOMTelemetry:
    requests_attempted: int = 0
    cache_hits: int = 0
    matches_found: int = 0
    unmatched_leads: int = 0
    skipped_insufficient_data: int = 0
    csv_addresses_loaded: int = 0
    rate_limit_warnings: int = 0
    quota_warnings: int = 0


@dataclass
class ATTOMPropertyMatch:
    property_address: str = ""
    estimated_value: float | None = None
    assessed_value: float | None = None
    property_type: str = ""
    owner_name: str = ""
    property_count: int | None = None
    confidence: float = 0
    signal: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class ATTOMClient:
    """Small ATTOM client for address lookup enrichment."""

    def __init__(self, config: Config):
        self.config = config
        self.api_key = config.api_keys.attom
        self.telemetry = ATTOMTelemetry()
        self.cache_path = Path(config.attom.cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = self._load_cache()

    def enrich_leads(self, leads: list[Lead]) -> list[Lead]:
        if self.config.sources.mode != "api" or not self.config.attom.enabled:
            return leads
        if not self.api_key:
            logger.warning("ATTOM enabled but ATTOM_API_KEY/api_keys.attom is missing.")
            return leads

        self._apply_csv_addresses(leads)
        seen_queries: set[str] = set()
        for lead in leads:
            address1, address2, basis = self._address_parts_for_lead(lead)
            if not address1 or not address2:
                self.telemetry.skipped_insufficient_data += 1
                continue

            cache_key = self._cache_key(address1, address2)
            if cache_key in seen_queries:
                self.telemetry.skipped_insufficient_data += 1
                lead.property_lookup_status = "duplicate_skipped"
                lead.property_lookup_reason = "Duplicate ATTOM address lookup already attempted this run."
                continue
            seen_queries.add(cache_key)

            lead.property_lookup_status = "attempted"
            lead.property_lookup_reason = f"ATTOM address lookup using {basis}."
            lead.address_needed = False
            match = self.lookup_address(address1, address2, lead)
            if not match:
                self.telemetry.unmatched_leads += 1
                if lead.property_lookup_status == "attempted":
                    lead.property_lookup_status = "unmatched"
                    lead.property_lookup_reason = "ATTOM returned no usable property match."
                continue
            if match.confidence < self.config.attom.min_match_confidence:
                self.telemetry.unmatched_leads += 1
                lead.property_lookup_status = "low_confidence"
                lead.property_lookup_reason = (
                    f"ATTOM match confidence {match.confidence:.2f} is below configured "
                    f"minimum {self.config.attom.min_match_confidence:.2f}."
                )
                logger.info(
                    "ATTOM low-confidence match skipped for %s (%s): %.2f",
                    lead.name,
                    basis,
                    match.confidence,
                )
                continue
            self._apply_match(lead, match)

        self._save_cache()
        self._log_telemetry()
        return leads

    def lookup_address(self, address1: str, address2: str, lead: Lead) -> ATTOMPropertyMatch | None:
        cache_key = self._cache_key(address1, address2)
        if cache_key in self._cache:
            self.telemetry.cache_hits += 1
            payload = self._cache[cache_key]
        else:
            if self.telemetry.requests_attempted >= self.config.attom.max_requests_per_run:
                self.telemetry.rate_limit_warnings += 1
                logger.warning(
                    "ATTOM request cap reached (%d); skipping remaining lookups.",
                    self.config.attom.max_requests_per_run,
                )
                return None
            payload = self._request_address(address1, address2)
            if payload is None:
                return None
            self._cache[cache_key] = payload

        properties = payload.get("property") or []
        if not properties:
            return None
        match = self._parse_property(properties[0], lead)
        if match:
            self.telemetry.matches_found += 1
        return match

    def _request_address(self, address1: str, address2: str) -> dict[str, Any] | None:
        url = f"{self.config.attom.base_url.rstrip('/')}/property/address"
        headers = {"APIKey": self.api_key, "Accept": "application/json"}
        params = {"address1": address1, "address2": address2}
        for attempt in range(1, self.config.attom.retry_attempts + 1):
            self.telemetry.requests_attempted += 1
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                self.telemetry.rate_limit_warnings += 1
                logger.warning("ATTOM rate-limit response for %s, %s.", address1, address2)
            if response.status_code in {402, 403}:
                self.telemetry.quota_warnings += 1
                logger.warning("ATTOM quota/permission response HTTP %s; stopping lookup.", response.status_code)
                return None
            if response.status_code >= 500 and attempt < self.config.attom.retry_attempts:
                time.sleep(self.config.attom.retry_backoff_seconds * attempt)
                continue
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("ATTOM address lookup failed for %s, %s: %s", address1, address2, exc)
                return None
            if self.config.attom.request_delay_seconds > 0:
                time.sleep(self.config.attom.request_delay_seconds)
            return response.json()
        return None

    def _parse_property(self, row: dict[str, Any], lead: Lead) -> ATTOMPropertyMatch:
        address = row.get("address") or {}
        avm = row.get("avm") or {}
        amount = avm.get("amount") or {}
        assessment = row.get("assessment") or {}
        assessed = assessment.get("assessed") or {}
        building = row.get("building") or {}
        summary = building.get("summary") or {}
        owner = row.get("owner") or {}

        owner_name = _first_present(
            owner.get("owner1", {}).get("fullName") if isinstance(owner.get("owner1"), dict) else "",
            owner.get("owner1", {}).get("fullname") if isinstance(owner.get("owner1"), dict) else "",
            owner.get("owner1", {}).get("name") if isinstance(owner.get("owner1"), dict) else "",
            owner.get("ownername1full"),
            owner.get("ownername1"),
            owner.get("absenteeownername"),
        )
        property_address = _format_attom_address(address)
        estimated_value = _number(amount.get("value") or amount.get("avmvalue"))
        assessed_value = _number(
            assessed.get("assdttlvalue")
            or assessed.get("assdtotalvalue")
            or assessed.get("taxamt")
            or assessment.get("assessedvalue")
        )
        property_type = _first_present(
            summary.get("proptype"),
            summary.get("propertyType"),
            row.get("summary", {}).get("proptype") if isinstance(row.get("summary"), dict) else "",
        )
        best_value = max(float(estimated_value or 0), float(assessed_value or 0))
        confidence = self._match_confidence(lead, owner_name, property_address)
        signal = _property_signal(best_value, confidence, owner_name, lead)
        return ATTOMPropertyMatch(
            property_address=property_address,
            estimated_value=estimated_value,
            assessed_value=assessed_value,
            property_type=property_type,
            owner_name=owner_name,
            property_count=_number(owner.get("propertycount")),
            confidence=confidence,
            signal=signal,
            raw=row,
        )

    def _match_confidence(self, lead: Lead, owner_name: str, property_address: str) -> float:
        confidence = 0.45
        if lead.property_address and _norm_street(lead.property_address) and _norm_street(lead.property_address) in _norm_street(property_address):
            confidence += 0.3
        owner_norm = _norm_name(owner_name)
        if owner_norm:
            name_norm = _norm_name(lead.name)
            org_norm = _norm_name(lead.apollo_organization)
            if name_norm and (name_norm in owner_norm or owner_norm in name_norm):
                confidence += 0.35
            elif org_norm and (org_norm in owner_norm or owner_norm in org_norm):
                confidence += 0.25
        if lead.apollo_person_id and not lead.property_address:
            confidence -= 0.15  # likely company/office address unless owner confirms.
        return max(0, min(1, round(confidence, 2)))

    def _apply_match(self, lead: Lead, match: ATTOMPropertyMatch) -> None:
        if not lead.property_address and match.property_address:
            lead.property_address = match.property_address
        lead.property_estimated_value = match.estimated_value
        lead.property_assessed_value = match.assessed_value
        lead.property_type = match.property_type
        lead.property_owner_name = match.owner_name
        lead.property_match_confidence = match.confidence
        lead.property_signal = match.signal
        if match.property_count and match.property_count > lead.property_count:
            lead.property_count = int(match.property_count)
        best_value = max(float(match.estimated_value or 0), float(match.assessed_value or 0))
        if match.confidence >= 0.7 and best_value > lead.property_value:
            lead.property_value = best_value
        if "attom_property" not in lead.source_notes:
            lead.source_notes = "; ".join(note for note in [lead.source_notes, "attom_property"] if note)
        lead.property_lookup_status = "matched"
        lead.property_lookup_reason = "ATTOM property/address match applied."
        lead.address_needed = False

    def _address_parts_for_lead(self, lead: Lead) -> tuple[str, str, str]:
        address1 = lead.property_address or lead.apollo_organization_address
        city = lead.city
        state = lead.state
        zip_code = lead.zip_code
        if not address1:
            if zip_code or (city and state):
                self._mark_needs_address(
                    lead,
                    "City/state/ZIP present, but street address is missing; ATTOM address endpoint skipped.",
                )
            else:
                lead.property_lookup_status = "insufficient_data"
                lead.property_lookup_reason = "Missing street address and city/state/ZIP for ATTOM lookup."
                lead.address_needed = True
            return "", "", "missing_address"
        if zip_code:
            return address1, zip_code, "zip"
        if city and state:
            return address1, f"{city}, {state}", "city_state"
        lead.property_lookup_status = "insufficient_data"
        lead.property_lookup_reason = "Street address present, but city/state or ZIP is missing for ATTOM lookup."
        lead.address_needed = False
        return "", "", "missing_city_state_or_zip"

    def _mark_needs_address(self, lead: Lead, reason: str) -> None:
        lead.property_lookup_status = "needs_address"
        lead.property_lookup_reason = reason
        lead.address_needed = True

    def _apply_csv_addresses(self, leads: list[Lead]) -> None:
        path = Path(self.config.attom.lead_addresses_path)
        if not path.exists():
            return
        try:
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            logger.warning("Unable to read ATTOM lead address CSV %s: %s", path, exc)
            return

        by_name: dict[str, dict[str, str]] = {}
        by_company: dict[str, dict[str, str]] = {}
        for row in rows:
            street = (row.get("street_address") or "").strip()
            if not street:
                continue
            name_key = _norm_name(row.get("name", ""))
            company_key = _norm_name(row.get("company", ""))
            if name_key:
                by_name.setdefault(name_key, row)
            if company_key:
                by_company.setdefault(company_key, row)

        for lead in leads:
            if lead.property_address:
                continue
            row = self._address_csv_match(lead, by_name, by_company)
            if not row:
                continue
            self._apply_csv_address_row(lead, row, path)

    def _address_csv_match(
        self,
        lead: Lead,
        by_name: dict[str, dict[str, str]],
        by_company: dict[str, dict[str, str]],
    ) -> dict[str, str] | None:
        name_key = _norm_name(lead.name)
        company_key = _norm_name(lead.apollo_organization)
        if name_key and name_key in by_name:
            return by_name[name_key]
        if company_key and company_key in by_company:
            return by_company[company_key]

        # Handle modest variations like legal suffixes or Apollo truncation.
        for candidate_key, row in by_company.items():
            if company_key and (company_key in candidate_key or candidate_key in company_key):
                return row
        for candidate_key, row in by_name.items():
            if name_key and (name_key in candidate_key or candidate_key in name_key):
                return row
        return None

    def _apply_csv_address_row(self, lead: Lead, row: dict[str, str], path: Path) -> None:
        lead.property_address = (row.get("street_address") or "").strip()
        lead.city = lead.city or (row.get("city") or "").strip()
        lead.state = lead.state or (row.get("state") or "").strip()
        lead.zip_code = lead.zip_code or (row.get("zip_code") or "").strip()
        lead.property_lookup_status = "address_loaded"
        lead.property_lookup_reason = f"Address loaded from {path} before ATTOM lookup."
        lead.address_needed = False
        source = (row.get("source") or "lead_addresses_csv").strip()
        note = f"address_csv:{source}"
        if note not in lead.source_notes:
            lead.source_notes = "; ".join(part for part in [lead.source_notes, note] if part)
        self.telemetry.csv_addresses_loaded += 1

    def _cache_key(self, address1: str, address2: str) -> str:
        return f"{address1.strip().lower()}|{address2.strip().lower()}"

    def _load_cache(self) -> dict[str, dict]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self._cache, indent=2, sort_keys=True))

    def _log_telemetry(self) -> None:
        logger.info(
            "ATTOM telemetry — requests attempted: %d | cache hits: %d | matches found: %d | "
            "unmatched leads: %d | skipped insufficient data: %d | CSV addresses loaded: %d | "
            "rate-limit warnings: %d | quota warnings: %d",
            self.telemetry.requests_attempted,
            self.telemetry.cache_hits,
            self.telemetry.matches_found,
            self.telemetry.unmatched_leads,
            self.telemetry.skipped_insufficient_data,
            self.telemetry.csv_addresses_loaded,
            self.telemetry.rate_limit_warnings,
            self.telemetry.quota_warnings,
        )


def _format_attom_address(address: dict[str, Any]) -> str:
    line1 = _first_present(address.get("line1"), address.get("oneLine"), address.get("address1"))
    if line1 and "," in line1:
        return line1
    city = _first_present(address.get("locality"), address.get("city"))
    state = _first_present(address.get("countrySubd"), address.get("state"))
    postal = _first_present(address.get("postal1"), address.get("postalCode"), address.get("zip"))
    parts = [line1, city, state, postal]
    return ", ".join(part for part in parts if part)


def _property_signal(value: float, confidence: float, owner_name: str, lead: Lead) -> str:
    if confidence < 0.7:
        return "Tentative ATTOM match - verify ownership"
    if value >= 3_000_000:
        return "Luxury/high-value property ownership"
    if value >= 2_000_000:
        return "High-value property ownership"
    if value >= 1_000_000:
        return "Property ownership supports accredited-investor likelihood"
    if owner_name:
        return "Property ownership match"
    return "ATTOM property match"


def _number(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> str:
    for value in values:
        if value not in (None, "", "null"):
            return str(value).strip()
    return ""


def _norm_name(value: str) -> str:
    return " ".join(str(value or "").lower().replace(".", "").replace(",", "").split())


def _norm_street(value: str) -> str:
    return " ".join(str(value or "").lower().replace(".", "").replace(",", "").split())
