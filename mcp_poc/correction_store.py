import json
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from chroma_store import UnifiedChromaStore, CORRECTIONS_COLLECTION

logger = logging.getLogger(__name__)


class CorrectionStore:
    def __init__(self, storage_path: str):
        self.storage = Path(storage_path)
        self.storage.mkdir(parents=True, exist_ok=True)
        self._store = UnifiedChromaStore(str(self.storage))

    def add_correction(self, topic: str, incorrect: str,
                       correct: str, context: str = ""):
        cid = str(uuid.uuid4())
        self._store.add_one(
            CORRECTIONS_COLLECTION, cid,
            metadata={
                "topic": topic.strip(),
                "incorrect_output": incorrect.strip(),
                "correct_output": correct.strip(),
                "context": context.strip(),
                "created_at": time.time(),
                "applied_count": 0,
            },
            document=topic.strip(),
        )
        logger.info("Stored correction for topic '%s' (id=%s)", topic, cid)

    def get_corrections(self, topic: str, limit: int = 5) -> List[Dict]:
        results = self._store.get(
            CORRECTIONS_COLLECTION,
            where_document={"$contains": topic},
            limit=limit * 2,
        )
        corrections = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                meta = (results.get("metadatas") or [{}])[i] or {}
                corrections.append({
                    "id": results["ids"][i],
                    "topic": meta.get("topic", ""),
                    "incorrect_output": meta.get("incorrect_output", ""),
                    "correct_output": meta.get("correct_output", ""),
                    "context": meta.get("context", ""),
                    "created_at": meta.get("created_at", 0.0),
                    "applied_count": meta.get("applied_count", 0),
                })
        corrections.sort(key=lambda c: c["created_at"], reverse=True)
        return corrections[:limit]

    def get_all_corrections(self, limit: int = 50) -> List[Dict]:
        results = self._store.get(CORRECTIONS_COLLECTION, limit=limit * 2)
        corrections = []
        if results and results.get("ids"):
            for i in range(len(results["ids"])):
                meta = (results.get("metadatas") or [{}])[i] or {}
                corrections.append({
                    "id": results["ids"][i],
                    "topic": meta.get("topic", ""),
                    "incorrect_output": meta.get("incorrect_output", ""),
                    "correct_output": meta.get("correct_output", ""),
                    "context": meta.get("context", ""),
                    "created_at": meta.get("created_at", 0.0),
                    "applied_count": meta.get("applied_count", 0),
                })
        corrections.sort(key=lambda c: c["created_at"], reverse=True)
        return corrections[:limit]

    def increment_applied(self, correction_id: str):
        result = self._store.get_one(CORRECTIONS_COLLECTION, correction_id)
        if result and result.get("metadata"):
            meta = dict(result["metadata"])
            meta["applied_count"] = meta.get("applied_count", 0) + 1
            self._store.update(
                CORRECTIONS_COLLECTION,
                ids=[correction_id],
                metadatas=[meta],
            )

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
        return self._store.count(CORRECTIONS_COLLECTION)

    def close(self):
        pass
