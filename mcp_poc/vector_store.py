import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

logger = logging.getLogger(__name__)

WIKI_COLLECTION = "wiki_docs"
KNOWLEDGE_COLLECTION = "knowledge_chunks"


@dataclass
class SearchResult:
    content: str
    source: str
    score: float
    tags: List[str] = field(default_factory=list)
    doc_id: str = ""
    collection: str = ""


class VectorStore:
    def __init__(self, storage_path: str, embedding_dim: int = 768):
        self.storage_path = storage_path
        self.embedding_dim = embedding_dim
        os.makedirs(storage_path, exist_ok=True)
        self.client = QdrantClient(path=storage_path)
        self._ensure_collections()

    def _ensure_collections(self):
        for name in (WIKI_COLLECTION, KNOWLEDGE_COLLECTION):
            if not self.client.collection_exists(name):
                logger.info("Creating Qdrant collection '%s' (dim=%d)", name, self.embedding_dim)
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=qmodels.VectorParams(
                        size=self.embedding_dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                )

    def insert(self, collection: str, doc_id: str, vector: List[float],
               payload: Dict[str, Any]):
        self.client.upsert(
            collection_name=collection,
            points=[qmodels.PointStruct(id=doc_id, vector=vector, payload=payload)],
        )

    def insert_batch(self, collection: str, points: List[qmodels.PointStruct]):
        self.client.upsert(collection_name=collection, points=points)

    def search(self, collection: str, vector: List[float],
               top_k: int = 5, score_threshold: Optional[float] = None) -> List[SearchResult]:
        kwargs = dict(
            collection_name=collection,
            query=vector,
            limit=top_k,
        )
        if score_threshold is not None:
            kwargs["score_threshold"] = score_threshold
        hits = self.client.query_points(**kwargs).points
        results = []
        for hit in hits:
            p = hit.payload or {}
            results.append(SearchResult(
                content=p.get("content", ""),
                source=p.get("source", ""),
                score=hit.score,
                tags=p.get("tags", []),
                doc_id=str(hit.id),
                collection=collection,
            ))
        return results

    def search_all(self, vector: List[float], top_k: int = 5,
                   score_threshold: Optional[float] = None) -> List[SearchResult]:
        wiki_results = self.search(WIKI_COLLECTION, vector, top_k, score_threshold)
        kb_results = self.search(KNOWLEDGE_COLLECTION, vector, top_k, score_threshold)
        combined = sorted(wiki_results + kb_results, key=lambda r: r.score, reverse=True)
        return combined[:top_k]

    def count(self, collection: str) -> int:
        try:
            info = self.client.get_collection(collection)
            return info.points_count
        except Exception:
            return 0

    def delete_collection(self, collection: str):
        try:
            self.client.delete_collection(collection)
        except Exception:
            pass

    def close(self):
        self.client.close()
