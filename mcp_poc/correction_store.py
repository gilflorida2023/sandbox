import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CORRECTIONS_DB = "corrections.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    incorrect_output TEXT NOT NULL,
    correct_output TEXT NOT NULL,
    context TEXT DEFAULT '',
    created_at REAL NOT NULL,
    applied_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_corrections_topic ON corrections(topic);
"""


class CorrectionStore:
    """Stores user corrections to prevent repeated mistakes.

    Users can correct the AI's responses via the REPL. Corrections
    are stored by topic and injected into the context when the
    model encounters a similar topic again.
    """

    def __init__(self, storage_path: str):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        db_path = self.storage / CORRECTIONS_DB
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA_SQL)

    def add_correction(self, topic: str, incorrect: str,
                       correct: str, context: str = ""):
        self._db.execute(
            """INSERT INTO corrections
               (topic, incorrect_output, correct_output, context, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (topic.strip(), incorrect.strip(), correct.strip(),
             context.strip(), time.time()),
        )
        self._db.commit()
        logger.info("Stored correction for topic '%s'", topic)

    def get_corrections(self, topic: str, limit: int = 5) -> List[Dict]:
        rows = self._db.execute(
            """SELECT * FROM corrections
               WHERE topic LIKE ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (f"%{topic}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_corrections(self, limit: int = 50) -> List[Dict]:
        rows = self._db.execute(
            "SELECT * FROM corrections ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def increment_applied(self, correction_id: int):
        self._db.execute(
            "UPDATE corrections SET applied_count = applied_count + 1 WHERE id = ?",
            (correction_id,),
        )
        self._db.commit()

    def format_corrections_for_context(self, topic: str) -> str:
        corrections = self.get_corrections(topic)
        if not corrections:
            return ""
        lines = ["=== User Corrections ==="]
        for c in corrections:
            lines.append(
                f"- Topic: {c['topic']}\n"
                f"  Incorrect: {c['incorrect_output'][:200]}\n"
                f"  Correct: {c['correct_output'][:200]}"
            )
            self.increment_applied(c["id"])
        return "\n".join(lines)

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]

    def close(self):
        self._db.close()
