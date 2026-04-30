"""SQLite storage layer for prospect records."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime


class ProspectDB:
    """Simple SQLite storage for prospect data throughout the pipeline."""

    def __init__(self, db_path: str = "data/prospects.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS prospects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT,
                city TEXT,
                state TEXT,
                zip_code TEXT,
                property_value REAL,
                property_count INTEGER DEFAULT 1,
                purchase_date TEXT,
                business_entities TEXT,  -- JSON array
                business_entity_count INTEGER DEFAULT 0,
                sec_filing_match INTEGER DEFAULT 0,  -- boolean
                sec_filing_details TEXT,  -- JSON
                apollo_email TEXT,
                apollo_title TEXT,
                apollo_company TEXT,
                apollo_linkedin TEXT,
                apollo_seniority TEXT,
                apollo_company_revenue REAL,
                phone_number TEXT,
                phone_valid INTEGER,  -- boolean
                phone_type TEXT,  -- mobile / landline
                area_median_income REAL,
                area_median_home_value REAL,
                census_tract TEXT,
                lead_score REAL,
                lead_tier TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, address)
            );

            CREATE INDEX IF NOT EXISTS idx_zip ON prospects(zip_code);
            CREATE INDEX IF NOT EXISTS idx_score ON prospects(lead_score DESC);
            CREATE INDEX IF NOT EXISTS idx_tier ON prospects(lead_tier);
        """)
        self.conn.commit()

    def upsert_prospect(self, data: dict) -> int:
        """Insert or update a prospect record. Returns the row id."""
        data["updated_at"] = datetime.now().isoformat()

        # Serialize any JSON fields
        if "business_entities" in data and isinstance(data["business_entities"], list):
            data["business_entities"] = json.dumps(data["business_entities"])
        if "sec_filing_details" in data and isinstance(data["sec_filing_details"], dict):
            data["sec_filing_details"] = json.dumps(data["sec_filing_details"])

        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        updates = ", ".join([f"{k}=excluded.{k}" for k in data.keys() if k not in ("name", "address")])

        sql = f"""
            INSERT INTO prospects ({columns}) VALUES ({placeholders})
            ON CONFLICT(name, address) DO UPDATE SET {updates}
        """

        cursor = self.conn.execute(sql, list(data.values()))
        self.conn.commit()
        return cursor.lastrowid

    def upsert_many(self, records: list[dict]):
        """Batch upsert prospect records."""
        for record in records:
            self.upsert_prospect(record)

    def get_prospects_by_zip(self, zip_code: str) -> list[dict]:
        """Get all prospects in a zip code."""
        cursor = self.conn.execute(
            "SELECT * FROM prospects WHERE zip_code = ? ORDER BY lead_score DESC",
            (zip_code,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_prospects_by_tier(self, tier: str) -> list[dict]:
        """Get all prospects in a score tier."""
        cursor = self.conn.execute(
            "SELECT * FROM prospects WHERE lead_tier = ? ORDER BY lead_score DESC",
            (tier,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_all_prospects(self) -> list[dict]:
        """Get all prospects sorted by score."""
        cursor = self.conn.execute(
            "SELECT * FROM prospects ORDER BY lead_score DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_unscored(self) -> list[dict]:
        """Get prospects that haven't been scored yet."""
        cursor = self.conn.execute(
            "SELECT * FROM prospects WHERE lead_score IS NULL"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_unenriched(self) -> list[dict]:
        """Get prospects without Apollo data."""
        cursor = self.conn.execute(
            "SELECT * FROM prospects WHERE apollo_email IS NULL"
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_by_tier(self) -> dict:
        """Get counts per tier."""
        cursor = self.conn.execute(
            "SELECT lead_tier, COUNT(*) as count FROM prospects GROUP BY lead_tier"
        )
        return {row["lead_tier"]: row["count"] for row in cursor.fetchall()}

    def close(self):
        self.conn.close()