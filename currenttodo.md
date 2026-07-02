# Todo-Driven RLM Implementation Plan

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     RLM_ORCHESTRATOR (loop)                       │
│                                                                   │
│  ┌──────────┐   ┌───────────┐   ┌─────────┐   ┌───────────────┐ │
│  │  PICK    │──▶│  BUILD    │──▶│  LLM    │──▶│  PARSE         │ │
│  │ next todo│   │  context  │   │  CHAT   │   │  observations  │ │
│  └──────────┘   └───────────┘   └─────────┘   └───────┬───────┘ │
│                                                        │         │
│  ┌──────────┐   ┌───────────┐   ┌──────────────────┐   │         │
│  │  LOG     │◀──│  PERSIST  │◀──│  UPDATE TODO     │◀──┘         │
│  │  stats   │   │  discover │   │  + split subtodos │             │
│  └──────────┘   └───────────┘   └──────────────────┘             │
│                                                                   │
│  STATS_COLLECTOR (rolling window, per-session accumulators)       │
│  TODO_LIST (persistent, status-tracked, hierarchical)             │
└──────────────────────────────────────────────────────────────────┘
```

---

## New Files

### 1. `mcp_poc/todo_list.py` (~90 lines)

Persistent todo list with Redis-like data model. SQLite-backed.

```
TodoItem:
  - id: str (SHA-256 hash)
  - description: str
  - status: str (pending | in_progress | completed | blocked)
  - parent_id: str | None
  - session_id: str
  - discoveries: List[str]  # doc_ids from vector store
  - created_at: float
  - completed_at: float | None
  - iteration_count: int    # RLM turns spent on this

TodoList:
  - create_todo(description, parent_id=None) → TodoItem
  - pick_next() → TodoItem | None  # first pending or in_progress
  - update_status(id, status)
  - add_discovery(id, doc_id)
  - get_sub_todos(parent_id) → List[TodoItem]
  - get_session_todos(session_id) → List[TodoItem]
  - completion_rate() → float
  - todo_text() → str  # formatted for context injection
```

**Key detail**: `pick_next()` returns the oldest `in_progress` item first (for continuity) or the oldest `pending` item. This ensures the model picks up where it left off.

### 2. `mcp_poc/stats_collector.py` (~120 lines)

Captures per-turn metrics and maintains rolling diagnostics.

```
StatsCollector:
  - record_turn(stats: TurnStats)
  - get_summary() → StatsSummary
  - get_rolling_average(window=10) → TurnStats

TurnStats:
  - turn_number: int
  - todo_id: str
  - prompt_tokens: int
  - completion_tokens: int
  - total_tokens: int
  - context_budget: int
  - context_used: int
  - truncated: bool
  - sem_search_scores: List[float]
  - self_references: int      # heuristic count
  - clarification_requests: int
  - duration_ns: int
  - embedding_calls: int

StatsSummary:
  - total_turns: int
  - total_prompt_tokens: int
  - total_completion_tokens: int
  - avg_prompt_per_turn: float
  - avg_completion_per_turn: float
  - avg_sem_score: float
  - truncation_rate: float
  - self_ref_rate: float
  - clarification_rate: float
  - todo_completion_rate: float
  - avg_duration_ms: float
```

### 3. `mcp_poc/rlm_orchestrator.py` (~160 lines)

The RLM loop that wires TodoList + StatsCollector + context building + LLM + persistence.

```
RlmOrchestrator:
  - __init__(agent, todo_list, stats_collector)
  - async run_turn(user_input) → (response, turn_stats)
  - _pick_todo() → TodoItem
  - _build_context(todo, user_input) → List[dict] # messages
  - _parse_observations(llm_response) → Observations
  - _persist(observations, todo)

Observations:
  - decisions: List[str]
  - blockers: List[str]
  - discoveries: List[str]  # notable findings to persist
  - sub_todos: List[str]    # new items to add to the todo list
  - files_touched: List[str]
  - is_complete: bool       # whether the current todo is done
  
## Observation Parsing Strategy

The LLM response is scanned for structured **observation blocks**. The model is instructed (via the system prompt) to emit observations in a simple key-value format:

```
## Observations
- decision: Use FastAPI over Flask for better async support
- discovery: JWT middleware needs a SECRET_KEY env var
- blocker: Need to install pyjwt library
- subtodo: Write unit tests for auth routes
- complete: yes
```

The parser extracts these with regex. If no structured block is found, it falls back to simple heuristics:
- Lines containing "decided", "chose", "using" → decisions
- Lines containing "blocked", "blocker", "needs", "requires" → blockers
- Lines containing "found", "discovered", "note" → discoveries
- Lines containing "next", "TODO", "also need" → sub_todos
- Lines containing "done", "complete", "finished" → completion check
```

---

## Modified Files

### 4. `mcp_poc/ollama_client.py`

**Change**: Return token stats from chat response alongside content.

```python
# Return signature change:
async def chat(self, messages, tools=None, format=None) -> tuple[str, dict]:
    resp = await self._make_request_with_retry(...)
    content = resp.get("message", {}).get("content", "")
    stats = {
        "prompt_tokens": resp.get("prompt_eval_count", 0),
        "completion_tokens": resp.get("eval_count", 0),
        "total_duration_ns": resp.get("total_duration", 0),
    }
    return content, stats
```

**Migration strategy**: Each caller currently does:
```python
response = await self.ollama.chat(...)
content = response.get("message", {}).get("content", "")
```
After change:
```python
content, stats = await self.ollama.chat(...)
```

**Alternative** (lower risk): Add `chat_with_stats()` alongside existing `chat()`.

### 5. `mcp_poc/embedding_service.py`

**Change**: Add a call counter for embedding usage stats.

```python
class EmbeddingService:
    def __init__(self, ...):
        self.call_count = 0
        self.total_chars = 0
    
    def embed(self, text):
        self.call_count += 1
        self.total_chars += len(text)
    
    def embed_batch(self, texts):
        self.call_count += len(texts)
        self.total_chars += sum(len(t) for t in texts)
```

### 6. `mcp_poc/session_state.py`

**Change**: Add cumulative token counters and stats snapshot.

```python
# In _load() defaults:
"_state": {
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_turns": 0,
    "stats_snapshots": [],
}

def record_tokens(self, prompt: int, completion: int):
    self._state["total_prompt_tokens"] += prompt
    self._state["total_completion_tokens"] += completion
    self.save()

def snapshot_stats(self, summary: dict):
    self._state["stats_snapshots"].append({
        "turn": self._state["total_turns"],
        **summary,
        "timestamp": time.time(),
    })
    self.save()
```

### 7. `mcp_poc/agent.py`

**Changes**:

a) **`__init__`** — Initialize new components:
```python
self.todo_list = TodoList(storage_path=f"{config.workspace.path}/.todos")
self.stats_collector = StatsCollector()
self.rlm = RlmOrchestrator(self, self.todo_list, self.stats_collector)
```

b) **`run()` method** — Use RLM loop for task decomposition and execution.

c) **`chat()` method** — Wire `/rlm` and `/todo` commands.

d) **Update all `ollama.chat()` calls** to unpack new `(content, stats)` return signature.

e) **Add per-turn stats logging** in the execution loop.

### 8. `mcp_poc/repl.py`

**Changes**: Add commands:

```python
# /rlm status       — show todo list + completion rate
# /rlm stats        — show telemetry dashboard
# /rlm start <task> — create todos from task, start RLM
# /rlm reset        — clear todos, start fresh
# /stats            — short stats summary
# /todo list        — show all todos
# /todo add <desc>  — manually add a todo
# /todo done <id>   — mark a todo completed
# /todo block <id>  — mark a todo blocked
```

### 9. `mcp_poc/config.py`

**Change**: Add RLMConfig dataclass.

```python
@dataclass
class RlmConfig:
    enabled: bool = True
    max_turns_per_todo: int = 5
    require_completion_check: bool = True
    auto_decompose: bool = True
    persist_discoveries: bool = True

# Add to Config:
rlm: RlmConfig = field(default_factory=RlmConfig)
```

### 10. `mcp_poc/config.yaml`

**Change**: Add RLM section.

```yaml
rlm:
  enabled: true
  max_turns_per_todo: 5
  require_completion_check: true
  auto_decompose: true
  persist_discoveries: true
```

---

## Continuity Telemetry Dashboard

The `/stats` REPL command outputs:

```
╔══════════════════════════════════════════════╗
║            RLM TELEMETRY DASHBOARD           ║
╠══════════════════════════════════════════════╣
║ Session: sess_abc123                         ║
║ Model:   qwen3.5:9b                          ║
╟──────────────────────────────────────────────╢
║ TURNS         Total: 12   Avg/turn: 1,540t   ║
║ PROMPT        Total: 14,832t  Avg: 1,236t    ║
║ COMPLETION    Total: 3,647t   Avg: 304t      ║
║ EMBEDDING     Calls: 47                       ║
╟──────────────────────────────────────────────╢
║ TODO COMPLETION   5/6 (83%)                   ║
║ TRUNCATION RATE   0/12 (0%)                   ║
║ SELF-REFERENCE    75% of turns ✓              ║
║ CLARIFICATIONS    0  ✓                        ║
║ AVG SEM SCORE     0.73 ✓                      ║
╟──────────────────────────────────────────────╢
║ ACTIVE TODO:    "Write unit tests for auth"   ║
║ IN PROGRESS:    1                             ║
║ PENDING:        0                             ║
║ COMPLETED:      5                             ║
║ BLOCKED:        0                             ║
╚══════════════════════════════════════════════╝
```

---

## Health Signals Summary

| Signal | Where computed | What to look for |
|---|---|---|
| **Context utilization** | `prompt_tokens / num_ctx * 100` | < 5% = underfeeding | > 60% = overflow risk |
| **Truncation rate** | `truncated_turns / total_turns` | > 10% = budget too small |
| **Self-reference rate** | output contains terms from prior turns | < 40% = context not carrying |
| **Clarification rate** | `clarification_requests / total_turns` | > 0 = model confused |
| **Semantic search score** | `avg(sem_search_scores)` | < 0.5 = knowledge not matching |
| **Todo completion rate** | `completed / total * 100` | < 60% = tasks too large or model struggling |
| **Iterations per todo** | `sum(iteration_count) / completed` | > 3 = decomposition too coarse |

---

## Implementation Order

| Step | File | Effort | Depends on |
|---|---|---|---|
| 1 | `todo_list.py` | Low | — |
| 2 | `stats_collector.py` | Low | — |
| 3 | `config.py` + `config.yaml` | Low | 1, 2 |
| 4 | `embedding_service.py` | Trivial | — |
| 5 | `ollama_client.py` | Medium | — (changes every caller) |
| 6 | `session_state.py` | Low | 2 |
| 7 | `rlm_orchestrator.py` | Medium | 1, 2, 5, 6 |
| 8 | `agent.py` update | High | 3, 5, 6, 7 |
| 9 | `repl.py` update | Medium | 8 |
| 10 | Run tests | Low | all |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Breaking `ollama.chat()` return signature breaks everything | Add `chat_with_stats()` alongside `chat()` — keep backward compat |
| RLM loop gets stuck on a single todo | `max_turns_per_todo` hard cap + auto-abandon if exceeded |
| Observation parsing fails + no structured output | Fallback to LLM re-parse: "Did you complete X? Reply with YES or NO" |
| Stats bloat session state files | Cap snapshots at last 50 entries, aggregate older ones |
| Todo list grows unboundedly | Archive completed todos older than 7 days |
