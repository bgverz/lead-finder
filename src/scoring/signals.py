"""Config-driven inferred affinity signals.

These tags are weak, inferred alignment signals based on Apollo/company/title
metadata and lead summary text. They are not verified interests.
"""

from __future__ import annotations

from src.models import Lead
from src.utils.config import Config


def apply_affinity_signals(lead: Lead, config: Config) -> Lead:
    """Populate inferred affinity tags and optional bonus score."""

    text = _signal_text(lead)
    tags: set[str] = set()

    tech_hit = _contains_any(text, config.signals.tech_keywords)
    investor_hit = _contains_any(text, config.signals.investor_keywords)
    networking_hit = _contains_any(text, config.signals.networking_keywords)
    real_estate_hit = _contains_any(text, config.signals.real_estate_keywords)
    healthcare_hit = _contains_any(text, config.signals.healthcare_keywords)

    if tech_hit:
        tags.add("AI/Tech")
    if networking_hit:
        tags.add("Startup Ecosystem")
    if real_estate_hit:
        tags.add("Real Estate")
    if healthcare_hit:
        tags.add("Healthcare")
    if investor_hit:
        tags.update(_investor_tags(text))

    lead.interest_tags = sorted(tags)
    lead.tech_signal = tech_hit
    lead.investor_signal = investor_hit
    lead.networking_signal = networking_hit
    lead.affinity_score = _affinity_bonus(lead, config)
    return lead


def _signal_text(lead: Lead) -> str:
    parts = [
        lead.apollo_title,
        lead.apollo_organization,
        lead.apollo_industry,
        lead.lead_summary,
        " ".join(lead.business_entity_names),
    ]
    return " ".join(part for part in parts if part).lower()


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords if keyword)


def _investor_tags(text: str) -> set[str]:
    tags: set[str] = set()
    if any(token in text for token in ("venture capital", " venture ", "ventures", " vc ")):
        tags.add("Venture Capital")
    if any(token in text for token in ("private equity", " pe ")):
        tags.add("Private Equity")
    if "family office" in text:
        tags.add("Family Office")
    if any(token in text for token in ("wealth", "asset management", "financial advisor")):
        tags.add("Wealth Management")
    if not tags:
        tags.add("Investor-Aligned")
    return tags


def _affinity_bonus(lead: Lead, config: Config) -> int:
    bonuses = config.scoring.affinity_bonuses or {}
    score = 0
    if lead.investor_signal:
        score += int(bonuses.get("investor_aligned_tags", 0) or 0)
    if "Startup Ecosystem" in lead.interest_tags:
        score += int(bonuses.get("startup_ecosystem_tags", 0) or 0)
    if any(tag in lead.interest_tags for tag in ("Venture Capital", "Private Equity", "Family Office")):
        score += int(bonuses.get("vc_pe_family_office_tags", 0) or 0)
    return score
