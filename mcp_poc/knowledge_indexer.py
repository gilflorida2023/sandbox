import logging
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from embedding_service import EmbeddingService
from vector_store import VectorStore, SearchResult, WIKI_COLLECTION, KNOWLEDGE_COLLECTION
from tool_wiki import ToolWiki

logger = logging.getLogger(__name__)

MIN_CHUNK_LENGTH = 40
MAX_CHUNK_LENGTH = 1500


def chunk_markdown(text: str, source: str, min_len: int = MIN_CHUNK_LENGTH,
                   max_len: int = MAX_CHUNK_LENGTH) -> List[Dict[str, Any]]:
    """Split markdown into chunks by heading boundaries, then by paragraph."""
    chunks = []
    lines = text.split("\n")
    current_heading = ""
    buffer = []

    def flush():
        nonlocal buffer
        if not buffer:
            return
        chunk = "\n".join(buffer).strip()
        if len(chunk) < min_len:
            return
        chunks.append({
            "content": chunk,
            "source": source,
            "tags": [source.split("/")[-1].replace(".md", "").replace("_", " ")]
        })
        buffer = []

    for line in lines:
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()
            # If the heading itself as a standalone chunk is too short,
            # still flush to get clean splits
            flush()
            buffer = [line]
            continue
        buffer.append(line)

    flush()

    if not chunks and len(text.strip()) >= min_len:
        chunks.append({
            "content": text.strip(),
            "source": source,
            "tags": [source.split("/")[-1].replace(".md", "").replace("_", " ")]
        })

    return chunks


class KnowledgeIndexer:
    def __init__(self, embed_service: EmbeddingService, vector_store: VectorStore,
                 wiki: Optional[ToolWiki] = None):
        self.embed = embed_service
        self.store = vector_store
        self.wiki = wiki
        self._indexed = False

    def index_wiki(self, wiki: ToolWiki):
        """Load wiki docs, chunk, embed, and index into Qdrant."""
        wiki_path = wiki.wiki_path
        tools_dir = wiki_path / "tools"
        guides_dir = wiki_path / "guides"

        points = []
        for md_file in sorted(tools_dir.glob("*.md")):
            text = md_file.read_text()
            source = f"wiki/tools/{md_file.name}"
            chunks = chunk_markdown(text, source)
            for chunk in chunks:
                vec = self.embed.embed(chunk["content"])
                if vec:
                    doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["content"]))
                    points.append({
                        "doc_id": doc_id,
                        "vector": vec,
                        "payload": chunk,
                    })

        for md_file in sorted(guides_dir.glob("*.md")):
            text = md_file.read_text()
            source = f"wiki/guides/{md_file.name}"
            chunks = chunk_markdown(text, source)
            for chunk in chunks:
                vec = self.embed.embed(chunk["content"])
                if vec:
                    doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["content"]))
                    points.append({
                        "doc_id": doc_id,
                        "vector": vec,
                        "payload": chunk,
                    })

        if points:
            from qdrant_client.http import models as qmodels
            batch = [
                qmodels.PointStruct(id=p["doc_id"], vector=p["vector"], payload=p["payload"])
                for p in points
            ]
            self.store.insert_batch(WIKI_COLLECTION, batch)
            logger.info("Indexed %d wiki chunks into Qdrant", len(points))
        else:
            logger.info("No wiki chunks to index")

        self._indexed = True

    def add_knowledge_chunk(self, content: str, source: str = "",
                            tags: Optional[List[str]] = None) -> str:
        """Embed and store a single knowledge chunk. Returns the doc_id."""
        vec = self.embed.embed(content)
        if not vec:
            logger.warning("Failed to embed knowledge chunk (empty vector)")
            return ""
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, content))
        self.store.insert(KNOWLEDGE_COLLECTION, doc_id, vec, {
            "content": content,
            "source": source,
            "tags": tags or [],
        })
        return doc_id

    def search(self, query: str, top_k: int = 5,
               score_threshold: Optional[float] = None) -> List[SearchResult]:
        vec = self.embed.embed_query(query)
        if not vec:
            return []
        return self.store.search_all(vec, top_k=top_k, score_threshold=score_threshold)

    def search_wiki(self, query: str, top_k: int = 3) -> List[SearchResult]:
        vec = self.embed.embed_query(query)
        if not vec:
            return []
        return self.store.search(WIKI_COLLECTION, vec, top_k=top_k)

    def format_results(self, results: List[SearchResult], max_chars: int = 2000) -> str:
        """Format search results as a context string for the LLM."""
        if not results:
            return ""
        lines = ["=== Relevant Knowledge (Semantic Search) ==="]
        budget = max_chars
        for r in results:
            clipped = r.content
            if len(clipped) > 400:
                clipped = clipped[:400] + "..."
            entry = f"- [{r.source}] (score={r.score:.3f}) {clipped}"
            if len(entry) > budget:
                break
            lines.append(entry)
            budget -= len(entry)
        return "\n".join(lines)

    @property
    def wiki_count(self) -> int:
        return self.store.count(WIKI_COLLECTION)

    @property
    def knowledge_count(self) -> int:
        return self.store.count(KNOWLEDGE_COLLECTION)

    def close(self):
        self.embed.close()
        self.store.close()
