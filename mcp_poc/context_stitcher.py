import logging
from typing import Dict, List, Optional, Any

from vector_store import VectorStore, SearchResult
from embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class ContextStitcher:
    """Stitches context from previous sessions into the current one.

    Uses semantic search over vector store to find relevant
    past context based on the current user query. Falls back
    to an empty result when no relevant context is found.
    """

    def __init__(self, vector_store: VectorStore, embedding_service: EmbeddingService):
        self.store = vector_store
        self.embed = embedding_service

    def get_session_context(self, user_query: str,
                            max_tokens: int = 500,
                            score_threshold: float = 0.55) -> str:
        query_vector = self.embed.embed_query(user_query)
        if not query_vector:
            return ""

        results = self.store.search_all(
            query_vector,
            top_k=3,
            score_threshold=score_threshold,
        )

        if not results:
            return ""

        return self._format_results(results, max_tokens)

    def _format_results(self, results: List[SearchResult],
                        max_tokens: int) -> str:
        parts = ["=== Context from Previous Sessions ==="]
        max_chars = max_tokens * 4
        budget = max_chars

        for r in results:
            clipped = r.content
            if len(clipped) > 500:
                clipped = clipped[:500] + "..."
            entry = f"\n[From {r.source} (relevance: {r.score:.2f})]\n{clipped}"
            if len(entry) > budget:
                break
            parts.append(entry)
            budget -= len(entry)

        return "\n".join(parts)
