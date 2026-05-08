"""Shared data models for pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Apollo title-tier classification — shared by Lead and LeadScorer.
# ---------------------------------------------------------------------------
_TOP_TITLES: tuple[str, ...] = (
    "chief investment officer",
    "chief executive officer",
    "co-founder",
    "founder",
    "owner",
    "chairman",
    "ceo",
    "cio",
)
_HIGH_TITLES: tuple[str, ...] = (
    "chief financial officer",
    "chief operating officer",
    "managing partner",
    "managing director",
    "board member",
    "president",
    "partner",
    "investor",
    "cfo",
    "coo",
)
_MEDIUM_TITLES: tuple[str, ...] = (
    "chief technology officer",
    "principal",
    "cto",
)


def apollo_title_tier(title: str) -> str:
    """Return 'top', 'high', 'medium', or 'low' for an Apollo job title."""
    t = title.lower()
    if any(tok in t for tok in _TOP_TITLES):
        return "top"
    if any(tok in t for tok in _HIGH_TITLES):
        return "high"
    if any(tok in t for tok in _MEDIUM_TITLES):
        return "medium"
    return "low"


def apollo_title_signal_phrase(title: str) -> str:
    """Return C-suite-aware summary language for an Apollo title."""

    t = title.lower()
    if any(tok in t for tok in ("founder", "co-founder", "owner", "chairman")):
        return "ownership/operator signal"
    if any(tok in t for tok in ("chief investment officer", "cio", "chief financial officer", "cfo")):
        return "financial decision-maker signal"
    if any(tok in t for tok in ("chief technology officer", "cto")):
        return "technology operator signal"
    if any(tok in t for tok in ("ceo", "chief executive officer", "president", "chief operating officer", "coo")):
        return "senior executive signal"
    if "chief" in t:
        return "generic chief-title signal"
    tier = apollo_title_tier(title)
    if tier == "top":
        return "ownership/operator signal"
    if tier == "high":
        return "senior executive signal"
    if tier == "medium":
        return "operator signal"
    return "limited role signal"


@dataclass
class TargetArea:
    """A target geography with wealth signals."""

    geography_type: str
    code: str
    state: str = ""
    county: str = ""
    metro: str = ""
    median_income: float | None = None
    median_home_value: float | None = None
    population: int | None = None
    source: str = "sample"


@dataclass
class PropertyRecord:
    """A public property record normalized for lead creation."""

    owner_name: str
    property_address: str
    city: str
    state: str
    zip_code: str
    property_value: float
    owner_type: str = "individual"
    purchase_date: date | None = None
    source: str = "sample_property_records"
    area_income: float | None = None
    area_home_value: float | None = None


@dataclass
class BusinessEntity:
    """A business entity linked to a prospect."""

    name: str
    role: str
    entity_type: str = ""
    filing_date: date | None = None
    source: str = "sample_business_records"


@dataclass
class ContactInfo:
    """Minimal contact validation result."""

    phone: str = ""
    phone_valid: bool = False
    phone_line_type: str = ""
    email: str = ""
    source: str = "sample_contacts"


@dataclass
class Lead:
    """A fully normalized prospect record."""

    name: str
    property_value: float
    property_address: str
    city: str = ""
    state: str = ""
    zip_code: str = ""
    owner_type: str = "individual"
    purchase_date: date | None = None
    business_entities: list[BusinessEntity] = field(default_factory=list)
    sec_match: bool = False
    sec_details: list[dict] = field(default_factory=list)
    area_income: float | None = None
    area_home_value: float | None = None
    phone: str = ""
    phone_valid: bool = False
    phone_line_type: str = ""
    email: str = ""
    property_count: int = 1
    recency_signal: bool = False
    lead_score: float = 0
    score_tier: str = "Skip"
    source_notes: str = ""
    apollo_person_id: str = ""
    apollo_first_name: str = ""
    apollo_last_name_obfuscated: str = ""
    apollo_title: str = ""
    apollo_organization: str = ""
    apollo_organization_address: str = ""
    apollo_industry: str = ""
    apollo_has_email: bool = False
    apollo_has_direct_phone: bool = False
    apollo_obfuscated: bool = False
    interest_tags: list[str] = field(default_factory=list)
    tech_signal: bool = False
    investor_signal: bool = False
    networking_signal: bool = False
    affinity_score: float = 0
    property_estimated_value: float | None = None
    property_assessed_value: float | None = None
    property_type: str = ""
    property_owner_name: str = ""
    property_match_confidence: float = 0
    property_signal: str = ""
    property_lookup_status: str = ""
    property_lookup_reason: str = ""
    address_needed: bool = False
    property_score: float = 0
    business_score: float = 0
    sec_score: float = 0
    area_score: float = 0
    phone_score: float = 0
    recency_score: float = 0
    apollo_signal_score: float = 0

    @property
    def business_entity_names(self) -> list[str]:
        return [entity.name for entity in self.business_entities if entity.name]

    @property
    def entity_count(self) -> int:
        return len(self.business_entities)

    @property
    def entity_types(self) -> list[str]:
        return sorted(
            {
                entity.entity_type.strip()
                for entity in self.business_entities
                if entity.entity_type and entity.entity_type.strip()
            }
        )

    @property
    def is_multi_entity_owner(self) -> bool:
        return self.entity_count > 1

    @property
    def sec_match_count(self) -> int:
        return len(self.sec_details) if self.sec_details else int(self.sec_match)

    @property
    def sec_forms(self) -> list[str]:
        return sorted(
            {
                str(detail.get("form_type", "")).strip()
                for detail in self.sec_details
                if str(detail.get("form_type", "")).strip()
            }
        )

    @property
    def sec_last_filing_date(self) -> str:
        dates = [
            str(detail.get("filing_date", "")).strip()
            for detail in self.sec_details
            if str(detail.get("filing_date", "")).strip()
        ]
        return max(dates) if dates else ""

    @property
    def sec_recent_match(self) -> bool:
        last_filing = self.sec_last_filing_date
        if not last_filing:
            return False
        try:
            filing_date = date.fromisoformat(last_filing[:10])
        except ValueError:
            return False
        return filing_date >= date.today() - timedelta(days=730)

    @property
    def lead_summary(self) -> str:
        if self.apollo_person_id and not self.property_value and not self.property_estimated_value and not self.property_assessed_value:
            return self._apollo_lead_summary()

        value = _format_currency(self.property_value)
        if self.apollo_person_id and (self.property_estimated_value or self.property_assessed_value):
            return self._apollo_property_summary()
        has_business = self.entity_count > 0
        has_sec = self.sec_match_count > 0
        phone_phrase = self._phone_summary_phrase()

        if has_business or has_sec:
            parts = [f"Owns {value} property"]
            if has_business:
                parts.append(
                    f"linked to {self.entity_count} business "
                    f"{'entity' if self.entity_count == 1 else 'entities'}"
                )
            if has_sec:
                parts.append("appears in SEC filings")
            if phone_phrase:
                parts.append(phone_phrase)
            return ", ".join(parts) + "."

        if self.area_income and self.area_income >= 150_000:
            return (
                "High-value property owner in a wealthy area; "
                "no business or SEC match yet — worth a quick profile check."
            )

        return "Property-led prospect; limited enrichment data available — low research priority."

    def _apollo_property_summary(self) -> str:
        title_signal = apollo_title_signal_phrase(self.apollo_title or "")
        if self._best_property_value() >= 2_000_000:
            if "founder" in (self.apollo_title or "").lower() or "owner" in (self.apollo_title or "").lower():
                return f"Founder signal + matched high-value property ({_format_currency(self._best_property_value())})."
            if apollo_title_tier(self.apollo_title or "") in ("top", "high"):
                return f"Executive/operator with luxury property ownership ({_format_currency(self._best_property_value())})."
            return "Property ownership supports accredited-investor likelihood."
        if self.property_match_confidence >= 0.7:
            return f"{title_signal.capitalize()} with matched property ownership."
        return f"{title_signal.capitalize()} with tentative property signal; verify ownership before relying on it."

    def _apollo_lead_summary(self) -> str:
        """Sales-oriented summary for Apollo-sourced leads."""
        title = self.apollo_title or "Executive"
        company = f" at {self.apollo_organization}" if self.apollo_organization else ""
        signal = apollo_title_signal_phrase(self.apollo_title or "")

        # Build context bullets.
        context: list[str] = []
        if self.sec_match:
            context.append("SEC filing match found")
        if self.apollo_obfuscated:
            context.append("reveal contact before outreach")
        elif self.apollo_has_email and not self.email:
            context.append("email available after export")
        if self.apollo_has_direct_phone and not self.phone_valid:
            context.append("direct phone available after reveal/export")

        body = f"{title}{company} — {signal}"
        if context:
            body += f"; {'; '.join(context)}"
        return body + "."

    @property
    def call_priority(self) -> str:
        valid_phone = self.phone_valid and bool(self.phone)
        line_type = self.phone_line_type.lower()
        if self.score_tier == "Hot" and valid_phone and line_type == "mobile":
            return "Call First"
        if self.score_tier == "Hot":
            return "Research First"
        if self.score_tier == "Warm" and valid_phone:
            return "Call"
        if self.score_tier == "Cool":
            return "Low Priority"
        return "Skip"

    @property
    def next_action(self) -> str:
        """Recommended next step based on available data and score tier."""
        if self.address_needed or self.property_lookup_status == "needs_address":
            return "Reveal/export address before ATTOM property lookup"
        if self.apollo_person_id:
            tier = apollo_title_tier(self.apollo_title or "")
            if self.apollo_obfuscated:
                if tier in ("top", "high"):
                    return "Reveal in Apollo – high priority"
                if tier == "medium":
                    return "Reveal in Apollo – verify first"
                return "Skip – weak role"
            if not self.email and not self.phone:
                return "Export from Apollo/ZoomInfo"
        if self.phone_valid and self.phone_line_type.lower() == "mobile":
            return "Call mobile"
        if self.phone_valid and self.phone:
            return "Call"
        if self.score_tier in ("Hot", "Warm"):
            return "Research + Outreach"
        if self.property_value > 0 and not self.business_entities and self.score_tier != "Skip":
            return "Research property/business ownership"
        if self.property_match_confidence > 0 and self.property_match_confidence < 0.7:
            return "Verify ATTOM property match"
        if self.score_tier == "Skip" and not self.apollo_person_id:
            return "Skip"
        return "Research"

    @property
    def data_confidence(self) -> str:
        has_property = bool(self.property_value and self.property_address)
        has_business = self.entity_count > 0
        has_contact = self.phone_valid and bool(self.phone)
        has_area = self.area_income is not None
        enrichment_count = sum([has_business, self.sec_match_count > 0, has_contact, has_area])

        if has_property and has_business and has_contact and has_area:
            return "High"
        if has_property and enrichment_count >= 1:
            return "Medium"
        return "Low"

    def _phone_summary_phrase(self) -> str:
        if not self.phone_valid or not self.phone:
            return ""
        line_type = self.phone_line_type.lower()
        if line_type == "mobile":
            return "mobile reachable"
        if line_type == "landline":
            return "landline reachable"
        return "phone reachable"

    def to_output_dict(self) -> dict:
        """Return the stable export schema required by the project plan."""

        return {
            "name": self.name,
            "lead_score": self.lead_score,
            "score_tier": self.score_tier,
            "next_action": self.next_action,
            "lead_summary": self.lead_summary,
            "call_priority": self.call_priority,
            "data_confidence": self.data_confidence,
            "phone": self.phone,
            "phone_line_type": self.phone_line_type,
            "property_value": self.property_value,
            "property_estimated_value": self.property_estimated_value,
            "property_assessed_value": self.property_assessed_value,
            "property_address": self.property_address,
            "property_match_confidence": self.property_match_confidence,
            "property_signal": self.property_signal,
            "property_lookup_status": self.property_lookup_status,
            "property_lookup_reason": self.property_lookup_reason,
            "address_needed": self.address_needed,
            "property_type": self.property_type,
            "property_owner_name": self.property_owner_name,
            "business_entities": "; ".join(self.business_entity_names),
            "entity_count": self.entity_count,
            "sec_match": self.sec_match,
            "sec_match_count": self.sec_match_count,
            "area_income": self.area_income,
            "recency_signal": self.recency_signal,
            "interest_tags": "; ".join(self.interest_tags),
            "tech_signal": self.tech_signal,
            "investor_signal": self.investor_signal,
            "networking_signal": self.networking_signal,
            "source_notes": self.source_notes,
            "entity_types": "; ".join(self.entity_types),
            "is_multi_entity_owner": self.is_multi_entity_owner,
            "sec_forms": "; ".join(self.sec_forms),
            "sec_recent_match": self.sec_recent_match,
            "sec_last_filing_date": self.sec_last_filing_date,
            "property_score": self.property_score,
            "business_score": self.business_score,
            "sec_score": self.sec_score,
            "area_score": self.area_score,
            "phone_score": self.phone_score,
            "recency_score": self.recency_score,
            "affinity_score": self.affinity_score,
            "apollo_signal_score": self.apollo_signal_score,
            "apollo_person_id": self.apollo_person_id,
            "apollo_first_name": self.apollo_first_name,
            "apollo_last_name_obfuscated": self.apollo_last_name_obfuscated,
            "apollo_title": self.apollo_title,
            "apollo_organization": self.apollo_organization,
            "apollo_organization_address": self.apollo_organization_address,
            "apollo_industry": self.apollo_industry,
            "apollo_has_email": self.apollo_has_email,
            "apollo_has_direct_phone": self.apollo_has_direct_phone,
            "apollo_obfuscated": self.apollo_obfuscated,
            "owner_type": self.owner_type,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "property_count": self.property_count,
            "area_home_value": self.area_home_value,
            "email": self.email,
        }

    def _best_property_value(self) -> float:
        return max(
            float(self.property_value or 0),
            float(self.property_estimated_value or 0),
            float(self.property_assessed_value or 0),
        )


def _format_currency(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"
