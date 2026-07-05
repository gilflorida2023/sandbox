"""Windowed prime-sieve knowledge accumulation system backed by ChromaDB.

API-compatible with the original SQLite-backed version.
Persistence is automatic — save()/load() are no-ops kept for API compat.
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Callable

from chroma_store import UnifiedChromaStore, KNOWLEDGE_COLLECTION

logger = logging.getLogger(__name__)

DB_FILENAME = "knowledge.db"
CHUNKS_FILE = "chunks.json"

DEFAULT_BLACKLIST = {
    "simplesieve", "primesieve", "prime sieve", "sieve of eratosthenes",
}

_regex_blacklist_cache: list = []


def _compile_regex_blacklist(patterns: list) -> list:
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            logger.warning("Invalid regex blacklist pattern %r: %s", p, e)
    return compiled


def _is_contaminated(content: str, blacklist: set = None,
                     blacklist_regex: list = None) -> bool:
    bl = blacklist or DEFAULT_BLACKLIST
    cl = content.lower()
    if any(kw in cl for kw in bl):
        return True
    if blacklist_regex:
        for pattern in blacklist_regex:
            if pattern.search(cl):
                return True
    return False


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _truncate_at_tokens(text: str, max_tokens: int) -> str:
    if _estimate_tokens(text) <= max_tokens:
        return text
    return text[:max_tokens * 4]


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


class WindowedContextDB:
    def __init__(self, storage_path: str, max_window: int = 30,
                 max_total: int = 500, blacklist: set = None,
                 blacklist_regex: list = None):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.max_window = max_window
        self.max_total = max_total
        self.blacklist = blacklist if blacklist is not None else set(DEFAULT_BLACKLIST)
        self.blacklist_regex = _compile_regex_blacklist(blacklist_regex or [])

        db_path = self.storage / DB_FILENAME
        self._db_path = str(db_path)
        self._store = UnifiedChromaStore(str(self.storage))
        self._maybe_migrate_from_json()

    def _maybe_migrate_from_json(self):
        path = self.storage / CHUNKS_FILE
        if not path.exists():
            return
        count = self._store.count(KNOWLEDGE_COLLECTION)
        if count > 0:
            return
        try:
            data = json.loads(path.read_text())
            for d in data:
                self.add(
                    d["content"],
                    source=d.get("source", "manual"),
                    tags=d.get("tags", []),
                )
            logger.info("Migrated %d chunks from %s", len(data), path)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Migration failed from %s: %s", path, e)

    @staticmethod
    def _row_to_chunk(row: dict) -> KnowledgeChunk:
        meta = row.get("metadata") or row
        tags_raw = meta.get("tags", "[]")
        if isinstance(tags_raw, str):
            tags = json.loads(tags_raw) if tags_raw else []
        else:
            tags = tags_raw or []
        document = row.get("document", meta.get("content", ""))
        return KnowledgeChunk(
            chunk_id=row["id"],
            content=document,
            tags=tags,
            source=meta.get("source", "manual"),
            weight=meta.get("weight", 0.5),
            created_at=meta.get("created_at", 0.0),
            accessed_at=meta.get("accessed_at", 0.0),
            access_count=meta.get("access_count", 0),
        )

    def add_blacklist_pattern(self, pattern: str):
        self.blacklist.add(pattern.lower())
        logger.info("Added blacklist pattern: %s", pattern)

    def add_blacklist_regex(self, pattern: str):
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            self.blacklist_regex.append(compiled)
            logger.info("Added regex blacklist pattern: %s", pattern)
        except re.error as e:
            logger.warning("Invalid regex pattern %r: %s", pattern, e)

    def add(self, content: str, source: str = "manual",
            tags: Optional[List[str]] = None) -> str:
        if _is_contaminated(content, self.blacklist, self.blacklist_regex):
            logger.debug("Skipping contaminated chunk: %.80s", content)
            return ""
        chunk = KnowledgeChunk.new(content, source=source, tags=tags)
        existing = self._store.get_one(KNOWLEDGE_COLLECTION, chunk.chunk_id)
        if existing is not None:
            meta = existing.get("metadata") or {}
            weight = min(1.0, meta.get("weight", 0.5) + 0.1)
            access_count = meta.get("access_count", 0) + 1
            now = _now()
            merged_tags = list(set(
                (json.loads(meta.get("tags", "[]")) if isinstance(meta.get("tags"), str) else (meta.get("tags") or []))
            ) | set(chunk.tags))
            self._store.update(
                KNOWLEDGE_COLLECTION,
                ids=[chunk.chunk_id],
                metadatas=[{
                    "weight": weight,
                    "access_count": access_count,
                    "accessed_at": now,
                    "tags": json.dumps(merged_tags),
                    "source": source,
                    "created_at": meta.get("created_at", now),
                }],
                documents=[chunk.content],
            )
            logger.debug("Bumped existing chunk %s (weight=%.2f, access=%d)",
                         chunk.chunk_id, weight, access_count)
            return chunk.chunk_id

        tags_json = json.dumps(chunk.tags)
        self._store.add_one(
            KNOWLEDGE_COLLECTION, chunk.chunk_id,
            metadata={
                "source": chunk.source,
                "tags": tags_json,
                "weight": chunk.weight,
                "created_at": chunk.created_at,
                "accessed_at": chunk.accessed_at,
                "access_count": chunk.access_count,
            },
            document=chunk.content,
        )
        logger.info("Added chunk %s (source=%s, tags=%s)",
                     chunk.chunk_id, source, tags)
        return chunk.chunk_id

    def add_chunk(self, chunk: KnowledgeChunk) -> str:
        existing = self._store.get_one(KNOWLEDGE_COLLECTION, chunk.chunk_id)
        if existing is not None:
            meta = existing.get("metadata") or {}
            weight = min(1.0, meta.get("weight", 0.5) + 0.1)
            access_count = meta.get("access_count", 0) + 1
            now = _now()
            merged_tags = list(set(
                (json.loads(meta.get("tags", "[]")) if isinstance(meta.get("tags"), str) else (meta.get("tags") or []))
            ) | set(chunk.tags))
            self._store.update(
                KNOWLEDGE_COLLECTION,
                ids=[chunk.chunk_id],
                metadatas=[{
                    "weight": weight,
                    "access_count": access_count,
                    "accessed_at": now,
                    "tags": json.dumps(merged_tags),
                    "source": chunk.source,
                }],
            )
            return chunk.chunk_id

        self._store.add_one(
            KNOWLEDGE_COLLECTION, chunk.chunk_id,
            metadata={
                "source": chunk.source,
                "tags": json.dumps(chunk.tags),
                "weight": chunk.weight,
                "created_at": chunk.created_at,
                "accessed_at": chunk.accessed_at,
                "access_count": chunk.access_count,
            },
            document=chunk.content,
        )
        return chunk.chunk_id

    def query(self, text: str, max_results: int = 5) -> List[KnowledgeChunk]:
        terms = [t for t in text.lower().split() if len(t) > 2]
        if not terms:
            return []

        # Try content-based $contains search via where_document
        try:
            # Use the first few meaningful terms for matching
            query_terms = " ".join(terms[:5])
            results = self._store.get(
                KNOWLEDGE_COLLECTION,
                where_document={"$contains": query_terms},
                limit=max_results * 5,
            )
        except Exception:
            results = {"ids": [], "metadatas": [], "documents": []}

        scored = []
        seen_ids = set()
        fts_rows = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                meta = (results.get("metadatas") or [{}])[i] or {}
                doc = (results.get("documents") or [""])[i] or ""
                fts_rows.append({
                    "id": results["ids"][i],
                    "metadata": meta,
                    "document": doc,
                })

        if fts_rows:
            now = _now()
            for row in fts_rows:
                meta = row["metadata"]
                tags_raw = meta.get("tags", "[]")
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                chunk = KnowledgeChunk(
                    chunk_id=row["id"],
                    content=row["document"],
                    tags=tags,
                    source=meta.get("source", ""),
                    weight=meta.get("weight", 0.5),
                    created_at=meta.get("created_at", 0.0),
                    accessed_at=meta.get("accessed_at", 0.0),
                    access_count=meta.get("access_count", 0),
                )
                tag_score = _match_tags(chunk.tags, text)
                content_score = _match_content(chunk.content, text)
                combined = (tag_score * 0.4 + content_score * 0.6) * chunk.current_weight()
                scored.append((combined, chunk))
                seen_ids.add(chunk.chunk_id)

        # Fallback: scan all if FTS-like search returned nothing
        if not scored:
            all_results = self._store.get(KNOWLEDGE_COLLECTION)
            if all_results and all_results.get("ids"):
                for i in range(len(all_results["ids"])):
                    meta = (all_results.get("metadatas") or [{}])[i] or {}
                    doc = (all_results.get("documents") or [""])[i] or ""
                    tags_raw = meta.get("tags", "[]")
                    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                    chunk = KnowledgeChunk(
                        chunk_id=all_results["ids"][i],
                        content=doc,
                        tags=tags,
                        source=meta.get("source", ""),
                        weight=meta.get("weight", 0.5),
                        created_at=meta.get("created_at", 0.0),
                        accessed_at=meta.get("accessed_at", 0.0),
                        access_count=meta.get("access_count", 0),
                    )
                    tag_score = _match_tags(chunk.tags, text)
                    content_score = _match_content(chunk.content, text)
                    if tag_score == 0.0 and content_score == 0.0:
                        continue
                    combined = (tag_score * 0.4 + content_score * 0.6) * chunk.current_weight()
                    scored.append((combined, chunk))

        scored.sort(key=lambda x: -x[0])
        results_list = [chunk for _, chunk in scored[:max_results]]

        for chunk in results_list:
            meta = self._store.get_one(KNOWLEDGE_COLLECTION, chunk.chunk_id)
            if meta:
                m = meta.get("metadata") or {}
                self._store.update(
                    KNOWLEDGE_COLLECTION,
                    ids=[chunk.chunk_id],
                    metadatas=[{
                        **m,
                        "access_count": m.get("access_count", 0) + 1,
                        "accessed_at": _now(),
                    }],
                )

        return results_list

    def window(self, max_size: Optional[int] = None) -> List[KnowledgeChunk]:
        size = max_size or self.max_window
        results = self._store.get(KNOWLEDGE_COLLECTION)
        chunks = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                meta = (results.get("metadatas") or [{}])[i] or {}
                doc = (results.get("documents") or [""])[i] or ""
                tags_raw = meta.get("tags", "[]")
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                chunks.append(KnowledgeChunk(
                    chunk_id=results["ids"][i],
                    content=doc,
                    tags=tags,
                    source=meta.get("source", ""),
                    weight=meta.get("weight", 0.5),
                    created_at=meta.get("created_at", 0.0),
                    accessed_at=meta.get("accessed_at", 0.0),
                    access_count=meta.get("access_count", 0),
                ))
        chunks.sort(key=lambda c: c.current_weight(), reverse=True)
        return chunks[:size]

    def prune(self, max_total: Optional[int] = None) -> int:
        limit = max_total or self.max_total
        results = self._store.get(KNOWLEDGE_COLLECTION)
        if not results or not results.get("ids"):
            return 0
        count = len(results["ids"])
        if count <= limit:
            return 0
        excess = count - limit
        chunks = []
        for i in range(len(results["ids"])):
            meta = (results.get("metadatas") or [{}])[i] or {}
            doc = (results.get("documents") or [""])[i] or ""
            tags_raw = meta.get("tags", "[]")
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
            chunks.append((KnowledgeChunk(
                chunk_id=results["ids"][i],
                content=doc,
                tags=tags,
                source=meta.get("source", ""),
                weight=meta.get("weight", 0.5),
                created_at=meta.get("created_at", 0.0),
                accessed_at=meta.get("accessed_at", 0.0),
                access_count=meta.get("access_count", 0),
            ), results["ids"][i]))
        chunks.sort(key=lambda x: x[0].current_weight())
        evict_ids = [cid for _, cid in chunks[:excess]]
        for cid in evict_ids:
            self._store.delete(KNOWLEDGE_COLLECTION, ids=[cid])
        removed = excess
        logger.info("Pruned %d chunks (kept %d / %d max)",
                     removed, limit, limit)
        return removed

    def count(self) -> int:
        return self._store.count(KNOWLEDGE_COLLECTION)

    def ingest_session_log(self, log_path: str, store_callback=None) -> int:
        path = Path(log_path)
        if not path.exists():
            logger.warning("Session log not found: %s", log_path)
            return 0

        store = store_callback or self.add
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
                    store(f"Decision: {decision}",
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
                    store(f"Roadblock: {rb}",
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
                    store(f"Action: {ai}",
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
                    store(f"Idea: {idea}",
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
                    store(f"Concept: {concept}",
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
                    store(f"Term: {term}",
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

    def add_note(self, content: str, tags: Optional[List[str]] = None) -> str:
        return self.add(content, source="note", tags=tags)

    def add_guide(self, name: str, content: str) -> str:
        return self.add(content, source="guide", tags=["guide", name])

    def save(self):
        pass

    def load(self):
        pass

    def clear(self):
        docs = self._store.get(KNOWLEDGE_COLLECTION)
        if docs and docs.get("ids"):
            self._store.delete(KNOWLEDGE_COLLECTION, ids=docs["ids"])
