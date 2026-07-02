import logging
import hashlib
from typing import List, Optional, Dict

import httpx

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, host: str = "localhost", port: int = 11434,
                 model: str = "nomic-embed-text", timeout: int = 30):
        self.base_url = f"http://{host}:{port}"
        self.model = model
        self._client = httpx.Client(timeout=timeout)
        self._dimension: Optional[int] = None
        self._cache: Dict[str, List[float]] = {}
        self._max_cache = 2048
        self.call_count: int = 0
        self.total_chars: int = 0

    def embed(self, text: str) -> List[float]:
        self.call_count += 1
        self.total_chars += len(text)
        batch = self.embed_batch([text])
        return batch[0] if batch else []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        uncached = []
        indices = []
        for i, t in enumerate(texts):
            key = self._cache_key(t)
            if key in self._cache:
                continue
            uncached.append(t)
            indices.append(i)
        if uncached:
            try:
                resp = self._client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": uncached},
                )
                resp.raise_for_status()
                data = resp.json()
                batch_embs = data.get("embeddings", [])
                if self._dimension is None and batch_embs:
                    self._dimension = len(batch_embs[0])
                for t, emb in zip(uncached, batch_embs):
                    key = self._cache_key(t)
                    self._cache[key] = emb
                    if len(self._cache) > self._max_cache:
                        oldest = next(iter(self._cache))
                        del self._cache[oldest]
            except Exception as e:
                logger.error("Embedding API call failed: %s", e)
                return []
        result = [self._cache.get(self._cache_key(t), []) for t in texts]
        return result

    def embed_query(self, query: str) -> List[float]:
        return self.embed(query)

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self.embed("_probe_")
        return self._dimension or 768

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def close(self):
        self._client.close()
