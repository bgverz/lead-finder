"""SQLite persistence for normalized lead records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import Lead


class LeadDatabase:
    """Small SQLite storage layer for repeatable local runs."""

    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._create()

    def _create(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                property_address TEXT NOT NULL,
                payload TEXT NOT NULL,
                lead_score REAL,
                score_tier TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, property_address)
            );
            CREATE TABLE IF NOT EXISTS seen_apollo_candidates (
                person_id   TEXT PRIMARY KEY,
                organization TEXT,
                title        TEXT,
                surfaced_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Lead records
    # ------------------------------------------------------------------

    def upsert_many(self, leads: list[Lead]) -> None:
        for lead in leads:
            self.conn.execute(
                """
                INSERT INTO leads (name, property_address, payload, lead_score, score_tier, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name, property_address) DO UPDATE SET
                    payload=excluded.payload,
                    lead_score=excluded.lead_score,
                    score_tier=excluded.score_tier,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    lead.name,
                    lead.property_address,
                    json.dumps(lead.to_output_dict(), default=str),
                    lead.lead_score,
                    lead.score_tier,
                ),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Apollo seen-IDs cache
    # ------------------------------------------------------------------

    def load_seen_apollo_ids(self, cooldown_days: int = 0) -> set[str]:
        """Return Apollo person IDs that should be suppressed this run.

        If ``cooldown_days`` is 0, return all ever-seen IDs.
        If > 0, return only IDs seen within the last N days.
        """
        if cooldown_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            rows = self.conn.execute(
                "SELECT person_id FROM seen_apollo_candidates WHERE surfaced_at >= ?",
                (cutoff,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT person_id FROM seen_apollo_candidates"
            ).fetchall()
        return {row["person_id"] for row in rows}

    def save_seen_apollo_ids(self, people: list) -> None:
        """Persist a list of ApolloPerson objects as seen candidates."""
        for person in people:
            pid = getattr(person, "apollo_person_id", None)
            if not pid:
                continue
            self.conn.execute(
                """
                INSERT INTO seen_apollo_candidates (person_id, organization, title, surfaced_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(person_id) DO UPDATE SET
                    surfaced_at = CURRENT_TIMESTAMP
                """,
                (
                    pid,
                    getattr(person, "organization_name", ""),
                    getattr(person, "title", ""),
                ),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
