import logging
import os
from typing import List, Dict, Any, Optional

from chroma_store import (
    UnifiedChromaStore, SearchResult,
    WIKI_COLLECTION, KNOWLEDGE_COLLECTION,
)

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, storage_path: str, embedding_dim: int = 768):
        self.storage_path = storage_path
        self.embedding_dim = embedding_dim
        os.makedirs(storage_path, exist_ok=True)
        self.store = UnifiedChromaStore(storage_path, embedding_dim=embedding_dim)

    def insert(self, collection: str, doc_id: str, vector: List[float],
               payload: Dict[str, Any]):
        self.store.add_one(
            collection, doc_id,
            embedding=vector,
            metadata=payload,
            document=payload.get("content", ""),
        )

    def insert_batch(self, collection: str, points: List[Any]):
        ids = []
        embeddings = []
        metadatas = []
        documents = []
        for p in points:
            payload = p.payload if hasattr(p, "payload") else p.get("payload", {})
            doc_id = str(p.id if hasattr(p, "id") else p["id"])
            vec = p.vector if hasattr(p, "vector") else p["vector"]
            ids.append(doc_id)
            embeddings.append(vec)
            metadatas.append(payload)
            documents.append(payload.get("content", ""))
        self.store.add(collection, ids, embeddings, metadatas, documents)

    def search(self, collection: str, vector: List[float],
               top_k: int = 5, score_threshold: Optional[float] = None) -> List[SearchResult]:
        return self.store.search(collection, vector, top_k=top_k, score_threshold=score_threshold)

    def search_all(self, vector: List[float], top_k: int = 5,
                   score_threshold: Optional[float] = None) -> List[SearchResult]:
        return self.store.search_all(vector, top_k=top_k, score_threshold=score_threshold)

    def count(self, collection: str) -> int:
        return self.store.count(collection)

    def delete_collection(self, collection: str):
        self.store.delete_collection(collection)

    def close(self):
        self.store.close()
