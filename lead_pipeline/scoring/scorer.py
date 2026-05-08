"""Configurable 100-point lead scoring engine."""

from __future__ import annotations

from datetime import date, timedelta

from lead_pipeline.models import Lead, apollo_title_tier
from lead_pipeline.scoring.signals import apply_affinity_signals
from lead_pipeline.utils.config import Config

# Points awarded per title tier (out-of-band from the 100-pt weight budget).
_TITLE_TIER_POINTS: dict[str, int] = {
    "top": 35,     # Founder, Co-Founder, CEO, President, Owner, Chairman
    "high": 28,    # Managing Partner, Partner, MD, Investor, Board Member
    "medium": 20,  # Principal
    "low": 10,     # Any other title that passed inclusion/exclusion filters
}

# Org name keywords that suggest an investment / private-market firm.
_INVESTOR_ORG_KEYWORDS: frozenset[str] = frozenset({
    "capital", "capitals", "ventures", "venture", "partners", "fund", "funds",
    "investment", "investments", "equity", "management", "advisors", "advisory",
    "wealth", "asset", "assets", "holdings", "family office", "financial",
    "securities", "finance", "realty", "real estate", "properties",
})


class LeadScorer:
    """Score and tier leads using the YAML-driven model."""

    def __init__(self, config: Config):
        self.config = config
        self.weights = config.scoring.weights
        self.tiers = config.scoring.tiers

    def score(self, lead: Lead, as_of: date | None = None) -> Lead:
        as_of = as_of or date.today()
        lead.recency_signal = lead.recency_signal or self._has_recent_signal(lead, as_of)

        lead.property_score = self._property_value_points(self._scoring_property_value(lead))
        if (
            lead.property_match_confidence >= 0.85
            and lead.apollo_person_id
            and apollo_title_tier(lead.apollo_title or "") in {"top", "high"}
            and lead.property_score > 0
        ):
            lead.property_score = min(33, lead.property_score + 3)
        multi_property_score = self.weights.multi_property if lead.property_count >= 2 else 0
        lead.business_score = self._business_points(lead) + multi_property_score
        lead.sec_score = self.weights.sec_filing_match if lead.sec_match else 0
        lead.area_score = self._area_wealth_points(lead.area_income)
        lead.phone_score = self._phone_points(lead)
        lead.recency_score = self.weights.recency_signal if lead.recency_signal else 0
        lead.apollo_signal_score = self._apollo_signal_points(lead)
        apply_affinity_signals(lead, self.config)

        score = (
            lead.property_score
            + lead.business_score
            + lead.sec_score
            + lead.area_score
            + lead.phone_score
            + lead.recency_score
            + lead.apollo_signal_score
            + lead.affinity_score
        )

        lead.lead_score = min(100, round(score, 2))
        lead.score_tier = self.assign_tier(lead.lead_score)
        return lead

    def assign_tier(self, score: float) -> str:
        if score >= self.tiers["hot"]:
            return "Hot"
        if score >= self.tiers["warm"]:
            return "Warm"
        if score >= self.tiers["cool"]:
            return "Cool"
        return "Skip"

    def _property_value_points(self, value: float) -> int:
        if value >= 3_000_000:
            return self.weights.property_value
        if value >= 2_000_000:
            return 22
        if value >= 1_500_000:
            return 12
        return 0

    def _scoring_property_value(self, lead: Lead) -> float:
        """Use ATTOM values only when confidence is strong enough."""
        base = float(lead.property_value or 0)
        attom_value = max(
            float(lead.property_estimated_value or 0),
            float(lead.property_assessed_value or 0),
        )
        if lead.property_match_confidence >= 0.7:
            return max(base, attom_value)
        if lead.property_match_confidence >= 0.45 and attom_value >= 2_000_000:
            # Weak/tentative matches get capped evidence so they do not dominate.
            return max(base, 1_500_000)
        return base

    def _business_points(self, lead: Lead) -> int:
        if not lead.business_entities:
            return 0
        base = 0
        for entity in lead.business_entities:
            entity_type = entity.entity_type.lower()
            role = entity.role.lower()
            if "corp" in entity_type or any(token in role for token in ("officer", "president", "ceo", "director")):
                base = max(base, self.weights.business_ownership)
            elif "llc" in entity_type or "member" in role or "manager" in role:
                base = max(base, 18)
            else:
                base = max(base, 12)
        if len(lead.business_entities) > 1:
            base += 5
        return min(self.weights.business_ownership, base)

    def _area_wealth_points(self, income: float | None) -> int:
        if income is None:
            return 0
        if income >= 150_000:
            return self.weights.area_wealth_index
        if income >= 100_000:
            return 6
        return 0

    def _phone_points(self, lead: Lead) -> int:
        if lead.phone_valid:
            line_type = lead.phone_line_type.lower()
            if line_type == "mobile":
                return self.weights.phone_reachability
            if line_type == "landline":
                return 5
            return 0
        # Partial credit for an Apollo contact-availability flag (unverified).
        if lead.apollo_has_direct_phone and lead.apollo_obfuscated:
            return self.weights.phone_reachability // 2
        return 0

    def _apollo_signal_points(self, lead: Lead) -> float:
        """Out-of-band signal score for Apollo leads.

        Title tier gives a wide spread so strong and weak candidates separate
        clearly.  Org and contact flags add modest bonuses.  None of this
        masquerades as verified property / business / contact data.
        """
        if not lead.apollo_person_id:
            return 0

        tier = apollo_title_tier(lead.apollo_title or "")
        title_pts = _TITLE_TIER_POINTS.get(tier, 0) if lead.apollo_title else 0
        org_pts = 5 if lead.apollo_organization else 0
        email_flag_pts = 5 if lead.apollo_has_email else 0
        investor_org_pts = self._investor_org_signal(lead.apollo_organization)

        return title_pts + org_pts + email_flag_pts + investor_org_pts

    def _investor_org_signal(self, org_name: str) -> float:
        """Extra points when the org name suggests a private investment firm."""
        if not org_name:
            return 0
        org_lower = org_name.lower()
        # Count distinct investor keywords present in the org name.
        hits = sum(1 for kw in _INVESTOR_ORG_KEYWORDS if kw in org_lower)
        return min(hits * 3, 9)  # cap at 9 pts (3 matching keywords)

    def _has_recent_signal(self, lead: Lead, as_of: date) -> bool:
        cutoff = as_of - timedelta(days=730)
        if lead.purchase_date and lead.purchase_date >= cutoff:
            return True
        return any(entity.filing_date and entity.filing_date >= cutoff for entity in lead.business_entities)
