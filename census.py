"""
Census Bureau API collector for geographic targeting.

Identifies zip codes and census tracts with high concentrations of
wealthy households based on median income and home values.

API docs: https://api.census.gov/data.html
ACS 5-Year Estimates: https://api.census.gov/data/2023/acs/acs5
"""

import requests
from dataclasses import dataclass
from src.utils.config import Config
from src.utils.logger import setup_logger

logger = setup_logger("collectors.census")

BASE_URL = "https://api.census.gov/data/2023/acs/acs5"

# ACS variable codes
VARIABLES = {
    "B19013_001E": "median_household_income",  # Median household income
    "B25077_001E": "median_home_value",         # Median home value
    "B01003_001E": "total_population",          # Total population
    "B25003_002E": "owner_occupied_units",      # Owner-occupied housing units
    "B15003_022E": "bachelors_degree",          # Population with bachelor's degree
    "B15003_023E": "masters_degree",            # Population with master's degree
    "B15003_025E": "doctoral_degree",           # Population with doctorate
}


@dataclass
class CensusTract:
    """A census tract with demographic data."""
    state_fips: str
    county_fips: str
    tract: str
    zip_code: str | None
    median_household_income: float | None
    median_home_value: float | None
    total_population: int | None
    owner_occupied_units: int | None
    education_score: float | None  # % with bachelor's or higher

    @property
    def fips(self) -> str:
        return f"{self.state_fips}{self.county_fips}{self.tract}"

    def meets_threshold(self, min_income: int, min_home_value: int) -> bool:
        """Check if tract meets targeting thresholds."""
        income_ok = (
            self.median_household_income is not None
            and self.median_household_income >= min_income
        )
        value_ok = (
            self.median_home_value is not None
            and self.median_home_value >= min_home_value
        )
        return income_ok and value_ok


# State name to FIPS code mapping
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "FL": "12", "GA": "13",
    "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29",
    "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50",
    "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56",
    "DC": "11",
}


class CensusCollector:
    """Collects demographic data from the Census Bureau API."""

    def __init__(self, config: Config):
        self.api_key = config.api_keys.census
        self.min_income = config.targeting.min_median_income
        self.min_home_value = config.targeting.min_median_home_value
        self.target_states = config.targeting.states

    def _make_request(self, params: dict) -> list[list[str]]:
        """Make a request to the Census API."""
        if self.api_key:
            params["key"] = self.api_key

        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _parse_value(self, val: str | None) -> float | None:
        """Parse a Census value, handling nulls and negatives."""
        if val is None or val == "" or val == "null":
            return None
        try:
            v = float(val)
            return v if v >= 0 else None  # Negative values = data not available
        except (ValueError, TypeError):
            return None

    def get_wealthy_tracts(self, state: str) -> list[CensusTract]:
        """
        Find census tracts in a state that meet the income and home value thresholds.

        Args:
            state: Two-letter state code (e.g., "CT")

        Returns:
            List of CensusTract objects meeting the thresholds
        """
        fips = STATE_FIPS.get(state.upper())
        if not fips:
            logger.error(f"Unknown state code: {state}")
            return []

        logger.info(f"Querying Census API for tracts in {state} (FIPS: {fips})")

        variable_codes = ",".join(VARIABLES.keys())

        try:
            data = self._make_request({
                "get": f"NAME,{variable_codes}",
                "for": "tract:*",
                "in": f"state:{fips}",
            })
        except requests.RequestException as e:
            logger.error(f"Census API request failed for {state}: {e}")
            return []

        if not data or len(data) < 2:
            logger.warning(f"No data returned for {state}")
            return []

        # First row is headers
        headers = data[0]
        tracts = []

        for row in data[1:]:
            row_dict = dict(zip(headers, row))

            income = self._parse_value(row_dict.get("B19013_001E"))
            home_value = self._parse_value(row_dict.get("B25077_001E"))
            population = self._parse_value(row_dict.get("B01003_001E"))
            bachelors = self._parse_value(row_dict.get("B15003_022E")) or 0
            masters = self._parse_value(row_dict.get("B15003_023E")) or 0
            doctoral = self._parse_value(row_dict.get("B15003_025E")) or 0

            # Education score: % of population with bachelor's or higher
            edu_score = None
            if population and population > 0:
                edu_score = round((bachelors + masters + doctoral) / population * 100, 1)

            tract = CensusTract(
                state_fips=row_dict.get("state", fips),
                county_fips=row_dict.get("county", ""),
                tract=row_dict.get("tract", ""),
                zip_code=None,  # Will be enriched via ZCTA crosswalk
                median_household_income=income,
                median_home_value=home_value,
                total_population=int(population) if population else None,
                owner_occupied_units=int(self._parse_value(row_dict.get("B25003_002E")) or 0),
                education_score=edu_score,
            )

            if tract.meets_threshold(self.min_income, self.min_home_value):
                tracts.append(tract)

        logger.info(f"Found {len(tracts)} qualifying tracts in {state} "
                     f"(income >= ${self.min_income:,}, home value >= ${self.min_home_value:,})")

        return tracts

    def get_wealthy_tracts_all_states(self) -> list[CensusTract]:
        """Get wealthy tracts across all target states."""
        all_tracts = []
        for state in self.target_states:
            tracts = self.get_wealthy_tracts(state)
            all_tracts.extend(tracts)
            logger.info(f"  {state}: {len(tracts)} qualifying tracts")

        logger.info(f"Total qualifying tracts across {len(self.target_states)} states: {len(all_tracts)}")
        return all_tracts

    def get_zip_level_data(self, state: str) -> list[dict]:
        """
        Get zip-code level income and home value data using ZCTA (ZIP Code Tabulation Areas).

        This is an alternative to tract-level data that maps directly to zip codes.
        """
        fips = STATE_FIPS.get(state.upper())
        if not fips:
            return []

        logger.info(f"Querying Census API for ZCTAs in {state}")

        try:
            data = self._make_request({
                "get": "NAME,B19013_001E,B25077_001E,B01003_001E",
                "for": "zip code tabulation area:*",
                "in": f"state:{fips}",
            })
        except requests.RequestException as e:
            logger.error(f"Census ZCTA request failed for {state}: {e}")
            return []

        if not data or len(data) < 2:
            return []

        headers = data[0]
        results = []

        for row in data[1:]:
            row_dict = dict(zip(headers, row))
            income = self._parse_value(row_dict.get("B19013_001E"))
            home_value = self._parse_value(row_dict.get("B25077_001E"))

            if (income and income >= self.min_income and
                    home_value and home_value >= self.min_home_value):
                results.append({
                    "zip_code": row_dict.get("zip code tabulation area", ""),
                    "name": row_dict.get("NAME", ""),
                    "median_income": income,
                    "median_home_value": home_value,
                    "population": self._parse_value(row_dict.get("B01003_001E")),
                })

        logger.info(f"Found {len(results)} qualifying zip codes in {state}")
        return results