"""Manual Apollo connectivity probe.

Run directly with `python test_apollo.py`. Pytest should not make live API calls.
"""

import os

import requests
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        raise SystemExit("APOLLO_API_KEY is not set.")

    response = requests.post(
        "https://api.apollo.io/api/v1/mixed_people/api_search",
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        json={"page": 1, "per_page": 5},
        timeout=30,
    )
    print(response.status_code)
    print(response.json())


if __name__ == "__main__":
    main()
