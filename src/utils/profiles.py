"""Built-in Apollo search profiles for different accredited investor segments.

Each profile overrides person_titles and (optionally) employee count bounds.
The base config's exclusion lists always stay in effect regardless of profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchProfile:
    name: str
    description: str
    person_titles: tuple[str, ...]
    employee_count_min: int = 1
    employee_count_max: int = 500  # 0 = no upper bound


PROFILES: dict[str, SearchProfile] = {
    "vc_pe": SearchProfile(
        name="vc_pe",
        description="Venture capital and private equity professionals",
        person_titles=(
            "Partner",
            "Managing Partner",
            "Managing Director",
            "Investor",
            "General Partner",
            "Venture Partner",
            "Principal",
            "Portfolio Manager",
            "Investment Director",
            "Board Member",
        ),
        employee_count_max=200,
    ),
    "founders": SearchProfile(
        name="founders",
        description="Founders and operators of private companies",
        person_titles=(
            "Founder",
            "Co-Founder",
            "CEO",
            "President",
            "Owner",
            "Chairman",
            "Entrepreneur",
            "Co-CEO",
        ),
        employee_count_max=1_000,
    ),
    "family_office": SearchProfile(
        name="family_office",
        description="Family office and private wealth management professionals",
        person_titles=(
            "Family Office",
            "Chief Investment Officer",
            "Managing Director",
            "Wealth Manager",
            "Portfolio Manager",
            "President",
            "Principal",
            "Investment Manager",
        ),
        employee_count_max=100,
    ),
    "real_estate": SearchProfile(
        name="real_estate",
        description="Real estate founders, developers, and investors",
        person_titles=(
            "Founder",
            "CEO",
            "Owner",
            "Principal",
            "Managing Partner",
            "Developer",
            "Managing Director",
            "President",
            "Partner",
        ),
        employee_count_max=500,
    ),
    "healthcare": SearchProfile(
        name="healthcare",
        description="Healthcare and biotech founders and executives",
        person_titles=(
            "Founder",
            "CEO",
            "Co-Founder",
            "Chief Medical Officer",
            "Managing Partner",
            "Principal",
            "Owner",
            "President",
        ),
        employee_count_max=500,
    ),
    "broad_hnw": SearchProfile(
        name="broad_hnw",
        description="Broad high-net-worth search across all investor/founder roles",
        person_titles=(
            "Founder",
            "Co-Founder",
            "CEO",
            "President",
            "Managing Partner",
            "Partner",
            "Owner",
            "Chairman",
            "Board Member",
            "Investor",
            "Managing Director",
            "Principal",
            "Family Office",
            "Chief Investment Officer",
            "General Partner",
            "Venture Partner",
        ),
        employee_count_max=2_000,
    ),
    "c_suite": SearchProfile(
        name="c_suite",
        description=(
            "C-level executives at small and mid-sized companies with plausible "
            "ownership, operator, investment, or financial decision-maker signal"
        ),
        person_titles=(
            "CEO",
            "Chief Executive Officer",
            "Founder",
            "Co-Founder",
            "Owner",
            "President",
            "Chairman",
            "CFO",
            "Chief Financial Officer",
            "CIO",
            "Chief Investment Officer",
            "COO",
            "Chief Operating Officer",
            "CTO",
            "Chief Technology Officer",
        ),
        employee_count_min=5,
        employee_count_max=500,
    ),
}


def list_profiles() -> list[str]:
    return list(PROFILES.keys())


def get_profile(name: str) -> SearchProfile:
    if name not in PROFILES:
        available = ", ".join(PROFILES.keys())
        raise ValueError(f"Unknown profile '{name}'. Available profiles: {available}")
    return PROFILES[name]
