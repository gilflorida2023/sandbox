"""Windowed prime-sieve knowledge accumulation system.

Stores knowledge as discrete, content-addressed chunks.
Deduplication by SHA-256 hash ("sieve" — only unique primes survive).
A weighted sliding window determines which chunks are returned for
context injection, with eviction based on weight + recency + access count.

Supports:
  - Hash-based dedup (same content = same chunk, weight bumps on re-add)
  - Tag + keyword relevance scoring
  - LRU-weighted window retrieval
  - Session log ingestion (parses .session-log/*.md files)
  - JSON persistence to disk
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────

def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _now() -> float:
    return time.time()


def _match_tags(tags: List[str], query: str) -> float:
    """Score [0.0, 1.0] how well tags match a query string."""
    q = query.lower()
    words = q.split()
    tag_hits = sum(1 for t in tags if t.lower() in q)
    word_hits = sum(1 for w in words if any(w in t.lower() for t in tags))
    if not tags or not words:
        return 0.0
    return min(1.0, (tag_hits * 0.6 + word_hits * 0.4) / max(len(tags), 1))


def _match_content(content: str, query: str) -> float:
    """Score [0.0, 1.0] how well knowledge content matches a query."""
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
        decay = 0.99 ** max(0, _now() - self.accessed_at)  # ~1% per sec
        freq_bonus = 1.0 + 0.1 * min(self.access_count, 50)
        return min(1.0, self.weight * decay * freq_bonus)


# ── Accumulator ────────────────────────────────────────────────────────────

CHUNKS_FILE = "chunks.json"
INDEX_FILE = "index.json"


class WindowedContext:
    """Prime-sieve knowledge accumulator with windowed retrieval.

    Usage:
      wc = WindowedContext("/path/to/storage")
      wc.add("Use workspace.read before editing files", source="guide", tags=["tool", "workspace"])
      wc.add_chunk(KnowledgeChunk.new("..."))

      for chunk in wc.query("how to read a file", max_results=3):
          print(chunk.content)

      wc.prune(max_total=500)
      wc.save()
    """

    def __init__(self, storage_path: str, max_window: int = 30,
                 max_total: int = 500):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.max_window = max_window
        self.max_total = max_total
        self._chunks: dict[str, KnowledgeChunk] = {}
        self._dirty = False

    # ── Public API ──────────────────────────────────────────────────────

    def add(self, content: str, source: str = "manual",
            tags: Optional[List[str]] = None) -> str:
        """Add a knowledge chunk. Deduplicates by content hash.
        Returns the chunk_id (same as existing if already present)."""
        chunk = KnowledgeChunk.new(content, source=source, tags=tags)
        existing = self._chunks.get(chunk.chunk_id)
        if existing:
            existing.touch()
            existing.weight = min(1.0, existing.weight + 0.1)
            existing.source = source
            if tags:
                existing.tags = list(set(existing.tags + tags))
            logger.debug("Bumped existing chunk %s (weight=%.2f, access=%d)",
                          chunk.chunk_id, existing.weight, existing.access_count)
            self._dirty = True
            return existing.chunk_id
        self._chunks[chunk.chunk_id] = chunk
        self._dirty = True
        logger.info("Added chunk %s (source=%s, tags=%s)",
                     chunk.chunk_id, source, tags)
        return chunk.chunk_id

    def add_chunk(self, chunk: KnowledgeChunk) -> str:
        """Add a pre-built KnowledgeChunk. Dedup by content hash."""
        existing = self._chunks.get(chunk.chunk_id)
        if existing:
            existing.touch()
            existing.weight = min(1.0, existing.weight + 0.1)
            if chunk.tags:
                existing.tags = list(set(existing.tags + chunk.tags))
            self._dirty = True
            return existing.chunk_id
        self._chunks[chunk.chunk_id] = chunk
        self._dirty = True
        return chunk.chunk_id

    def query(self, text: str, max_results: int = 5) -> List[KnowledgeChunk]:
        """Retrieve top-N chunks relevant to *text*.

        Scoring combines tag match + content match, weighted by
        current_weight (which factors in recency and access frequency).
        """
        scored = []
        for chunk in self._chunks.values():
            tag_score = _match_tags(chunk.tags, text)
            content_score = _match_content(chunk.content, text)
            if tag_score == 0.0 and content_score == 0.0:
                continue
            combined = (tag_score * 0.4 + content_score * 0.6) * chunk.current_weight()
            scored.append((combined, chunk))

        scored.sort(key=lambda x: -x[0])
        results = [chunk for _, chunk in scored[:max_results]]
        for chunk in results:
            chunk.touch()
        self._dirty = True
        return results

    def window(self, max_size: Optional[int] = None) -> List[KnowledgeChunk]:
        """Return the top-weighted chunks for context injection."""
        size = max_size or self.max_window
        ranked = sorted(
            self._chunks.values(),
            key=lambda c: c.current_weight(),
            reverse=True,
        )
        return ranked[:size]

    def prune(self, max_total: Optional[int] = None) -> int:
        """Evict lowest-weighted chunks beyond max_total.  Returns count removed."""
        limit = max_total or self.max_total
        if len(self._chunks) <= limit:
            return 0
        ranked = sorted(
            self._chunks.values(),
            key=lambda c: c.current_weight(),
        )
        to_evict = len(self._chunks) - limit
        for chunk in ranked[:to_evict]:
            del self._chunks[chunk.chunk_id]
        if to_evict:
            self._dirty = True
            logger.info("Pruned %d chunks (kept %d / %d max)",
                        to_evict, len(self._chunks), limit)
        return to_evict

    def count(self) -> int:
        return len(self._chunks)

    # ── Session log ingestion ───────────────────────────────────────────

    def ingest_session_log(self, log_path: str) -> int:
        """Parse a .session-log markdown file and extract knowledge chunks.

        Recognised sections: Decisions, Roadblocks, Action Items, Ideas,
        Concepts, Terminology.  Each yields one or more chunks.
        Returns count of new chunks added.
        """
        path = Path(log_path)
        if not path.exists():
            logger.warning("Session log not found: %s", log_path)
            return 0

        text = path.read_text()
        added = 0
        source = f"session:{path.stem}"

        # Extract decisions
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

        # Extract roadblocks
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

        # Extract action items
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

        # Extract ideas
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

        # Extract concepts
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

        # Extract terminology
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

    def ingest_session_logs(self, logs_dir: str,
                            max_logs: int = 20) -> int:
        """Ingest all .md files in a .session-log directory.
        Returns total chunks added."""
        d = Path(logs_dir)
        if not d.is_dir():
            logger.warning("Session logs dir not found: %s", logs_dir)
            return 0
        md_files = sorted(d.glob("*.md"))
        # Skip INDEX.md
        md_files = [f for f in md_files if f.name != "INDEX.md"]
        total = 0
        for f in md_files[:max_logs]:
            total += self.ingest_session_log(str(f))
        return total

    # ── In-memory knowledge from plain text ─────────────────────────────

    def add_note(self, content: str, tags: Optional[List[str]] = None) -> str:
        """Shortcut to add a plain knowledge note."""
        return self.add(content, source="note", tags=tags)

    def add_guide(self, name: str, content: str) -> str:
        """Store a guide as a knowledge chunk."""
        return self.add(content, source="guide", tags=["guide", name])

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self):
        if not self._dirty:
            return
        path = self.storage / CHUNKS_FILE
        data = []
        for chunk in self._chunks.values():
            d = asdict(chunk)
            data.append(d)
        path.write_text(json.dumps(data, indent=2))
        self._write_index()
        self._dirty = False
        logger.debug("Saved %d chunks to %s", len(data), path)

    def load(self):
        path = self.storage / CHUNKS_FILE
        if not path.exists():
            logger.info("No existing chunks at %s, starting fresh", path)
            return
        try:
            data = json.loads(path.read_text())
            for d in data:
                chunk = KnowledgeChunk(**d)
                self._chunks[chunk.chunk_id] = chunk
            logger.info("Loaded %d chunks from %s", len(self._chunks), path)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load chunks from %s: %s", path, e)

    def _write_index(self):
        path = self.storage / INDEX_FILE
        data = {
            "version": "1.0",
            "total_chunks": len(self._chunks),
            "sources": list(set(c.source for c in self._chunks.values())),
            "tags": list(set(t for c in self._chunks.values() for t in c.tags)),
            "generated_at": _now(),
        }
        path.write_text(json.dumps(data, indent=2))

    # ── Reset ───────────────────────────────────────────────────────────

    def clear(self):
        self._chunks.clear()
        self._dirty = True
        self.save()
