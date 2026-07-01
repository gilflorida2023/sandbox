# Current Plan: Context Management & Tiny Model Orchestration

**Date:** 2026-07-01
**Author:** Builder (AI Agent)
**Status:** Active Planning

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current System State](#current-system-state)
3. [Phase 1: Foundation — Context Control & Contamination Prevention](#phase-1-foundation--context-control--contamination-prevention)
4. [Phase 2: Intelligence — Semantic Search & User-Controlled Knowledge](#phase-2-intelligence--semantic-search--user-controlled-knowledge)
5. [Phase 3: Advanced — Task Continuity & Context Stitching](#phase-3-advanced--task-continuity--context-stitching)
6. [Testing & Validation Phase](#testing--validation-phase)
7. [Rollback / Recovery Plan](#rollback--recovery-plan)
8. [Success Criteria](#success-criteria)

---

## Executive Summary

### Problem Statement

Small language models (glm4:9b, ~8K context) are being used as coding agents. The current system faces four critical issues:

1. **Context Contamination** — Old session data (e.g., prime sieve code) leaks into new conversations via the knowledge database, causing the model to generate irrelevant or incorrect code.
2. **Context Bloat** — Wiki documentation and knowledge chunks are auto-injected into every prompt without token budgeting, wasting the limited context window.
3. **No Semantic Retrieval** — All context retrieval is keyword-based (substring matching + FTS5), which cannot find conceptually related content.
4. **No User Control** — Knowledge is automatically accumulated from session logs without user review, enabling "poison pills" (incorrect or harmful facts) to persist indefinitely.

### Design Philosophy

- **Tiny models need tiny, focused context.** Every token counts. Less is more.
- **Users trust what they approve.** Knowledge should only persist with explicit user consent.
- **Semantic search > keyword search.** Concepts matter more than exact word matches.
- **Session memory is ephemeral.** Long-term memory requires curation.
- **Continuity is engineered, not automatic.** Context must be actively managed across turns and sessions.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User Input                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Context Budget Manager                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Session Mem  │  │ Convo Mem    │  │ Semantic Docs │  │
│  │ (500 tokens) │  │ (500 tokens) │  │ (500 tokens)  │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ Active Task  │  │ Wiki Ref     │                     │
│  │ (500 tokens) │  │ (on demand)  │                     │
│  └──────────────┘  └──────────────┘                     │
│  Total: 2000 tokens max                                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Knowledge Layer                             │
│  ┌─────────────────────┐  ┌──────────────────────────┐   │
│  │ Vector DB (Qdrant)  │  │ User-Approved Store      │   │
│  │ - Semantic search   │  │ - Vetted knowledge only  │   │
│  │ - Domain expertise  │  │ - Trust/distrust flags   │   │
│  └─────────────────────┘  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Current System State

### What Already Works

| Component | Status | Notes |
|-----------|--------|-------|
| Session log extraction | ✅ Works | Extracts decisions, roadblocks, ideas via `take-minutes` |
| Knowledge DB (SQLite) | ✅ Works | FTS5 full-text search, weight decay, dedup by SHA-256 |
| Context injection | ✅ Works | Wiki docs + knowledge chunks injected into system prompts |
| Token budgeting | ✅ Partially | `context_manager.py` has `max_tokens=2000` parameter (just added) |
| Contamination blacklist | ✅ Partially | Hardcoded sieve/prime keywords (just added) |
| Session log auto-ingestion | ❌ Disabled | Disabled to prevent contamination (just disabled) |
| Wiki doc auto-injection | ❌ Removed | Per-tool wiki doc injection removed (just removed) |

### What Needs Building

| Component | Priority | Complexity |
|-----------|----------|------------|
| Semantic search (vector DB) | High | Medium |
| User review mechanism | High | Low |
| Context budget enforcement | High | Low |
| Session continuity | Medium | High |
| Cross-session state | Medium | High |
| Wiki version control | Low | Low |
| Testing framework | High | Medium |

### Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `mcp_poc/agent.py` | Main agent orchestrator | 1060 |
| `mcp_poc/context_manager.py` | Context assembly + injection | 152 |
| `mcp_poc/windowed_context_db.py` | SQLite knowledge accumulator | 524 |
| `mcp_poc/tool_wiki.py` | Wiki documentation reader | 53 |
| `mcp_poc/config.py` | Configuration dataclasses | 59 |
| `mcp_poc/config.yaml` | Runtime configuration | 22 |
| `mcp_poc/session_log.py` | Session logging + extraction | 278 |
| `mcp_poc/ollama_client.py` | Ollama API client | 133 |
| `mcp_poc/workflows/` | Pipeline workflows | 4 files |

---

## Phase 1: Foundation — Context Control & Contamination Prevention

**Goal:** Eliminate immediate contamination vectors, enforce context budgets, and establish user control over knowledge persistence.

**Timeline:** 2-3 sessions

### 1.1 Contamination Blacklist (✅ DONE)

**What:** Keyword-based filter that blocks known contamination patterns from entering the knowledge DB.

**Where:** `windowed_context_db.py:29-33`

**Current implementation:**
```python
CONTAMINATION_BLACKLIST = {
    "simplesieve", "primesieve", "prime sieve", "sieve of eratosthenes",
}
```

**Remaining work:**
- [ ] Make blacklist configurable via `config.yaml` (e.g., `agent.knowledge_blacklist: ["sieve", "prime"]`)
- [ ] Add ability for users to extend blacklist at runtime
- [ ] Consider regex patterns instead of substring matching for more precise filtering

### 1.2 Session Log Auto-Ingestion (✅ DONE)

**What:** Disabled the automatic ingestion of past session logs on startup.

**Where:** `agent.py:196-201` (replaced with comment)

**Current state:**
```python
# Knowledge ingestion on startup is disabled by default.
# Past session logs can contain task-specific noise (e.g. prime sieve code)
# that contaminates future sessions when injected as "Accumulated Knowledge".
```

### 1.3 Wiki Doc Auto-Injection (✅ DONE)

**What:** Removed per-tool wiki documentation auto-injection during tool execution loops.

**Where:** `agent.py` (removed `_get_tool_wiki_doc` method, `wiki_injected` tracking, and injection code in both `run()` and `chat()` methods)

**Rationale:** The model can call `wiki.lookup` on demand. Auto-injecting docs for every tool burns context tokens unnecessarily. This gives the model control over when it needs documentation.

### 1.4 Token Budget Enforcement (✅ DONE - needs refinement)

**What:** Added `max_tokens` parameter to context retrieval methods with budget-aware truncation.

**Where:** `context_manager.py`

**Current implementation:**
```python
def get_relevant_context(self, query: str, max_tokens: int = 2000):
    # Token-budget-aware section processing
    budget = max_tokens
    # Each section deducts from budget, stops when exhausted
    
def get_knowledge_window(self, max_size=None, max_tokens=1000):
    # Entry-level budget check
```

**Remaining work:**
- [ ] Add token estimation unit tests
- [ ] Consider using actual tokenizer (e.g., `tiktoken`) instead of `len(text) // 4`
- [ ] Add warning logs when context is truncated
- [ ] Implement progressive disclosure: show context summary first, full context on request

### 1.5 Knowledge DB Cleanup (✅ DONE)

**What:** Deleted contaminated `knowledge.db` to remove all prime sieve artifacts.

**Where:** `workspace/.context/knowledge/knowledge.db`

**Note:** The DB will be recreated empty on next system start. All prior accumulated knowledge is lost and must be rebuilt through the new curated workflow.

### 1.6 User Approval Gate for Knowledge Storage (🔴 NOT STARTED)

**What:** Before any knowledge chunk is stored, present it to the user for approval.

**Where:** New file `mcp_poc/user_approval.py` or extend `context_manager.py`

**Design:**
```python
class ApprovalManager:
    """Manages user review of proposed knowledge chunks."""
    
    def __init__(self):
        self.pending = {}  # chunk_id → KnowledgeChunk (awaiting approval)
        self.approved = set()  # chunk_ids that passed review
        self.rejected = set()  # chunk_ids that were denied
        self.blacklist_patterns = set()  # user-defined patterns to auto-reject
    
    def propose_knowledge(self, chunk: KnowledgeChunk) -> str:
        """Submit a chunk for user approval. Returns chunk_id."""
        self.pending[chunk.chunk_id] = chunk
        return chunk.chunk_id
    
    def approve(self, chunk_id: str) -> bool:
        """User approved this chunk. Move to approved set."""
        if chunk_id in self.pending:
            self.approved.add(chunk_id)
            del self.pending[chunk_id]
            return True
        return False
    
    def reject(self, chunk_id: str) -> bool:
        """User rejected this chunk. Add to blacklist pattern set."""
        self.rejected.add(chunk_id)
        if chunk_id in self.pending:
            del self.pending[chunk_id]
        return True
    
    def get_pending_summary(self) -> List[Dict]:
        """Return pending chunks for user review display."""
        summaries = []
        for chunk_id, chunk in self.pending.items():
            summaries.append({
                "id": chunk_id,
                "content_preview": chunk.content[:200],
                "source": chunk.source,
                "tags": chunk.tags,
                "timestamp": chunk.created_at
            })
        return summaries
```

**Integration points:**
- `agent.py`: After session log extraction, route chunks through `ApprovalManager.propose_knowledge()` before calling `add()`
- CLI: Add `/approve`, `/reject`, `/pending` commands in the REPL
- Only chunks in `self.approved` are injected as "Accumulated Knowledge"

### 1.7 Configuration Refinements

**What:** Expose new settings in `config.yaml` for user control.

**Add to `config.yaml`:**
```yaml
agent:
  max_turns: 20
  temperature: 0.1
  max_context_tokens: 2000
  
  knowledge:
    ingest_on_startup: false
    require_user_approval: true
    blacklist:
      - "sieve"
      - "prime"
      - "simplesieve"
    max_chunks_per_session: 50
  
  context:
    session_tokens: 500
    conversation_tokens: 500
    knowledge_tokens: 500
    task_tokens: 500
```

**Add to `config.py`:**
```python
@dataclass
class AgentKnowledgeConfig:
    ingest_on_startup: bool = False
    require_user_approval: bool = True
    blacklist: List[str] = field(default_factory=lambda: ["sieve", "prime"])
    max_chunks_per_session: int = 50

@dataclass
class AgentContextConfig:
    session_tokens: int = 500
    conversation_tokens: int = 500
    knowledge_tokens: int = 500
    task_tokens: int = 500
```

---

## Phase 2: Intelligence — Semantic Search & User-Controlled Knowledge

**Goal:** Replace keyword-based context retrieval with semantic search, enabling the system to find conceptually relevant content across sessions without contamination.

**Timeline:** 3-5 sessions

### 2.1 Vector Database Setup

**What:** Install and configure Qdrant (self-hosted, local mode) for semantic search.

**New dependency:** `qdrant-client`

**Design:**
```python
class SemanticVectorStore:
    """Qdrant-backed vector store for semantic knowledge retrieval."""
    
    def __init__(self, collection_name="domain_knowledge", 
                 embedding_dim=768, local_path="./.vectorstore"):
        self.client = QdrantClient(path=local_path)
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        if not any(c.name == self.collection_name for c in collections):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
    
    def upsert_document(self, doc_id: str, vector: List[float], 
                        payload: Dict[str, Any]):
        """Store or update a document with its embedding vector."""
        self.client.upsert(
            collection_name=self.collection_name,
            points=[PointStruct(
                id=doc_id,
                vector=vector,
                payload=payload
            )]
        )
    
    def search(self, query_vector: List[float], 
               limit: int = 5,
               score_threshold: float = 0.7) -> List[Dict]:
        """Search for similar documents."""
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold
        )
        return [
            {
                "id": r.id,
                "score": r.score,
                "content": r.payload.get("content", ""),
                "source": r.payload.get("source", ""),
                "tags": r.payload.get("tags", [])
            }
            for r in results
        ]
```

### 2.2 Embedding Service

**What:** Create a lightweight embedding service using `nomic-embed-text` via Ollama (already available on the system).

**Design:**
```python
class EmbeddingService:
    """Generates embeddings using nomic-embed-text via Ollama."""
    
    def __init__(self, model="nomic-embed-text", ollama_host="localhost:11434"):
        self.model = model
        self.client = httpx.AsyncClient(base_url=f"http://{ollama_host}")
        self._cache = {}  # text_hash → vector (to avoid redundant encoding)
    
    async def embed(self, text: str) -> List[float]:
        """Generate embedding vector for text."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if text_hash in self._cache:
            return self._cache[text_hash]
        
        response = await self.client.post("/api/embeddings", json={
            "model": self.model,
            "prompt": text
        })
        result = response.json()
        vector = result.get("embedding", [])
        self._cache[text_hash] = vector
        return vector
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts in batch."""
        tasks = [self.embed(t) for t in texts]
        return await asyncio.gather(*tasks)
```

### 2.3 Semantic Context Retrieval Integration

**What:** Replace the keyword-based `get_relevant_context()` in `context_manager.py` with a hybrid approach: semantic search first, keyword fallback.

**Design:**
```python
class SemanticContextManager(ContextManager):
    """Extends ContextManager with semantic search capabilities."""
    
    def __init__(self, wiki, knowledge_path=None):
        super().__init__(wiki, knowledge_path)
        self.embedding = EmbeddingService()
        self.vector_store = SemanticVectorStore()
    
    async def get_relevant_context(self, query: str, 
                                    max_tokens: int = 2000) -> Optional[str]:
        """Hybrid retrieval: semantic search + keyword fallback."""
        
        # 1. Try semantic search first
        query_vector = await self.embedding.embed(query)
        semantic_results = self.vector_store.search(
            query_vector, limit=5, score_threshold=0.7
        )
        
        if len(semantic_results) >= 2:
            # Use semantic results
            parts = self._format_semantic_results(semantic_results)
            return self._apply_token_budget(parts, max_tokens)
        
        # 2. Fallback to keyword-based (existing logic)
        parts = self._keyword_search(query)
        if parts:
            return self._apply_token_budget(parts, max_tokens)
        
        # 3. Absolute fallback: getting_started guide
        return self._get_fallback(max_tokens)
    
    def _format_semantic_results(self, results: List[Dict]) -> List[str]:
        """Format semantic search results for prompt injection."""
        parts = []
        for r in results:
            tag = "Semantic Match" if r["score"] > 0.85 else "Related Knowledge"
            parts.append(f"=== {tag} (score: {r['score']:.2f}) ===")
            parts.append(r["content"][:1500])  # Truncate per result
        return parts
```

### 2.4 Document Chunking Pipeline

**What:** Pre-process wiki documents and session knowledge into embedding-friendly chunks.

**Design:**
```python
class KnowledgeChunker:
    """Splits documents into chunks optimized for embedding + retrieval."""
    
    def __init__(self, chunk_size=800, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
    
    def chunk_wiki_docs(self, wiki_path: str) -> List[Dict]:
        """Process all wiki docs into chunks."""
        chunks = []
        wiki_dir = Path(wiki_path)
        
        # Process tool docs
        for tool_file in (wiki_dir / "tools").glob("*.md"):
            content = tool_file.read_text()
            doc_chunks = self.splitter.split_text(content)
            for i, chunk in enumerate(doc_chunks):
                chunks.append({
                    "content": chunk,
                    "source": f"wiki/tools/{tool_file.name}",
                    "tags": ["wiki", "tool", tool_file.stem],
                    "chunk_index": i
                })
        
        # Process guides
        for guide_file in (wiki_dir / "guides").glob("*.md"):
            content = guide_file.read_text()
            doc_chunks = self.splitter.split_text(content)
            for i, chunk in enumerate(doc_chunks):
                chunks.append({
                    "content": chunk,
                    "source": f"wiki/guides/{guide_file.name}",
                    "tags": ["wiki", "guide", guide_file.stem],
                    "chunk_index": i
                })
        
        return chunks
    
    def chunk_knowledge_chunks(self, knowledge_entries: List[Dict]) -> List[Dict]:
        """Process knowledge base entries into searchable chunks."""
        chunks = []
        for entry in knowledge_entries:
            if len(entry["content"]) > self.chunk_size:
                # Split long entries
                doc_chunks = self.splitter.split_text(entry["content"])
                for i, chunk in enumerate(doc_chunks):
                    chunks.append({
                        "content": chunk,
                        "source": entry.get("source", "knowledge"),
                        "tags": entry.get("tags", []) + [f"chunk_{i}"],
                        "original_id": entry.get("id")
                    })
            else:
                chunks.append(entry)
        return chunks
```

### 2.5 Knowledge Indexing Pipeline

**What:** When user-approved knowledge or wiki docs are available, index them into the vector store.

**Design:**
```python
class KnowledgeIndexer:
    """Orchestrates chunking + embedding + storage of knowledge."""
    
    def __init__(self, chunker=None, embedder=None, vector_store=None):
        self.chunker = chunker or KnowledgeChunker()
        self.embedder = embedder or EmbeddingService()
        self.vector_store = vector_store or SemanticVectorStore()
    
    async def index_wiki(self, wiki_path: str):
        """Index all wiki documentation."""
        chunks = self.chunker.chunk_wiki_docs(wiki_path)
        texts = [c["content"] for c in chunks]
        vectors = await self.embedder.embed_batch(texts)
        
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(
                f"{chunk['source']}:{chunk['chunk_index']}".encode()
            ).hexdigest()[:16]
            self.vector_store.upsert_document(
                doc_id=chunk_id,
                vector=vectors[i],
                payload={
                    "content": chunk["content"],
                    "source": chunk["source"],
                    "tags": chunk["tags"],
                    "type": "wiki"
                }
            )
    
    async def index_knowledge(self, knowledge_entries: List[Dict]):
        """Index user-approved knowledge chunks."""
        chunks = self.chunker.chunk_knowledge_chunks(knowledge_entries)
        if not chunks:
            return
        
        texts = [c["content"] for c in chunks]
        vectors = await self.embedder.embed_batch(texts)
        
        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get("id") or hashlib.sha256(
                chunk["content"].encode()
            ).hexdigest()[:16]
            self.vector_store.upsert_document(
                doc_id=chunk_id,
                vector=vectors[i],
                payload={
                    "content": chunk["content"],
                    "source": chunk.get("source", "knowledge"),
                    "tags": chunk.get("tags", []),
                    "type": "knowledge"
                }
            )
```

---

## Phase 3: Advanced — Task Continuity & Context Stitching

**Goal:** Enable the system to maintain context across turns and sessions, enabling natural multi-turn conversations and cross-session knowledge continuity.

**Timeline:** 4-6 sessions

### 3.1 Session State Manager

**What:** Store session state (conversation thread, active tasks, pending items) that persists across invocations.

**Design:**
```python
class SessionState:
    """Persists conversation state across invocations."""
    
    def __init__(self, session_id: str, storage_path: str = "./.session_state"):
        self.session_id = session_id
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_path / f"{session_id}.json"
        self._state = self._load()
    
    def _load(self) -> Dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {
            "session_id": self.session_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "turn_count": 0,
            "active_task": None,
            "task_history": [],
            "pending_approvals": [],
            "conversation_summary": "",
            "referenced_files": [],
            "context_fragments": []
        }
    
    def save(self):
        self._state["updated_at"] = time.time()
        self.state_file.write_text(json.dumps(self._state, indent=2))
    
    def update_task(self, task: str):
        self._state["active_task"] = task
        self._state["task_history"].append({
            "task": task,
            "timestamp": time.time()
        })
        self.save()
    
    def add_context_fragment(self, fragment: Dict):
        """Store a context fragment for later retrieval."""
        self._state["context_fragments"].append({
            **fragment,
            "timestamp": time.time()
        })
        self.save()
    
    def get_recent_context(self, max_fragments: int = 5) -> List[Dict]:
        """Get most recent context fragments."""
        fragments = self._state["context_fragments"]
        return fragments[-max_fragments:]
```

### 3.2 Conversation Summarization

**What:** When a conversation exceeds the context window, summarize previous turns to maintain continuity without losing key information.

**Design:**
```python
class ConversationSummarizer:
    """Summarizes conversation history for context window management."""
    
    def __init__(self, ollama_client, max_summary_tokens=300):
        self.ollama = ollama_client
        self.max_summary_tokens = max_summary_tokens
    
    async def summarize_turns(self, messages: List[Dict]) -> str:
        """Summarize a list of conversation turns."""
        # Only summarize if there are enough turns
        if len(messages) < 6:
            return ""
        
        # Convert messages to summary text
        turn_text = self._messages_to_text(messages[:-2])  # Keep last 2 turns intact
        
        summary_prompt = (
            "Summarize the following conversation turns, preserving:\n"
            "- The user's goal/task\n"
            "- Key decisions made\n"
            "- Files created or modified\n"
            "- Any issues or blockers encountered\n"
            "- Important findings or insights\n\n"
            f"{turn_text}\n\nSummary:"
        )
        
        response = await self.ollama.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            tools=None  # No tools needed for summarization
        )
        
        summary = response.get("message", {}).get("content", "")
        
        # Truncate to budget
        if len(summary) > self.max_summary_tokens * 4:
            summary = summary[:self.max_summary_tokens * 4]
        
        return summary
    
    def _messages_to_text(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:500]  # Truncate per message
            lines.append(f"[{role.upper()}]: {content}")
        return "\n".join(lines)
```

### 3.3 Context Stitching

**What:** When resuming a session, pull relevant context from previous sessions based on the current user query.

**Design:**
```python
class ContextStitcher:
    """Stitches context from previous sessions into the current one."""
    
    def __init__(self, vector_store, embedding_service):
        self.vector_store = vector_store
        self.embedding = embedding_service
    
    async def get_session_context(self, user_query: str, 
                                    session_id: str = None,
                                    max_tokens: int = 500) -> str:
        """Retrieve relevant context from past sessions."""
        
        # 1. Get query embedding
        query_vector = await self.embedding.embed(user_query)
        
        # 2. Search for relevant past context
        results = self.vector_store.search(
            query_vector, 
            limit=3, 
            score_threshold=0.65  # Lower threshold for broader recall
        )
        
        if not results:
            return ""
        
        # 3. Format results with source attribution
        parts = ["=== Context from Previous Sessions ==="]
        token_count = 0
        max_chars = max_tokens * 4
        
        for r in results:
            entry = f"\n[From {r['source']} (relevance: {r['score']:.2f})]\n{r['content'][:500]}"
            if token_count + len(entry) // 4 > max_tokens:
                break
            parts.append(entry)
            token_count += len(entry) // 4
        
        return "\n".join(parts)
```

### 3.4 Task Context Persistence

**What:** Store task context (what were we working on, what files were involved) so the model can pick up where it left off.

**Design:**
```python
@dataclass
class TaskContext:
    """Describes a task the system was working on."""
    task_id: str
    task_description: str
    session_id: str
    files_involved: List[str]
    decisions: List[str]
    blockers: List[str]
    code_created: List[str]
    status: str  # "in_progress", "completed", "blocked", "abandoned"
    last_updated: float
```

**Storage:** Use the same SQLite DB with a new `tasks` table.

```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_description TEXT NOT NULL,
    session_id TEXT NOT NULL,
    files_involved TEXT NOT NULL DEFAULT '[]',
    decisions TEXT NOT NULL DEFAULT '[]',
    blockers TEXT NOT NULL DEFAULT '[]',
    code_created TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at REAL NOT NULL,
    last_updated REAL NOT NULL
);
```

**Integration:**
- After each session, summarize the task into a `TaskContext` and store it
- On new session start, check if the user query references a previous task
- If so, load that task's context and inject it as "Previous Task Context"

### 3.5 User Feedback Loop

**What:** Allow users to correct the AI's responses, with the correction stored as a "correction record" that influences future behavior.

**Design:**
```python
class CorrectionStore:
    """Stores user corrections to prevent repeated mistakes."""
    
    def __init__(self, storage_path: str = "./.corrections"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite corrections table."""
        self.db = sqlite3.connect(str(self.storage_path / "corrections.db"))
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                incorrect_output TEXT NOT NULL,
                correct_output TEXT NOT NULL,
                context TEXT,
                created_at REAL NOT NULL,
                applied_count INTEGER DEFAULT 0
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_corrections_topic 
            ON corrections(topic)
        """)
        self.db.commit()
    
    def add_correction(self, topic: str, incorrect: str, correct: str, context: str = ""):
        """Store a user correction."""
        self.db.execute(
            """INSERT INTO corrections (topic, incorrect_output, correct_output, context, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (topic, incorrect, correct, context, time.time())
        )
        self.db.commit()
    
    def get_corrections(self, topic: str) -> List[Dict]:
        """Get relevant corrections for a topic."""
        rows = self.db.execute(
            "SELECT * FROM corrections WHERE topic LIKE ? ORDER BY created_at DESC LIMIT 5",
            (f"%{topic}%",)
        ).fetchall()
        return [dict(r) for r in rows]
```

**CLI Integration:**
- User types `/correct "incorrect statement" -> "correct statement"`
- System stores the correction
- On future queries about similar topics, corrections are injected as "User Corrections" context

---

## Testing & Validation Phase

**Goal:** Ensure all changes work correctly, don't break existing functionality, and measurably improve context quality.

**Timeline:** 2-3 sessions (can run in parallel with Phase 2 and 3 work)

### 4.1 Unit Tests

**What:** Comprehensive unit tests for each new component.

**Test structure:** `mcp_poc/tests/`

```
tests/
  __init__.py
  test_config.py
  test_context_manager.py
  test_windowed_context_db.py
  test_semantic_search.py       # Phase 2
  test_embedding_service.py     # Phase 2
  test_user_approval.py         # Phase 1
  test_session_state.py         # Phase 3
  test_conversation_summary.py  # Phase 3
  test_correction_store.py      # Phase 3
```

**Test the following scenarios:**

#### 4.1.1 Contamination Tests
```
Test: Contaminated content is rejected
Input: Content with "simplesieve" keyword
Expected: _is_contaminated() returns True, chunk is NOT stored

Test: Clean content is accepted
Input: Content without blacklisted keywords
Expected: _is_contaminated() returns False, chunk is stored

Test: Blacklist is configurable
Input: Updated blacklist with new terms
Expected: New terms are filtered alongside existing ones
```

#### 4.1.2 Token Budget Tests
```
Test: Context respects token budget
Input: 10000 tokens of context, max_tokens=2000
Expected: Output is truncated to ~2000 tokens

Test: Empty context returns None
Input: No relevant context found
Expected: Returns None (or fallback)

Test: Budget distributes across sections
Input: wiki docs + knowledge chunks exceeding budget
Expected: Higher-priority content kept, lower-priority dropped
```

#### 4.1.3 Semantic Search Tests (Phase 2)
```
Test: Similar concepts are retrieved
Query: "find prime numbers"
Expected: Returns chunks about sieve algorithms, number theory

Test: Unrelated queries return nothing
Query: "baking bread recipe"
Expected: Returns no results or score < 0.7

Test: Score threshold filtering works
Query: low-relevance query
Expected: Results below threshold are excluded
```

#### 4.1.4 User Approval Tests (Phase 1)
```
Test: Pending chunks are stored for review
Input: Knowledge chunk submitted for approval
Expected: Appears in pending list, NOT in active knowledge

Test: Approved chunks are usable
Input: User approves pending chunk
Expected: Chunk appears in knowledge queries

Test: Rejected chunks are blocked
Input: User rejects pending chunk
Expected: Chunk is not stored, not returned in queries
```

### 4.2 Integration Tests

**Test the full pipeline end-to-end.**

#### 4.2.1 Session Flow Test
```
1. User types a query
2. System builds context using token budget
3. Model generates response
4. Session is logged
5. Knowledge is extracted
6. Chunks are proposed for user approval
7. User approves/rejects chunks
8. Next query uses updated knowledge base
```

#### 4.2.2 Continuity Test (Phase 3)
```
Session A:
1. User: "Work on the prime sieve project"
2. System reads wiki docs, works on files
3. Session ends, task context saved

Session B (next day):
1. User: "Continue with the sieve optimization"
2. System detects same task
3. Previous context stitched in
4. User can continue naturally
```

### 4.3 Performance Benchmarks

**Metrics to measure:**

| Metric | Current Baseline | Target |
|--------|-----------------|--------|
| Context injection size (tokens) | ~5000+ (unbounded) | ≤2000 |
| Query response time | TBD | < 5s |
| Semantic search recall | 0% (no semantic search) | > 80% |
| User approval rate | 0% (no approval system) | > 90% |
| Contamination rate | ~30% (prime sieve) | < 1% |
| Session continuity | 0% (no cross-session) | > 80% |

### 4.4 User Acceptance Tests

**Real-world scenarios to validate:**

1. **Biscuit recipe test** — User asks for a recipe today
   - Expected: System provides recipe, no prime sieve contamination
   
2. **Car repair test** — User works on a completely different topic tomorrow
   - Expected: System switches context cleanly, no biscuit/recipe contamination

3. **Correction test** — User corrects a wrong answer
   - Expected: System remembers correction, doesn't repeat mistake

4. **Continuity test** — User asks a follow-up question
   - Expected: System remembers previous turn, answers coherently

5. **Knowledge growth test** — User works on prime numbers for a week
   - Expected: Knowledge base becomes rich with prime number vectors
   - New user working on cars sees no prime number contamination

### 4.5 Regression Tests

**Ensure existing functionality still works:**

1. **Wiki.lookup** — Tool still accessible and returns docs
2. **Workspace operations** — read, write, list, delete, run, compile
3. **Session logging** — Logs are still generated and structured
4. **Dual mode** — PLAN and BUILD modes still work
5. **Config loading** — YAML configuration still parses correctly

---

## Rollback / Recovery Plan

### If Phase 1 Changes Cause Issues

```bash
# Revert all Phase 1 changes
git checkout -- mcp_poc/agent.py
git checkout -- mcp_poc/context_manager.py
git checkout -- mcp_poc/windowed_context_db.py
git checkout -- mcp_poc/config.py
git checkout -- mcp_poc/config.yaml

# Restore knowledge.db from backup (if available)
# Or simply: it will be recreated empty
```

### If Semantic Search (Phase 2) Fails

Fallback to keyword-based search:
- Keep the existing `WindowedContextDB` as primary
- Add semantic search as an optional enhancement
- Toggle via `config.yaml`: `knowledge.semantic_search: false`

### If Vector DB Becomes Corrupt

```bash
# Delete and recreate vector store
rm -rf workspace/.vectorstore/
# Re-index from wiki and approved knowledge
```

### If Session State Becomes Inconsistent

```bash
# Clear session state
rm -rf workspace/.session_state/
# Sessions start fresh
```

---

## Success Criteria

### Checklist

- [ ] **Contamination-free**: No prime sieve or similar artifacts appear in unrelated conversations
- [ ] **Token-budgeted**: Context never exceeds 2000 tokens per turn
- [ ] **Semantic retrieval**: Conceptually related knowledge is found, not just keyword matches
- [ ] **User-approved**: No knowledge persists without user consent
- [ ] **Session continuity**: Follow-up questions work naturally without re-stating context
- [ ] **Cross-session continuity**: Related tasks across sessions can reference each other
- [ ] **Correctable**: User corrections prevent repeated mistakes
- [ ] **Tested**: All components have passing unit tests
- [ ] **Performant**: Response time < 5s for typical queries
- [ ] **Documented**: Configuration options and workflows are documented

### Definition of Done

Phase 1 is done when:
- [ ] All contamination vectors are blocked
- [ ] Token budgets are enforced and logged
- [ ] User approval gate is operational
- [ ] Configuration is documented

Phase 2 is done when:
- [ ] Qdrant vector store is operational
- [ ] Embedding service generates vectors
- [ ] Wiki docs are indexed and searchable
- [ ] `get_relevant_context()` uses semantic search as primary
- [ ] Fallback to keyword search works

Phase 3 is done when:
- [ ] Session state persists across invocations
- [ ] Conversation summarization works
- [ ] Context stitching retrieves past session context
- [ ] Task context is stored and retrievable
- [ ] User corrections prevent repeated mistakes

Testing is done when:
- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Performance benchmarks meet targets
- [ ] User acceptance scenarios pass
- [ ] Regression tests pass
