"""Census/geographic targeting adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from src.models import TargetArea
from src.utils.config import Config
from src.utils.logger import setup_logger

logger = setup_logger("collectors.census")

ACS_BASE_URL = "https://api.census.gov/data/2023/acs/acs5"
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}


@dataclass
class CensusClient:
    """Resolve target geographies to wealthy areas."""

    config: Config

    def target_areas(self, cli_zip_codes: list[str] | None = None, cli_state: str = "") -> list[TargetArea]:
        """Return target areas from CLI/config, enriched from Census when enabled."""

        zip_codes = cli_zip_codes or self.config.targeting.zip_codes
        if zip_codes:
            return [
                TargetArea(
                    geography_type="zip",
                    code=str(zip_code).zfill(5),
                    median_income=None,
                    source="user_input",
                )
                for zip_code in zip_codes
            ]

        states = [cli_state] if cli_state else self.config.targeting.states
        if self.config.sources.mode == "api":
            return self._fetch_county_areas_for_states(states)

        # In sample mode, keep the target broad and let sample property rows carry area income.
        return [
            TargetArea(geography_type="state", code=state.upper(), state=state.upper(), source="sample")
            for state in states
        ]

    def _fetch_county_areas_for_states(self, states: list[str]) -> list[TargetArea]:
        """Fetch county-level ACS5 data for each target state.

        The Census API does not support state-filtered ZCTA queries (the
        ``in=state:XX`` constraint returns HTTP 400 for
        ``for=zip code tabulation area:*`` in ACS5 2023), and the national
        ZCTA dataset does not include a state association (STATE=None).  We
        use county-level data instead: ``for=county:*&in=state:XX`` is fully
        supported, returns reliable median income / home value, and the
        data flows through to area wealth scoring.
        """
        unknown_states = [s for s in states if s.upper() not in STATE_FIPS]
        if unknown_states:
            logger.warning(
                "Skipping unrecognised state codes (not in Census FIPS table): %s",
                ", ".join(unknown_states),
            )

        areas: list[TargetArea] = []
        for state in states:
            fips = STATE_FIPS.get(state.upper())
            if not fips:
                continue

            params: dict[str, str] = {
                "get": "NAME,B19013_001E,B25077_001E,B01003_001E",
                "for": "county:*",
                "in": f"state:{fips}",
            }
            if self.config.api_keys.census:
                params["key"] = self.config.api_keys.census

            loggable = {k: v for k, v in params.items() if k != "key"}
            logger.debug("Census ACS5 county request for state %s: %s", state.upper(), loggable)

            try:
                response = requests.get(ACS_BASE_URL, params=params, timeout=30)
                response.raise_for_status()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                body = getattr(getattr(exc, "response", None), "text", "")[:300]
                exc_str = _redact_census_key(str(exc))
                logger.warning(
                    "Census county request failed for state %s%s: %s%s",
                    state.upper(),
                    f" (HTTP {status})" if status else "",
                    exc_str,
                    f" | response: {body}" if body else "",
                )
                continue

            rows = response.json()
            if len(rows) < 2:
                logger.debug("Census returned no county rows for state %s.", state.upper())
                continue

            headers = rows[0]
            for row in rows[1:]:
                data = dict(zip(headers, row))
                income = _number(data.get("B19013_001E"))
                home_value = _number(data.get("B25077_001E"))
                if income is None or home_value is None:
                    continue
                # Use county FIPS as the area code (state_fips + county_fips).
                county_code = str(data.get("county") or "").zfill(3)
                area_code = f"{fips}{county_code}"
                areas.append(
                    TargetArea(
                        geography_type="county",
                        code=area_code,
                        state=state.upper(),
                        county=str(data.get("NAME") or ""),
                        median_income=income,
                        median_home_value=home_value,
                        population=int(_number(data.get("B01003_001E")) or 0),
                        source="census_acs5_county",
                    )
                )

        wealthy = [
            a for a in areas
            if (a.median_income or 0) >= self.config.targeting.min_median_income
            or (a.median_home_value or 0) >= self.config.targeting.min_median_home_value
        ]
        logger.info(
            "Census: %s counties retrieved, %s meet wealth thresholds for states: %s",
            len(areas),
            len(wealthy),
            ", ".join(s.upper() for s in states if s.upper() in STATE_FIPS),
        )
        return wealthy


def _redact_census_key(message: str) -> str:
    return re.sub(r"((?:&|\?)key=)[^&\s]+", r"\1REDACTED", message)


def _number(value: str | None) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
