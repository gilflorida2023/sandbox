"""Unified ChromaDB wrapper — single backing store replacing Qdrant + 4 SQLite DBs.

This is the low-level layer. Domain-specific stores (VectorStore,
WindowedContextDB, TaskStore, TodoList, CorrectionStore) will use
this class internally instead of QdrantClient or sqlite3.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError

logger = logging.getLogger(__name__)

# Collection names
WIKI_COLLECTION = "wiki_docs"
KNOWLEDGE_COLLECTION = "knowledge_chunks"
TASKS_COLLECTION = "tasks"
TODOS_COLLECTION = "todos"
CORRECTIONS_COLLECTION = "corrections"
EXPLORATIONS_COLLECTION = "master_index"

DEFAULT_EMBEDDING_DIM = 768
MAX_QUERY_LIMIT = 2 ** 31 - 1


@dataclass
class SearchResult:
    content: str
    source: str
    score: float
    tags: List[str] = field(default_factory=list)
    doc_id: str = ""
    collection: str = ""


class _NoOpEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input):
        return [[] for _ in input]


class UnifiedChromaStore:
    """Low-level wrapper around ChromaDB PersistentClient.

    Provides CRUD + vector search that all domain-specific stores use.
    Embedding dimension is fixed at init time (default 768).
    Non-vector collections (tasks, todos, corrections) store zero embeddings.
    """

    def __init__(self, storage_path: str, embedding_dim: int = DEFAULT_EMBEDDING_DIM):
        self.storage_path = storage_path
        self.embedding_dim = embedding_dim
        os.makedirs(storage_path, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=storage_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collections: dict[str, chromadb.Collection] = {}

    def _zero_embedding(self) -> List[float]:
        return [0.0] * self.embedding_dim

    def _get_collection(self, name: str) -> chromadb.Collection:
        if name not in self._collections:
            try:
                collection = self.client.get_collection(name)
            except NotFoundError:
                collection = self.client.create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=_NoOpEmbeddingFunction(),
                )
            self._collections[name] = collection
        return self._collections[name]

    # ── Core CRUD ──────────────────────────────────────────────────────

    def add(self, collection: str, ids: List[str],
            embeddings: Optional[List[List[float]]] = None,
            metadatas: Optional[List[Dict[str, Any]]] = None,
            documents: Optional[List[str]] = None):
        if embeddings is None:
            embeddings = [self._zero_embedding() for _ in ids]
        col = self._get_collection(collection)
        col.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

    def add_one(self, collection: str, doc_id: str,
                embedding: Optional[List[float]] = None,
                metadata: Optional[Dict[str, Any]] = None,
                document: Optional[str] = None):
        if embedding is None:
            embedding = self._zero_embedding()
        self.add(collection, [doc_id],
                 embeddings=[embedding],
                 metadatas=[metadata] if metadata else None,
                 documents=[document] if document else None)

    def get(self, collection: str, ids: Optional[List[str]] = None,
            where: Optional[Dict[str, Any]] = None,
            where_document: Optional[Dict[str, Any]] = None,
            limit: int = MAX_QUERY_LIMIT, offset: int = 0) -> Dict[str, Any]:
        col = self._get_collection(collection)
        kwargs: Dict[str, Any] = dict(limit=limit, offset=offset)
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        if where_document is not None:
            kwargs["where_document"] = where_document
        return col.get(**kwargs)

    def get_one(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        result = self.get(collection, ids=[doc_id])
        if result and result.get("ids"):
            return {
                "id": result["ids"][0],
                "document": (result.get("documents") or [None])[0],
                "metadata": (result.get("metadatas") or [None])[0],
                "embedding": (result.get("embeddings") or [None])[0],
            }
        return None

    def update(self, collection: str, ids: List[str],
               embeddings: Optional[List[List[float]]] = None,
               metadatas: Optional[List[Dict[str, Any]]] = None,
               documents: Optional[List[str]] = None):
        if embeddings is None:
            embeddings = [self._zero_embedding() for _ in ids]
        col = self._get_collection(collection)
        col.update(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

    def upsert(self, collection: str, ids: List[str],
               embeddings: Optional[List[List[float]]] = None,
               metadatas: Optional[List[Dict[str, Any]]] = None,
               documents: Optional[List[str]] = None):
        if embeddings is None:
            embeddings = [self._zero_embedding() for _ in ids]
        col = self._get_collection(collection)
        col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

    def delete(self, collection: str, ids: Optional[List[str]] = None,
               where: Optional[Dict[str, Any]] = None):
        col = self._get_collection(collection)
        kwargs: Dict[str, Any] = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where is not None:
            kwargs["where"] = where
        col.delete(**kwargs)

    def count(self, collection: str) -> int:
        col = self._get_collection(collection)
        return col.count()

    # ── Vector Search ──────────────────────────────────────────────────

    @staticmethod
    def _cosine_distance_to_similarity(distance: float) -> float:
        return max(0.0, min(1.0, 1.0 - distance / 2.0))

    def query(self, collection: str, query_embeddings: List[List[float]],
              n_results: int = 10, where: Optional[Dict[str, Any]] = None,
              include: Optional[List[str]] = None) -> Dict[str, Any]:
        col = self._get_collection(collection)
        kwargs: Dict[str, Any] = dict(
            query_embeddings=query_embeddings,
            n_results=n_results,
        )
        if where is not None:
            kwargs["where"] = where
        if include is not None:
            kwargs["include"] = include
        return col.query(**kwargs)

    def search(self, collection: str, query_vector: List[float],
               top_k: int = 5, score_threshold: Optional[float] = None,
               where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        try:
            results = self.query(
                collection,
                query_embeddings=[query_vector],
                n_results=top_k,
                where=where,
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            logger.exception("ChromaDB search failed on '%s'", collection)
            return []

        hits = []
        if not results or not results.get("ids") or not results["ids"]:
            return hits

        for i in range(len(results["ids"][0])):
            distance = (results.get("distances") or [[1.0]])[0][i]
            score = self._cosine_distance_to_similarity(distance)
            if score_threshold is not None and score < score_threshold:
                continue

            metadata = (results.get("metadatas") or [[{}]])[0][i] or {}
            document = (results.get("documents") or [[""]])[0][i] or ""
            doc_id = results["ids"][0][i]

            hits.append(SearchResult(
                content=document or metadata.get("content", ""),
                source=metadata.get("source", ""),
                score=score,
                tags=metadata.get("tags", []),
                doc_id=doc_id,
                collection=collection,
            ))

        return hits

    def search_all(self, query_vector: List[float], top_k: int = 5,
                   score_threshold: Optional[float] = None,
                   collections: Optional[List[str]] = None) -> List[SearchResult]:
        targets = collections or [WIKI_COLLECTION, KNOWLEDGE_COLLECTION]
        all_results = []
        for col_name in targets:
            try:
                results = self.search(col_name, query_vector, top_k, score_threshold)
                all_results.extend(results)
            except Exception:
                logger.debug("Collection '%s' not available for search", col_name)
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    # ── Collection Management ──────────────────────────────────────────

    def delete_collection(self, name: str):
        if name in self._collections:
            del self._collections[name]
        try:
            self.client.delete_collection(name)
        except ValueError:
            pass

    def list_collections(self) -> List[str]:
        return [c.name for c in self.client.list_collections()]

    def close(self):
        self._collections.clear()
