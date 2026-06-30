"""Windowed prime-sieve knowledge accumulation system backed by SQLite.

Same API as WindowedContext in windowed_context.py, but persistence is
handled by SQLite with FTS5 full-text search instead of flat JSON files.
"""

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

DB_FILENAME = "knowledge.db"
CHUNKS_FILE = "chunks.json"  # legacy file for migration

# ── Helpers ────────────────────────────────────────────────────────────────


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _now() -> float:
    return time.time()


def _match_tags(tags: List[str], query: str) -> float:
    q = query.lower()
    words = q.split()
    tag_hits = sum(1 for t in tags if t.lower() in q)
    word_hits = sum(1 for w in words if any(w in t.lower() for t in tags))
    if not tags or not words:
        return 0.0
    return min(1.0, (tag_hits * 0.6 + word_hits * 0.4) / max(len(tags), 1))


def _match_content(content: str, query: str) -> float:
    q = query.lower()
    c = content.lower()
    words = q.split()
    word_hits = sum(1 for w in words if w in c)
    if not words:
        return 0.0
    return min(1.0, word_hits / len(words))


# ── Data ───────────────────────────────────────────────────────────────────


@dataclass
class KnowledgeChunk:
    chunk_id: str
    content: str
    tags: List[str] = field(default_factory=list)
    source: str = "manual"
    weight: float = 0.5
    created_at: float = 0.0
    accessed_at: float = 0.0
    access_count: int = 0

    @classmethod
    def new(cls, content: str, source: str = "manual",
            tags: Optional[List[str]] = None) -> "KnowledgeChunk":
        now = _now()
        return cls(
            chunk_id=_content_hash(content),
            content=content,
            tags=tags or [],
            source=source,
            weight=0.5,
            created_at=now,
            accessed_at=now,
            access_count=0,
        )

    def touch(self):
        self.access_count += 1
        self.accessed_at = _now()

    def current_weight(self) -> float:
        decay = 0.99 ** max(0, _now() - self.accessed_at)
        freq_bonus = 1.0 + 0.1 * min(self.access_count, 50)
        return min(1.0, self.weight * decay * freq_bonus)


# ── Schema ─────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual',
    weight REAL NOT NULL DEFAULT 0.5,
    created_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_created_at ON chunks(created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_accessed_at ON chunks(accessed_at);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    tags,
    tokenize='porter unicode61'
);
"""

# ── SQLite-backed accumulator ──────────────────────────────────────────────


class WindowedContextDB:
    """Prime-sieve knowledge accumulator backed by SQLite + FTS5.

    API-compatible with WindowedContext (windowed_context.py).
    Persistence is automatic — save()/load() are no-ops kept for API compat.
    """

    def __init__(self, storage_path: str, max_window: int = 30,
                 max_total: int = 500):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.max_window = max_window
        self.max_total = max_total

        db_path = self.storage / DB_FILENAME
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA_SQL)

        self._maybe_migrate_from_json()

    # ── Migration from legacy JSON ──────────────────────────────────────

    def _maybe_migrate_from_json(self):
        path = self.storage / CHUNKS_FILE
        if not path.exists():
            return
        count = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if count > 0:
            return
        try:
            data = json.loads(path.read_text())
            for d in data:
                tags = d.get("tags", [])
                if isinstance(tags, list):
                    tags = json.dumps(tags)
                self._db.execute(
                    """INSERT OR IGNORE INTO chunks
                       (chunk_id, content, tags, source, weight,
                        created_at, accessed_at, access_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (d["chunk_id"], d["content"], tags,
                     d.get("source", "manual"), d.get("weight", 0.5),
                     d.get("created_at", 0), d.get("accessed_at", 0),
                     d.get("access_count", 0)),
                )
                self._db.execute(
                    "INSERT OR IGNORE INTO chunks_fts(chunk_id, content, tags) VALUES (?, ?, ?)",
                    (d["chunk_id"], d["content"], tags),
                )
            self._db.commit()
            logger.info("Migrated %d chunks from %s", len(data), path)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Migration failed from %s: %s", path, e)

    # ── Row conversion ──────────────────────────────────────────────────

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> KnowledgeChunk:
        tags_raw = row["tags"]
        if isinstance(tags_raw, str):
            tags = json.loads(tags_raw) if tags_raw else []
        else:
            tags = tags_raw or []
        return KnowledgeChunk(
            chunk_id=row["chunk_id"],
            content=row["content"],
            tags=tags,
            source=row["source"],
            weight=row["weight"],
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"],
        )

    # ── Public API ──────────────────────────────────────────────────────

    def add(self, content: str, source: str = "manual",
            tags: Optional[List[str]] = None) -> str:
        chunk = KnowledgeChunk.new(content, source=source, tags=tags)
        existing = self._db.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
        ).fetchone()

        if existing:
            weight = min(1.0, existing["weight"] + 0.1)
            access_count = existing["access_count"] + 1
            now = _now()
            merged_tags = list(set(json.loads(existing["tags"]) if isinstance(existing["tags"], str) else (existing["tags"] or [])) | set(chunk.tags))
            self._db.execute(
                """UPDATE chunks SET weight=?, access_count=?, accessed_at=?,
                   tags=?, source=?
                   WHERE chunk_id=?""",
                (weight, access_count, now, json.dumps(merged_tags),
                 source, chunk.chunk_id),
            )
            self._db.commit()
            logger.debug("Bumped existing chunk %s (weight=%.2f, access=%d)",
                         chunk.chunk_id, weight, access_count)
            return chunk.chunk_id

        tags_json = json.dumps(chunk.tags)
        self._db.execute(
            """INSERT INTO chunks
               (chunk_id, content, tags, source, weight,
                created_at, accessed_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (chunk.chunk_id, chunk.content, tags_json, chunk.source,
             chunk.weight, chunk.created_at, chunk.accessed_at,
             chunk.access_count),
        )
        self._db.execute(
            "INSERT INTO chunks_fts(chunk_id, content, tags) VALUES (?, ?, ?)",
            (chunk.chunk_id, chunk.content, tags_json),
        )
        self._db.commit()
        logger.info("Added chunk %s (source=%s, tags=%s)",
                     chunk.chunk_id, source, tags)
        return chunk.chunk_id

    def add_chunk(self, chunk: KnowledgeChunk) -> str:
        existing = self._db.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
        ).fetchone()

        if existing:
            weight = min(1.0, existing["weight"] + 0.1)
            access_count = existing["access_count"] + 1
            now = _now()
            merged_tags = list(set(json.loads(existing["tags"]) if isinstance(existing["tags"], str) else (existing["tags"] or [])) | set(chunk.tags))
            self._db.execute(
                """UPDATE chunks SET weight=?, access_count=?, accessed_at=?,
                   tags=?
                   WHERE chunk_id=?""",
                (weight, access_count, now, json.dumps(merged_tags),
                 chunk.chunk_id),
            )
            self._db.commit()
            return chunk.chunk_id

        tags_json = json.dumps(chunk.tags)
        self._db.execute(
            """INSERT INTO chunks
               (chunk_id, content, tags, source, weight,
                created_at, accessed_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (chunk.chunk_id, chunk.content, tags_json, chunk.source,
             chunk.weight, chunk.created_at, chunk.accessed_at,
             chunk.access_count),
        )
        self._db.execute(
            "INSERT INTO chunks_fts(chunk_id, content, tags) VALUES (?, ?, ?)",
            (chunk.chunk_id, chunk.content, tags_json),
        )
        self._db.commit()
        return chunk.chunk_id

    def query(self, text: str, max_results: int = 5) -> List[KnowledgeChunk]:
        terms = [t for t in text.lower().split() if len(t) > 2]
        if not terms:
            return []

        # Try FTS5 for content search
        fts_query = " AND ".join(f'"{t}"' for t in terms)
        try:
            fts_rows = self._db.execute(
                """SELECT c.*
                   FROM chunks_fts f
                   JOIN chunks c ON c.chunk_id = f.chunk_id
                   WHERE chunks_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, max_results * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            fts_rows = []

        scored = []
        seen_ids = set()

        if fts_rows:
            now = _now()
            for row in fts_rows:
                chunk = self._row_to_chunk(row)
                tag_score = _match_tags(chunk.tags, text)
                content_score = _match_content(chunk.content, text)
                combined = (tag_score * 0.4 + content_score * 0.6) * chunk.current_weight()
                scored.append((combined, chunk))
                seen_ids.add(chunk.chunk_id)

        # Fallback: scan all chunks if FTS5 returned nothing
        if not scored:
            all_rows = self._db.execute("SELECT * FROM chunks").fetchall()
            for row in all_rows:
                chunk = self._row_to_chunk(row)
                tag_score = _match_tags(chunk.tags, text)
                content_score = _match_content(chunk.content, text)
                if tag_score == 0.0 and content_score == 0.0:
                    continue
                combined = (tag_score * 0.4 + content_score * 0.6) * chunk.current_weight()
                scored.append((combined, chunk))

        scored.sort(key=lambda x: -x[0])
        results = [chunk for _, chunk in scored[:max_results]]

        # Update access tracking
        for chunk in results:
            self._db.execute(
                "UPDATE chunks SET access_count = access_count + 1, accessed_at = ? WHERE chunk_id = ?",
                (_now(), chunk.chunk_id),
            )
        if results:
            self._db.commit()

        return results

    def window(self, max_size: Optional[int] = None) -> List[KnowledgeChunk]:
        size = max_size or self.max_window
        rows = self._db.execute("SELECT * FROM chunks").fetchall()
        chunks = [self._row_to_chunk(r) for r in rows]
        chunks.sort(key=lambda c: c.current_weight(), reverse=True)
        return chunks[:size]

    def prune(self, max_total: Optional[int] = None) -> int:
        limit = max_total or self.max_total
        count = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if count <= limit:
            return 0
        excess = count - limit
        rows = self._db.execute("SELECT * FROM chunks").fetchall()
        chunks = [(self._row_to_chunk(r), r["chunk_id"]) for r in rows]
        chunks.sort(key=lambda x: x[0].current_weight())
        evict_ids = [cid for _, cid in chunks[:excess]]
        placeholders = ",".join("?" for _ in evict_ids)
        self._db.execute(
            f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", evict_ids
        )
        self._db.execute(
            """DELETE FROM chunks_fts WHERE chunk_id NOT IN (
                SELECT chunk_id FROM chunks
            )"""
        )
        self._db.commit()
        removed = excess
        logger.info("Pruned %d chunks (kept %d / %d max)",
                     removed, limit, limit)
        return removed

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    # ── Session log ingestion ───────────────────────────────────────────

    def ingest_session_log(self, log_path: str) -> int:
        path = Path(log_path)
        if not path.exists():
            logger.warning("Session log not found: %s", log_path)
            return 0

        text = path.read_text()
        added = 0
        source = f"session:{path.stem}"

        for match in re.finditer(
                r"^## Decisions\s*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for i, line in enumerate(body.strip().split("\n")):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                decision = re.sub(r"^\d+\.\s*", "", line).strip()
                if decision:
                    self.add(f"Decision: {decision}",
                             source=source, tags=["decision"])
                    added += 1

        for match in re.finditer(
                r"^## Roadblocks?.*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rb = re.sub(r"^-\s*", "", line).strip()
                if rb:
                    self.add(f"Roadblock: {rb}",
                             source=source, tags=["roadblock"])
                    added += 1

        for match in re.finditer(
                r"^## Action Items\s*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                ai = re.sub(r"^-\s*\[.?\]\s*", "", line).strip()
                if ai:
                    self.add(f"Action: {ai}",
                             source=source, tags=["action"])
                    added += 1

        for match in re.finditer(
                r"^## Ideas\s*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                idea = re.sub(r"^-\s*\*{0,2}", "", line).strip()
                idea = re.sub(r"\*{0,2}:\s*", ": ", idea)
                if idea:
                    self.add(f"Idea: {idea}",
                             source=source, tags=["idea"])
                    added += 1

        for match in re.finditer(
                r"^## Concepts\s*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                concept = re.sub(r"^-\s*\*{0,2}", "", line).strip()
                concept = re.sub(r"\*{0,2}:\s*", ": ", concept)
                if concept:
                    self.add(f"Concept: {concept}",
                             source=source, tags=["concept"])
                    added += 1

        for match in re.finditer(
                r"^## Terminology\s*\n(.+?)(?=^## |\Z)", text, re.M | re.S):
            body = match.group(1)
            for line in body.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                term = re.sub(r"^-\s*\*{0,2}", "", line).strip()
                term = re.sub(r"\*{0,2}:\s*", ": ", term)
                if term:
                    self.add(f"Term: {term}",
                             source=source, tags=["term", "glossary"])
                    added += 1

        if added:
            logger.info("Ingested %d chunks from %s", added, log_path)
        return added

    def ingest_session_logs(self, logs_dir: str, max_logs: int = 20) -> int:
        d = Path(logs_dir)
        if not d.is_dir():
            logger.warning("Session logs dir not found: %s", logs_dir)
            return 0
        md_files = sorted(d.glob("*.md"))
        md_files = [f for f in md_files if f.name != "INDEX.md"]
        total = 0
        for f in md_files[:max_logs]:
            total += self.ingest_session_log(str(f))
        return total

    # ── Convenience helpers ─────────────────────────────────────────────

    def add_note(self, content: str, tags: Optional[List[str]] = None) -> str:
        return self.add(content, source="note", tags=tags)

    def add_guide(self, name: str, content: str) -> str:
        return self.add(content, source="guide", tags=["guide", name])

    # ── Persistence (no-ops for API compat) ─────────────────────────────

    def save(self):
        pass

    def load(self):
        pass

    # ── Reset ───────────────────────────────────────────────────────────

    def clear(self):
        self._db.execute("DELETE FROM chunks")
        self._db.execute("DELETE FROM chunks_fts")
        self._db.commit()
