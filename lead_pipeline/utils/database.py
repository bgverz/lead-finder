"""SQLite persistence for normalized lead records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lead_pipeline.models import Lead

VALID_STATUSES = frozenset({
    "new", "revealed", "contacted", "skipped", "converted", "do_not_contact"
})


class LeadDatabase:
    """Small SQLite storage layer for repeatable local runs."""

    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._create()
        self._migrate()

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
                lead_status TEXT DEFAULT 'new',
                status_updated_at TEXT,
                status_notes TEXT DEFAULT '',
                apollo_search_profile TEXT DEFAULT '',
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

    def _migrate(self) -> None:
        """Add new columns to existing leads table if they don't exist yet."""
        new_columns = [
            "ALTER TABLE leads ADD COLUMN lead_status TEXT DEFAULT 'new'",
            "ALTER TABLE leads ADD COLUMN status_updated_at TEXT",
            "ALTER TABLE leads ADD COLUMN status_notes TEXT DEFAULT ''",
            "ALTER TABLE leads ADD COLUMN apollo_search_profile TEXT DEFAULT ''",
        ]
        for sql in new_columns:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        self.conn.commit()

    # ------------------------------------------------------------------
    # Lead records
    # ------------------------------------------------------------------

    def upsert_many(self, leads: list[Lead]) -> None:
        for lead in leads:
            self.conn.execute(
                """
                INSERT INTO leads
                    (name, property_address, payload, lead_score, score_tier,
                     lead_status, status_notes, apollo_search_profile, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name, property_address) DO UPDATE SET
                    payload=excluded.payload,
                    lead_score=excluded.lead_score,
                    score_tier=excluded.score_tier,
                    apollo_search_profile=CASE
                        WHEN excluded.apollo_search_profile != ''
                        THEN excluded.apollo_search_profile
                        ELSE leads.apollo_search_profile END,
                    lead_status=CASE
                        WHEN leads.lead_status IN
                            ('contacted','revealed','converted','do_not_contact','skipped')
                        THEN leads.lead_status
                        ELSE excluded.lead_status END,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    lead.name,
                    lead.property_address,
                    json.dumps(lead.to_output_dict(), default=str),
                    lead.lead_score,
                    lead.score_tier,
                    lead.lead_status,
                    lead.status_notes,
                    lead.apollo_search_profile,
                ),
            )
        self.conn.commit()

    def apply_stored_statuses(self, leads: list[Lead]) -> None:
        """Restore previously-set statuses to leads before export/display."""
        for lead in leads:
            row = self.conn.execute(
                """SELECT lead_status, status_updated_at, status_notes
                   FROM leads WHERE name=? AND property_address=?""",
                (lead.name, lead.property_address),
            ).fetchone()
            if row and row["lead_status"] and row["lead_status"] != "new":
                lead.lead_status = row["lead_status"]
                lead.status_updated_at = row["status_updated_at"] or ""
                lead.status_notes = row["status_notes"] or ""

    def update_lead_status(
        self, name: str, property_address: str, status: str, notes: str = ""
    ) -> bool:
        """Update lead status. Returns True if a row was found and updated."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = self.conn.execute(
            """UPDATE leads
               SET lead_status=?, status_updated_at=?, status_notes=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE name=? AND property_address=?""",
            (status, now, notes, name, property_address),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def load_reveal_candidates(self, min_score: float = 45.0) -> list[dict]:
        """Return leads worth revealing, excluding already-actioned ones."""
        rows = self.conn.execute(
            """SELECT name, property_address, payload, lead_score, score_tier, lead_status
               FROM leads
               WHERE lead_score >= ?
                 AND lead_status NOT IN ('revealed', 'do_not_contact')
               ORDER BY lead_score DESC""",
            (min_score,),
        ).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["payload"])
            data["_db_lead_status"] = row["lead_status"] or "new"
            result.append(data)
        return result

    def load_profile_stats(self) -> list[dict]:
        """Aggregate lead quality stats grouped by Apollo search profile."""
        rows = self.conn.execute(
            """SELECT
                   COALESCE(NULLIF(apollo_search_profile, ''), '(no profile)') AS profile,
                   COUNT(*) AS total,
                   ROUND(AVG(lead_score), 1) AS avg_score,
                   SUM(CASE WHEN score_tier='Hot'  THEN 1 ELSE 0 END) AS hot,
                   SUM(CASE WHEN score_tier='Warm' THEN 1 ELSE 0 END) AS warm,
                   SUM(CASE WHEN score_tier='Cool' THEN 1 ELSE 0 END) AS cool,
                   SUM(CASE WHEN score_tier='Skip' THEN 1 ELSE 0 END) AS skip_count
               FROM leads
               GROUP BY COALESCE(NULLIF(apollo_search_profile, ''), '(no profile)')
               ORDER BY avg_score DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def import_feedback(self, rows: list[dict]) -> tuple[int, int]:
        """Apply status/notes from feedback rows. Returns (updated_count, not_found_count)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updated = 0
        not_found = 0
        for row in rows:
            name = (row.get("name") or "").strip()
            status = (row.get("status") or "").strip().lower()
            notes = (row.get("notes") or "").strip()
            address = (row.get("property_address") or "").strip()
            if not name or not status:
                continue
            if address:
                cursor = self.conn.execute(
                    """UPDATE leads
                       SET lead_status=?, status_updated_at=?, status_notes=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE name=? AND property_address=?""",
                    (status, now, notes, name, address),
                )
            else:
                cursor = self.conn.execute(
                    """UPDATE leads
                       SET lead_status=?, status_updated_at=?, status_notes=?,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE name=?""",
                    (status, now, notes, name),
                )
            if cursor.rowcount > 0:
                updated += cursor.rowcount
            else:
                not_found += 1
        self.conn.commit()
        return updated, not_found

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
