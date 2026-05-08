"""Apollo.io search and optional contact reveal adapter."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import requests

from lead_pipeline.utils.config import Config
from lead_pipeline.utils.logger import setup_logger

logger = setup_logger("enrichment.apollo")

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_REVEAL_URL_TEMPLATE = "https://api.apollo.io/api/v1/people/{person_id}"

# Country name variants that map to ISO "US".
_US_COUNTRY_NAMES: frozenset[str] = frozenset({
    "us", "usa", "united states", "united states of america",
    "u.s.", "u.s.a.", "u.s",
})

# Apollo employee-count range labels in ascending order.
_EMPLOYEE_RANGE_BUCKETS: list[tuple[int, int | None, str]] = [
    (1, 10, "1,10"),
    (11, 50, "11,50"),
    (51, 200, "51,200"),
    (201, 500, "201,500"),
    (501, 1000, "501,1000"),
    (1001, 5000, "1001,5000"),
    (5001, 10000, "5001,10000"),
    (10001, None, "10001,"),
]


def _build_employee_ranges(min_count: int, max_count: int) -> list[str]:
    """Return Apollo range strings that overlap with [min_count, max_count]."""
    ranges: list[str] = []
    for low, high, label in _EMPLOYEE_RANGE_BUCKETS:
        if max_count > 0 and low > max_count:
            continue
        if high is not None and high < (min_count or 1):
            continue
        ranges.append(label)
    return ranges


@dataclass
class ApolloPerson:
    """A normalized Apollo search result."""

    apollo_person_id: str
    first_name: str = ""
    last_name: str = ""
    last_name_obfuscated: str = ""
    title: str = ""
    organization_name: str = ""
    organization_address: str = ""
    industry: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    email: str = ""
    phone: str = ""
    has_email: bool = False
    has_direct_phone: bool = False
    has_mobile_phone: bool = False
    is_obfuscated: bool = False
    is_recycled: bool = False  # True when surfaced via cooldown fallback
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        parts = [self.first_name, self.last_name or self.last_name_obfuscated]
        return " ".join(part for part in parts if part).strip() or self.organization_name or "Apollo Prospect"

    @property
    def has_full_name(self) -> bool:
        return bool(self.first_name and self.last_name and not self.is_obfuscated)

    @property
    def company_or_title(self) -> str:
        return self.organization_name or self.title


class ApolloClient:
    """Apollo adapter using api_search, with reveal calls disabled by default."""

    def __init__(self, config: Config):
        self.config = config
        self.api_key = config.api_keys.apollo
        self.session = requests.Session()
        # Updated after every search_people call.
        self.last_stats: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_people(
        self,
        seen_ids: set[str] | None = None,
    ) -> list[ApolloPerson]:
        """Search Apollo people endpoint and return normalized candidates.

        ``seen_ids`` is a set of Apollo person IDs to skip (run-diversity
        deduplication).  Pass an empty set or None to skip no one.
        Telemetry is stored in ``self.last_stats`` after each call.
        """
        if not self.config.apollo.enabled:
            return []
        if not self.api_key:
            logger.warning("Apollo enabled but APOLLO_API_KEY/api_keys.apollo is missing.")
            return []

        start_page = self._start_page()
        base_payload = self._build_base_payload()
        self._log_query_info(base_payload, start_page)

        people = self._fetch_pages(base_payload, start_page)

        # If the random start page returned nothing, fall back to page 1.
        if not people and start_page > 1:
            logger.info(
                "Apollo page %d returned 0 results; falling back to page 1.", start_page
            )
            people = self._fetch_pages(base_payload, 1)

        raw_count = len(people)
        people, stats = self._apply_client_filters(people, seen_ids or set())
        stats["raw_retrieved"] = raw_count
        stats["final_kept"] = len(people)
        self.last_stats = stats

        obfuscated = sum(p.is_obfuscated for p in people)
        if obfuscated:
            logger.warning(
                "Apollo search returned %d obfuscated candidates; "
                "keeping leads with missing contact fields.",
                obfuscated,
            )
        return people

    def reveal_contact(self, person: ApolloPerson) -> ApolloPerson:
        """Optionally retrieve full contact details when the account is permitted."""
        if not self.config.apollo.reveal_contacts:
            return person
        if not person.apollo_person_id:
            logger.warning("Skipping Apollo reveal because person id is missing.")
            return person

        response = self.session.get(
            APOLLO_REVEAL_URL_TEMPLATE.format(person_id=person.apollo_person_id),
            headers=self._headers(),
            timeout=30,
        )
        if response.status_code in {402, 403}:
            logger.warning(
                "Apollo reveal was denied; contact reveal may require additional permissions or credits."
            )
            return person
        response.raise_for_status()
        data = response.json().get("person") or response.json()
        return self._parse_person({**person.raw, **data})

    def search_probe(self) -> tuple[bool, bool, str]:
        """Check api_search connectivity with per_page=1 for doctor."""
        if not self.api_key:
            return False, False, "APOLLO_API_KEY not set"
        probe_payload = {**self._build_base_payload(), "page": 1, "per_page": 1}
        response = self.session.post(
            APOLLO_SEARCH_URL,
            headers=self._headers(),
            json=probe_payload,
            timeout=30,
        )
        if response.status_code >= 400:
            return False, False, f"HTTP {response.status_code}: {response.text[:160]}"
        rows = response.json().get("people") or response.json().get("contacts") or []
        if not rows:
            return True, False, "connected; no people returned for current filters"
        person = self._parse_person(rows[0])
        return True, person.is_obfuscated, "connected"

    # ------------------------------------------------------------------
    # Payload / filter helpers
    # ------------------------------------------------------------------

    def _start_page(self) -> int:
        limit = self.config.apollo.random_page_offset_max
        if limit and limit > 1:
            return random.randint(1, limit)
        return 1

    def _build_base_payload(self) -> dict[str, Any]:
        """Merge static config.filters with derived server-side filters.

        Priority (highest wins):
        1. active_profile (set by --profile CLI flag)
        2. search_rotation variant (randomly selected each run)
        3. base config.filters
        """
        payload: dict[str, Any] = dict(self.config.apollo.filters or {})

        # Apply rotation only when no explicit profile is active.
        if not self.config.apollo.active_profile:
            rotation_override = self._select_rotation_variant()
            if rotation_override:
                payload.update(rotation_override)

        # Apply built-in profile (overrides everything including rotation).
        if self.config.apollo.active_profile:
            from lead_pipeline.utils.profiles import get_profile
            try:
                profile = get_profile(self.config.apollo.active_profile)
                payload["person_titles"] = list(profile.person_titles)
                if profile.employee_count_max > 0:
                    ranges = _build_employee_ranges(
                        profile.employee_count_min, profile.employee_count_max
                    )
                    if ranges:
                        payload["organization_num_employees_ranges"] = ranges
                logger.info(
                    "Apollo using profile '%s': %d titles, emp max %d",
                    profile.name,
                    len(profile.person_titles),
                    profile.employee_count_max,
                )
            except ValueError as exc:
                logger.warning("Profile error: %s — falling back to base filters.", exc)

        # Employee count ranges from base config — only inject when not already set.
        if not payload.get("organization_num_employees_ranges"):
            emp_min = self.config.apollo.employee_count_min or 0
            emp_max = self.config.apollo.employee_count_max or 0
            if emp_min > 0 or emp_max > 0:
                ranges = _build_employee_ranges(emp_min, emp_max)
                if ranges:
                    payload["organization_num_employees_ranges"] = ranges

        # Server-side country filter — always applied when countries is non-empty.
        countries = [c.upper() for c in (self.config.targeting.countries or []) if c.strip()]
        if countries:
            payload["person_country_codes"] = countries

        return payload

    def _select_rotation_variant(self) -> dict[str, Any] | None:
        """Randomly pick one variant from search_rotation (if configured)."""
        rotations = self.config.apollo.search_rotation
        if not rotations:
            return None
        chosen = random.choice(rotations)
        name = chosen.get("name", "unnamed")
        logger.info("Apollo search rotation: selected '%s' variant", name)
        # Strip the logging-only 'name' key before returning.
        return {k: v for k, v in chosen.items() if k != "name"}

    def _fetch_pages(self, base_payload: dict[str, Any], start_page: int) -> list[ApolloPerson]:
        """Fetch one or more pages starting from start_page; stop early when results thin out."""
        people: list[ApolloPerson] = []
        for page_offset in range(self.config.apollo.max_pages):
            page = start_page + page_offset
            payload = {**base_payload, "page": page, "per_page": self.config.apollo.per_page}
            try:
                response = self.session.post(
                    APOLLO_SEARCH_URL,
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.warning("Apollo search page %d failed: %s", page, exc)
                break
            data = response.json()
            rows = data.get("people") or data.get("contacts") or []
            people.extend(self._parse_person(row) for row in rows)
            if len(rows) < self.config.apollo.per_page:
                break
        return people

    def _apply_client_filters(
        self,
        people: list[ApolloPerson],
        seen_ids: set[str],
    ) -> tuple[list[ApolloPerson], dict[str, int]]:
        """Apply client-side filters and return (filtered_list, stats_dict)."""
        stats: dict[str, int] = {
            "seen_filtered": 0,
            "title_filtered": 0,
            "org_filtered": 0,
            "geo_filtered": 0,
        }

        # 1. Skip previously-seen IDs.
        if seen_ids:
            before = len(people)
            people = [p for p in people if p.apollo_person_id not in seen_ids]
            stats["seen_filtered"] = before - len(people)
            if stats["seen_filtered"]:
                logger.info(
                    "Apollo: skipped %d previously-seen candidates.",
                    stats["seen_filtered"],
                )

        # 2. Title exclusions.
        if self.config.apollo.excluded_titles:
            before = len(people)
            people = [p for p in people if not self._is_excluded_title(p.title)]
            stats["title_filtered"] = before - len(people)
            if stats["title_filtered"]:
                logger.info(
                    "Apollo: dropped %d candidates matching excluded_titles.",
                    stats["title_filtered"],
                )

        # 3. Organization exclusions.
        if self.config.apollo.excluded_organizations:
            before = len(people)
            people = [p for p in people if not self._is_excluded_org(p.organization_name)]
            stats["org_filtered"] = before - len(people)
            if stats["org_filtered"]:
                logger.info(
                    "Apollo: dropped %d candidates matching excluded_organizations.",
                    stats["org_filtered"],
                )

        # 4. Client-side country/geo filter (fallback safety net after server-side filter).
        target_codes = [c.upper() for c in (self.config.targeting.countries or []) if c.strip()]
        if target_codes:
            before = len(people)
            people = [p for p in people if self._is_target_country(p, target_codes)]
            stats["geo_filtered"] = before - len(people)
            if stats["geo_filtered"]:
                logger.warning(
                    "Apollo geo filter: dropped %d non-%s candidate(s) that slipped past server-side filter.",
                    stats["geo_filtered"],
                    "/".join(target_codes),
                )

        return people, stats

    def _is_excluded_title(self, title: str) -> bool:
        title_lower = title.lower()
        overrides = {
            k.lower(): [v.lower() for v in vs]
            for k, vs in (self.config.apollo.excluded_titles_unless_containing or {}).items()
        }
        for excl in self.config.apollo.excluded_titles:
            excl_lower = excl.lower()
            if excl_lower not in title_lower:
                continue
            exceptions = overrides.get(excl_lower, [])
            if exceptions and any(ex in title_lower for ex in exceptions):
                continue
            return True
        return False

    def _is_excluded_org(self, org_name: str) -> bool:
        org_lower = org_name.lower()
        return any(excl.lower() in org_lower for excl in self.config.apollo.excluded_organizations)

    def _is_target_country(self, person: ApolloPerson, target_codes: list[str]) -> bool:
        """Client-side country check. Empty country field → pass through (server filter is primary)."""
        if not target_codes:
            return True  # geo filtering disabled
        raw_country = person.country.strip()
        if not raw_country:
            return True  # no country data — server-side filter is the primary guard
        country_upper = raw_country.upper()
        if country_upper in target_codes:
            return True
        # Handle long-form names (e.g. "United States")
        if raw_country.lower() in _US_COUNTRY_NAMES and "US" in target_codes:
            return True
        return False

    def _log_query_info(self, payload: dict[str, Any], start_page: int) -> None:
        titles = payload.get("person_titles") or []
        emp_ranges = payload.get("organization_num_employees_ranges") or []
        country_codes = payload.get("person_country_codes") or []
        excluded_orgs = self.config.apollo.excluded_organizations
        profile_tag = (
            f" [profile: {self.config.apollo.active_profile}]"
            if self.config.apollo.active_profile
            else ""
        )
        logger.info(
            "Apollo query%s — page start: %d | titles: %s | employee ranges: %s",
            profile_tag,
            start_page,
            ", ".join(titles[:4]) + ("…" if len(titles) > 4 else "") if titles else "any",
            ", ".join(emp_ranges) if emp_ranges else "any",
        )
        if country_codes:
            logger.info(
                "Apollo geography filter: %s only (server-side + client-side fallback)",
                "/".join(country_codes),
            )
        if excluded_orgs:
            logger.info(
                "Apollo org exclusions (%d): %s",
                len(excluded_orgs),
                ", ".join(excluded_orgs[:6]) + ("…" if len(excluded_orgs) > 6 else ""),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _parse_person(self, row: dict[str, Any]) -> ApolloPerson:
        organization = row.get("organization") or {}
        last_name = str(row.get("last_name") or "").strip()
        last_name_obfuscated = str(row.get("last_name_obfuscated") or "").strip()
        email = str(row.get("email") or "").strip()
        phone = str(
            row.get("phone") or row.get("direct_phone") or row.get("mobile_phone") or ""
        ).strip()
        is_obfuscated = bool(
            last_name_obfuscated
            or row.get("email_status") == "unavailable"
            or (row.get("has_email") and not email)
            or (row.get("has_direct_phone") and not phone)
        )
        return ApolloPerson(
            apollo_person_id=str(row.get("id") or row.get("person_id") or "").strip(),
            first_name=str(row.get("first_name") or "").strip(),
            last_name=last_name,
            last_name_obfuscated=last_name_obfuscated,
            title=str(row.get("title") or "").strip(),
            organization_name=str(
                organization.get("name") or row.get("organization_name") or ""
            ).strip(),
            organization_address=str(
                organization.get("street_address")
                or organization.get("streetAddress")
                or organization.get("primary_address")
                or organization.get("raw_address")
                or organization.get("rawAddress")
                or organization.get("address")
                or organization.get("address1")
                or organization.get("line1")
                or row.get("organization_street_address")
                or row.get("organization_address")
                or ""
            ).strip(),
            industry=str(
                organization.get("industry")
                or organization.get("industry_name")
                or row.get("industry")
                or row.get("organization_industry")
                or ""
            ).strip(),
            city=str(row.get("city") or organization.get("city") or organization.get("locality") or "").strip(),
            state=str(row.get("state") or organization.get("state") or organization.get("region") or "").strip(),
            country=str(row.get("country") or organization.get("country") or "").strip(),
            email=email,
            phone=phone,
            has_email=bool(row.get("has_email")),
            has_direct_phone=bool(row.get("has_direct_phone")),
            has_mobile_phone=bool(row.get("has_mobile_phone")),
            is_obfuscated=is_obfuscated,
            raw=row,
        )
