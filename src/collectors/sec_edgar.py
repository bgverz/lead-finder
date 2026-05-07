"""SEC EDGAR/Form D lookup adapter."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from src.utils.config import Config
from src.utils.logger import setup_logger
from src.utils.rate_limiter import RateLimiter

logger = setup_logger("collectors.sec_edgar")

_EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_MAX_ATTEMPTS = 3
_RETRY_STATUSES = {500, 502, 503, 504}


class SECEdgarMatcher:
    """Find Form D or disclosure matches for prospects."""

    def __init__(self, config: Config):
        self.config = config
        self._rate_limiter = RateLimiter(10, 1)
        self._sample = self._load_sample() if config.sources.mode == "sample" else {}
        if config.sources.mode == "api":
            ua = config.api_keys.sec_user_agent
            if not ua or "contact@example.com" in ua:
                logger.warning(
                    "SEC EDGAR User-Agent is not configured (placeholder detected); "
                    "SEC enrichment will be skipped for all candidates."
                )
            else:
                logger.info("SEC EDGAR enrichment enabled (User-Agent: %s).", ua)

    def match(self, owner_name: str) -> tuple[bool, list[dict]]:
        if self.config.sources.mode == "sample":
            details = self._sample.get(_norm(owner_name), [])
            return bool(details), details

        self._rate_limiter.acquire()
        headers = {
            "User-Agent": self.config.api_keys.sec_user_agent,
            "Accept": "application/json",
        }
        params = {"q": f'"{owner_name}"', "forms": "D,D/A", "dateRange": "all"}

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = requests.get(
                    _EDGAR_SEARCH_URL,
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                if response.status_code in _RETRY_STATUSES:
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    if attempt < _MAX_ATTEMPTS:
                        logger.warning(
                            "SEC EDGAR returned HTTP %s for %r (attempt %d/%d); "
                            "retrying in %ds.",
                            response.status_code,
                            owner_name,
                            attempt,
                            _MAX_ATTEMPTS,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.warning(
                            "SEC EDGAR returned HTTP %s for %r after %d attempts; skipping.",
                            response.status_code,
                            owner_name,
                            _MAX_ATTEMPTS,
                        )
                        return False, []

                response.raise_for_status()
                hits = response.json().get("hits", {}).get("hits", [])
                details = [
                    {
                        "company_name": hit.get("_source", {}).get("entity_name", ""),
                        "filing_date": hit.get("_source", {}).get("file_date", ""),
                        "form_type": hit.get("_source", {}).get("form_type", ""),
                        "source": "sec_edgar",
                    }
                    for hit in hits[:5]
                ]
                return bool(details), details

            except requests.exceptions.Timeout as exc:
                last_exc = exc
                delay = 2 ** (attempt - 1)
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "SEC EDGAR timed out for %r (attempt %d/%d); retrying in %ds.",
                        owner_name,
                        attempt,
                        _MAX_ATTEMPTS,
                        delay,
                    )
                    time.sleep(delay)
            except Exception as exc:
                last_exc = exc
                break  # Non-retryable (connection error, bad JSON, etc.)

        logger.warning(
            "SEC EDGAR match failed for %r: %s; skipping candidate.",
            owner_name,
            last_exc,
        )
        return False, []

    def _load_sample(self) -> dict[str, list[dict]]:
        path = Path(self.config.sources.sample_sec_matches)
        if not path.exists():
            return {}
        frame = pd.read_csv(path)
        index: dict[str, list[dict]] = {}
        for row in frame.to_dict("records"):
            index.setdefault(_norm(str(row.get("owner_name", ""))), []).append(
                {
                    "company_name": row.get("company_name", ""),
                    "filing_date": row.get("filing_date", ""),
                    "form_type": row.get("form_type", "D"),
                    "source": row.get("source", "sample_sec_matches"),
                }
            )
        return index


def _norm(value: str) -> str:
    return " ".join(value.lower().replace(".", "").split())
