"""
SEC EDGAR collector for Form D and other relevant filings.

Form D filings are submitted by companies raising money under Regulation D
(private placements). The officers and related persons listed in these filings
are, by definition, accredited investors or issuer insiders — the exact
target persona for pre-IPO share sales.

EDGAR full-text search: https://efts.sec.gov/LATEST/search-index?q=...
EDGAR company search: https://www.sec.gov/cgi-bin/browse-edgar
"""

import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from src.utils.logger import setup_logger
from src.utils.rate_limiter import RateLimiter

logger = setup_logger("collectors.sec_edgar")

EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULL_TEXT_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_FILING_URL = "https://www.sec.gov/cgi-bin/viewer"

# EDGAR requires a User-Agent header with contact info
HEADERS = {
    "User-Agent": "InvestorLeadPipeline/1.0 (contact@example.com)",
    "Accept": "application/json",
}


@dataclass
class FormDFiling:
    """A parsed Form D filing from EDGAR."""
    company_name: str
    cik: str
    filing_date: str
    form_type: str  # D, D/A
    total_amount_sold: float | None
    total_offering_amount: float | None
    related_persons: list[dict] = field(default_factory=list)  # officers/directors/promoters
    issuer_state: str = ""
    industry_group: str = ""
    filing_url: str = ""


@dataclass
class EdgarMatch:
    """A match found for a prospect name in EDGAR filings."""
    prospect_name: str
    filing: FormDFiling
    role: str  # Director, Officer, Promoter, etc.
    confidence: float  # 0-1 match confidence


class SECEdgarCollector:
    """Searches SEC EDGAR for Form D filings and matches prospect names."""

    def __init__(self):
        self.rate_limiter = RateLimiter(max_requests=10, window_seconds=1)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def search_form_d_filings(
        self,
        search_term: str,
        date_range_days: int = 730,  # Last 2 years
        max_results: int = 20,
    ) -> list[FormDFiling]:
        """
        Search EDGAR full-text search for Form D filings matching a term.

        Args:
            search_term: Name to search for (person or company)
            date_range_days: How far back to search
            max_results: Maximum results to return
        """
        self.rate_limiter.acquire_sync()

        start_date = (datetime.now() - timedelta(days=date_range_days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        params = {
            "q": f'"{search_term}"',
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
            "forms": "D,D/A",
        }

        try:
            response = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"EDGAR search failed for '{search_term}': {e}")
            return []

        filings = []
        hits = data.get("hits", {}).get("hits", [])

        for hit in hits[:max_results]:
            source = hit.get("_source", {})
            filing = FormDFiling(
                company_name=source.get("entity_name", ""),
                cik=source.get("entity_id", ""),
                filing_date=source.get("file_date", ""),
                form_type=source.get("form_type", "D"),
                total_amount_sold=None,
                total_offering_amount=None,
                filing_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={source.get('entity_id', '')}&type=D&dateb=&owner=include&count=10",
            )
            filings.append(filing)

        logger.info(f"EDGAR search for '{search_term}': {len(filings)} Form D filings found")
        return filings

    def search_person_name(self, first_name: str, last_name: str) -> list[EdgarMatch]:
        """
        Search for a person's name across Form D filings.

        This searches for the person as a related person (officer, director, promoter)
        in Form D filings — meaning they were involved in a Reg D private placement.

        Args:
            first_name: Person's first name
            last_name: Person's last name

        Returns:
            List of EdgarMatch objects with filing details and role
        """
        search_term = f"{first_name} {last_name}"
        filings = self.search_form_d_filings(search_term)

        matches = []
        for filing in filings:
            match = EdgarMatch(
                prospect_name=search_term,
                filing=filing,
                role="Related Person",  # Would need to parse XML for exact role
                confidence=0.7,  # Name matching isn't exact
            )
            matches.append(match)

        return matches

    def batch_search(self, names: list[dict]) -> dict[str, list[EdgarMatch]]:
        """
        Batch search for multiple prospect names.

        Args:
            names: List of dicts with 'first_name' and 'last_name'

        Returns:
            Dict mapping full name to list of matches
        """
        results = {}

        for name_dict in names:
            first = name_dict.get("first_name", "")
            last = name_dict.get("last_name", "")
            full_name = f"{first} {last}".strip()

            if not full_name:
                continue

            matches = self.search_person_name(first, last)
            if matches:
                results[full_name] = matches
                logger.info(f"  SEC match found: {full_name} -> {len(matches)} filings")

        logger.info(f"SEC batch search: {len(results)} matches out of {len(names)} names")
        return results

    def search_company_filings(self, company_name: str) -> list[FormDFiling]:
        """Search for Form D filings by company name."""
        return self.search_form_d_filings(company_name)