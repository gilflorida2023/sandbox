# Coding Agent with Pipeline Integration

## Overview

The Coding Agent is an advanced AI-powered development assistant that combines sophisticated safety controls, semantic search capabilities, and session continuity features to help developers write, analyze, and maintain code more effectively.

Built with a three-phase architecture, the agent provides:
- **Phase 1**: Safety-first development with user approval gates and contamination protection
- **Phase 2**: Semantic search and knowledge management across documentation and code
- **Phase 3**: Task continuity and context stitching across sessions
- **Phase 4**: Recursive exploration with ChromaDB-backed problem decomposition
- **Web Tools**: Fetch URLs and search the web via MCP tool integration (webfetch, websearch)

## Installation & Setup

### Prerequisites
- Python 3.13+
- Ollama with models (qwen2.5-coder:7b, glm4:9b)
- SSH tunneling setup (if accessing remote Ollama instances)

### SSH Tunnel Setup (systemd)

If connecting to a remote Ollama, the SSH tunnel runs as a systemd *user* service for reliability (auto-restart on failure, detached from the Python process):

```bash
# Copy the service unit
cp deploy/ollama-tunnel.service ~/.config/systemd/user/

# Enable linger so the service survives logout
loginctl enable-linger $USER

# Start the tunnel
systemctl --user daemon-reload
systemctl --user enable --now ollama-tunnel

# Check status
systemctl --user status ollama-tunnel
```

The unit file at `deploy/ollama-tunnel.service` uses `Restart=always`, `ServerAliveInterval=15`, and `ExitOnForwardFailure=yes` for fast dead-tunnel detection and automatic recovery.

### Installation
```bash
# Clone the repository
cd /path/to/projects/sandbox/mcp_poc

# Install Python dependencies
pip install -r requirements.txt

# Start the agent
python agent.py "Your task description"

# Or use the interactive REPL
python repl.py
```

### Configuration

Edit `config.yaml` in the mcp_poc/ directory to customize:

```yaml
# Core settings
agent:
  max_turns: 20
  temperature: 0.1
  max_context_tokens: 2000

# Ollama connection
ollama:
  host: "localhost"
  port: 11434
  model: "qwen2.5-coder:7b"

# Phase 3: Continuity & Context
phase3:
  session:
    storage_path: "/home/scout/projects/sandbox/workspace/.session_state"
    max_summary_tokens: 300
    keep_recent_turns: 4
    score_threshold: 0.55

  correction:
    storage_path: "/home/scout/projects/sandbox/workspace/.corrections"

  task:
    storage_path: "/home/scout/projects/sandbox/workspace/.tasks"
```

## Core Features

### Phase 1: Safety & Control

#### Dual-Mode System
- **PLAN Mode**: Read-only analysis, no file modifications
- **BUILD Mode**: Full development capabilities with approval gates

#### User Approval Gates
All knowledge storage requires explicit user approval:
- `/pending` - Review chunks awaiting approval
- `/approve <id>` - Approve a knowledge chunk
- `/reject <id>` - Reject a knowledge chunk

#### Contamination Protection
- Configurable blacklist patterns (simplesieve, primesieve, etc.)
- Runtime blacklist extension via `/blacklist <pattern>`
- Regex blacklist support (`/blacklist re:sieve\\s+of`)

### Phase 2: Semantic Search & Knowledge Management

#### Vector Store Integration
- Qdrant-based vector database for semantic search
- Nomic-embed-text for embeddings
- Wiki documentation automatic indexing

#### Semantic Search Commands
- `/search <query>` - Search across wiki documentation and accumulated knowledge

#### Context Management
- Sliding window knowledge base (max 500 chunks)
- Token-based context windows (500 tokens per category)
- Wiki tool documentation integration

### Phase 3: Task Continuity & Context Stitching

#### Session State Management (`SessionStateManager`)
Persists conversation state across sessions, including:
- Active tasks and progress tracking
- Conversation summaries
- Referenced files
- Context fragments for continuity

#### Conversation Summarizer (`ConversationSummarizer`)
- Summarizes older conversation turns while preserving key information
- Keeps last N turns (configurable, default 4) intact
- Integrates summaries into context windows within 2000-token budget

#### Context Stitcher (`ContextStitcher`)
- Uses semantic search to find relevant past context
- Retrieves context from previous sessions based on query similarity
- Applies score thresholds (default 0.55) for quality control

#### Task Store (`TaskStore`)
Persistent task management with:
- CRUD operations for tasks
- File involvement tracking
- Decision and blocker management
- Code creation tracking
- Semantic task search

#### Correction Store (`CorrectionStore`)
Stores user corrections to prevent repeated mistakes:
- Topic-based correction storage
- Applied count tracking
- Semantic search for corrections
- Context preservation for future reference

### Phase 4: Recursive Exploration System

#### Recursive Solver (`RecursiveSolver`)
Autonomous recursive problem solving with ChromaDB-backed memory:

- **Problem Decomposition**: Breaks complex problems into independently solvable sub-problems
- **Recursive Loop**: decompose → retrieve → solve → store → reflect → check → repeat
- **ChromaDB Memory**: Per-exploration vector store for persistent context across iterations
- **Compaction**: Automatic summarization every N iterations (configurable, default 3)
- **Convergence Detection**: Self-evaluation to determine when the problem is solved
- **Ollama Embeddings**: Uses `nomic-embed-text` via existing Ollama pipeline

#### Exploration Naming
- Format: `explore_<YYYYMMDD_HHMMSS>` (auto-generated from timestamp)
- Stored at: `workspace/.explorations/<exploration_id>/`

## REPL Commands

### Core Commands
```bash
/plan                    # Switch to PLAN mode (read-only)
/build                   # Switch to BUILD mode (requires approval)
/pending                  # List knowledge chunks awaiting approval
/approve <id>            # Approve a pending knowledge chunk
/reject <id>             # Reject a pending knowledge chunk
/blacklist <pattern>     # Add contamination pattern
dree: Prefix with 're:' for regex (e.g. 're:sieve\\s+of')
/search <query>          # Semantic search across wiki + knowledge
```

### Web Tools (MCP)

Two new web-browsing tools are available as MCP CGI scripts, auto-discovered by the agent with no Python-side changes:

| Tool | CGI Script | Description |
|------|-----------|-------------|
| `workspace.webfetch` | `scout/cgi-bin/workspace/webfetch.py` | Fetch a URL and return text content (uses httpx, max 50K chars) |
| `workspace.websearch` | `scout/cgi-bin/workspace/websearch.py` | Search the web via DuckDuckGo (no API key needed) |
| `workspace.git_clone` | `scout/cgi-bin/workspace/git_clone.py` | Clone a git repository into the workspace |

Use them to look up documentation, clone repositories, research best practices, fetch API references, search for error solutions, or read online guides.

### Phase 3 Commands
```bash
/resume <session>        # Resume a previous session
/summarize <n>           # Generate conversation summary (last n turns)
/task <action>           # Manage tasks (add/show/update)
/correct <id> <feedback> # Submit user correction
```

### Phase 4 Commands
```bash
/explore <problem>       # Start recursive exploration of a complex problem
```

## Usage Examples

### Example 1: Starting a New Task
```bash
$ python agent.py "Create a REST API for user authentication"

# Agent will:
# 1. Plan the task in Phase 1
# 2. Execute tool calls in Phase 2
# 3. Store insights in knowledge base
# 4. Maintain session state for continuity
```

### Example 2: Resuming a Previous Session
```bash
$ python agent.py "Continue the authentication implementation" --session-id auth-session-2024

# Agent will:
# 1. Load previous session state
# 2. Inject conversation summary
# 3. Provide context from earlier work
# 4. Continue from where it left off
```

### Example 3: Interactive REPL Session
```bash
$ python repl.py

# In interactive mode:
>>> /plan
Mode switched to PLAN mode successfully
Current mode: PLAN (Read-only: Yes)

>>> Implement user authentication
[Agent generates plan and executes tools...]

>>> /build
Mode switched to BUILD mode successfully
Current mode: BUILD (Read-only: No)

>>> /pending
=== Pending Knowledge Chunks (0) ===
No pending knowledge chunks awaiting review.

>>> /search authentication
=== Semantic Search Results (3) ===
  [wiki] score=0.892
  Create JWT authentication system for API endpoints...
  [knowledge] score=0.756
  User authentication flow: login -> validate -> issue token...
  [knowledge] score=0.721
  Password hashing implementation using bcrypt...
```

### Example 4: Task Management
```bash
>>> /task add "Implement password reset feature"
Task added: task_abc123

>>> /task show 1
=== Task: Implement password reset feature ===
Status: in_progress
Files: []
Decisions: []
Blockers: []
Code created: []

>>> /task update 1 status "completed"
Task updated: task_abc123
```

### Example 5: Recursive Exploration with `/explore`
```bash
$ python repl.py

>>> /explore Design a rate-limiting middleware for the REST API

=== Starting Recursive Exploration ===
Problem: Design a rate-limiting middleware for the REST API

[Agent iterates through decomposition, solution, reflection cycles...
Stores intermediate findings in ChromaDB for context retention]

=== Exploration Result ===
## Rate Limiting Middleware Design

### 1. Token Bucket Algorithm
Implement a token bucket with configurable refill rate and capacity...

### 2. Redis-backed Counter
Use Redis INCR with TTL for distributed rate tracking...

### 3. Middleware Integration
Wrap FastAPI routes with dependency injection...

### 4. Headers & Responses
Return X-RateLimit-Limit, X-RateLimit-Remaining, etc.
```

### Example 6: Web Search and URL Fetching

The agent can now use `workspace.websearch` and `workspace.webfetch` to browse the web:

```bash
$ python repl.py

>>> Find the latest FastAPI documentation on middleware

[Agent uses workspace.websearch to search, then workspace.webfetch to
read the official FastAPI middleware docs page]

Result: FastAPI middleware docs say you can add middleware via
app.add_middleware() or with the @app.middleware() decorator...
```

### Example 7: Submitting Corrections
```bash
>>> /correct error_handling
User correction: Replace 'if x == 5:' with 'if x == 5:  # Note: magic numbers should be avoided'

# The correction will be stored and injected when similar error_handling topics arise
```

## Configuration

### Core Configuration (`config.py`)

```python
@dataclass
class ScoutConfig:
    host: str = "localhost"
    port: int = 8080
    base_url: str = "http://localhost:8080/cgi-bin/mcp/tools"

@dataclass
class OllamaConfig:
    host: str = "192.168.0.7"  # Change as needed
    port: int = 11434
    model: str = "qwen2.5-coder:7b"
    timeout: int = 300

@dataclass
class AgentConfig:
    max_turns: int = 20
    temperature: float = 0.1
    max_context_tokens: int = 2000
    knowledge:
        ingest_on_startup: bool = False
        require_user_approval: bool = True
        blacklist: list = ["simplesieve", "primesieve", ...]
        max_chunks_per_session: int = 50
    context:
        session_tokens: int = 500
        conversation_tokens: int = 500
        knowledge_tokens: int = 500
        task_tokens: int = 500
```

### Phase 4 Configuration

```yaml
solver:
  chroma_path: "/home/scout/projects/sandbox/workspace/.explorations"
  max_iterations: 20          # Maximum recursive iterations
  max_context_tokens: 1024    # Token budget per solver turn
  retrieval_top_k: 3          # ChromaDB results per query
  compaction_interval: 3      # Summarize every N iterations
```

### Phase 3 Configuration

```python
@dataclass
class SessionConfig:
    storage_path: str = ""
    max_summary_tokens: int = 300
    keep_recent_turns: int = 4
    score_threshold: float = 0.55

@dataclass
class CorrectionConfig:
    storage_path: str = ""
    max_corrections: int = 50

@dataclass
class TaskConfig:
    storage_path: str = ""
    max_tasks: int = 100

@dataclass
class Phase3Config:
    session: SessionConfig = field(default_factory=SessionConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    task: TaskConfig = field(default_factory=TaskConfig)
```

## Architecture

### Component Interactions

```
┌─────────────────────────────────────────────────────────┐
│                    OLLAMA                              │
└─────────────────────▲─────────────────────────────────┘
                      │
┌─────────────────────▼─────────────────────────────────┐
│                    CODING AGENT                        │
├─────────────────────▲─────────────────────────────────┤
│                     │                                 │
│   ┌─────────────────┼─────────────────┐               │
│   │                 │                 │               │
│   │   PHASE 2:     │   PHASE 3:      │               │
│   │ SEMANTIC SEARCH│ CONTEXT STITCHING│               │
│   │                │                 │               │
│   │  ┌────────────▼────────────┐     │               │
│   │  │  VECTOR STORE          │     │               │
│   │  │                        │     │               │
│   │  │  EmbeddingService      │     │               │
│   │  │                        │     │               │
│   │  └────────────▲────────────┘     │               │
│   │              │                 │               │
│   └───────────────┼─────────────────┘               │
│                  │                                 │
│   ┌─────────────▼─────────────┐                    │
│   │  PHASE 1: SAFETY & CONTROL │                    │
│   │                           │                    │
│   │ ┌─────────────────────────┼─────────────────┐ │
│   │ │     KNOWLEDGE INDEXER    │   WINDOW DB      │ │
│   │ │                        │                 │ │
│   │ │  ┌────────────────────▼─────┐   ┌─────────▼─────┐ │
│   │ │  │ ToolWiki              │   │ WindowedContextDB│ │
│   │ │  │                      │   │                 │ │
│   │ │  │ Wiki docs + LLM tools │   │   Windowed    │ │
│   │ │  │                      │   │ Knowledge    │ │
│   │ │  └────────────────────▲─────┘   │   Base       │ │
│   │ │                       │         │                 │ │
│   │ └───────────────────────┼─────────┘   BLACKLIST    │ │
│   │                          │       ├───────────────┤ │
│   │   ┌─────────────────────▼─────┐   │   CONTAMINATION│ │
│   │   │   ApprovalManager       │   │   PROTECTION   │ │
│   │   │                        │   │               │ │
│   └───┤   User approval gate   ├───┤   Combined    │ │
│       │   (pending/approve)    │   │   Blacklist   │ │
│       └───────────────────────┘   └───────────────┘ │
│                                                     │
│   ┌─────────────────────────────────────────────────┘
│   │                   CONTEXT MANAGER                  │
│   └─────────────────────────────────────────────────┘
│
│   ┌─────────────────────▲─────────────────────────────────┐
│   │                     │                                 │
│   ┌─────────────────────┼─────────────────┐               │
│   │   PHASE 3: CONTINUITY & MEMORY                   │
│   │                                           │
│   │ ┌─────────────────────────────┐             │
│   │ │ SessionStateManager         │             │
│   │ │  (session_state.py)        │             │
│   │ └─────────────────────────────┘             │
│   │                                            │
│   │ ┌─────────────────────────────┐             │
│   │ │ ConversationSummarizer   │             │
│   │ │   (conversation_summarizer.py) │         │
│   │ └─────────────────────────────┘             │
│   │                                            │
│   │ ┌─────────────────────────────┐             │
│   │ │  ContextStitcher          │             │
│   │ │   (context_stitcher.py)    │             │
│   │ └─────────────────────────────┘             │
│   │                                            │
│   │ ┌─────────────────────────────┐             │
│   │ │       TaskStore            │             │
│   │ │    (task_store.py)          │             │
│   │ └─────────────────────────────┘             │
│   │                                            │
│   │ ┌─────────────────────────────┐             │
│   │ │       CorrectionStore      │             │
│   │ │    (correction_store.py)     │             │
│   │ └─────────────────────────────┘             │
│   └─────────────────────────────────────────────┘
│
│   ┌─────────────────────▲─────────────────────────────────┐
│   │                     │                                 │
│   ┌─────────────────────┼─────────────────┐               │
│   │   PHASE 4: RECURSIVE EXPLORATION                    │
│   │                                           │
│   │ ┌─────────────────────────────┐             │
│   │ │      RecursiveSolver       │             │
│   │ │       (solver.py)          │             │
│   │ │                            │             │
│   │ │ ┌────────────────────────┐ │             │
│   │ │ │   ChromaDB (per        │ │             │
│   │ │ │   exploration)         │ │             │
│   │ │ └────────────────────────┘ │             │
│   │ └─────────────────────────────┘             │
│   └─────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User Input → Agent → Ollama → Tools/Responses**
2. **Tool Results → Context Manager → Knowledge Base**
3. **Knowledge Indexer → Vector Store (semantic search)**
4. **Session State → Memory Persistence**
5. **Corrections → Correction Store**
6. **Problem → RecursiveSolver → ChromaDB (decompose/solve/reflect/store loop)**
7. **User Query → Ollama Model → MCP Tools → Web (webfetch/websearch)**

## Testing

### Running Tests
```bash
# All tests
./venv/bin/python -m pytest tests/ -v

# Specific test categories
./venv/bin/python -m pytest tests/test_config.py -v
./venv/bin/python -m pytest tests/test_context_manager.py -v
./venv/bin/python -m pytest tests/test_session_state.py -v
./venv/bin/python -m pytest tests/test_conversation_summarizer.py -v
./venv/bin/python -m pytest tests/test_context_stitcher.py -v
./venv/bin/python -m pytest tests/test_task_store.py -v
./venv/bin/python -m pytest tests/test_correction_store.py -v
```

### Current Test Status
- **Total Tests**: 123
- **Phase 3 Tests**: 52
- **Original Tests**: 71
- **Pass Rate**: 123/123 (100%)

### Test Coverage
- **SessionStateManager**: 18 tests
- **ConversationSummarizer**: 10 tests  
- **ContextStitcher**: 8 tests
- **TaskStore**: 12 tests
- **CorrectionStore**: 14 tests

## System Specifications

### Dependencies
```
Python version: 3.13+
\nCore packages:
- httpx>=0.25.0
- pyyaml>=6.0
- rich>=13.0.0
- take-minutes>=0.4.0
- chromadb>=1.5.0
- chromadb>=0.4.0
- curl (system package for scout CGI scripts)

Optional:
- Ollama (local or remote instance)
- SSH tunneling for remote Ollama
```

### Performance Characteristics

#### Token Budget Management
- **Maximum context per turn**: 2000 tokens
- **Knowledge window**: 500 tokens
- **Session context**: 500 tokens
- **Conversation context**: 500 tokens
- **Task context**: 500 tokens

#### Storage Limits
- **Knowledge database**: 500 chunks max
- **Session fragments**: 1000 max per session
- **Correction storage**: 50 max per topic
- **Task storage**: 100 max concurrent tasks
- **Exploration storage**: Per-exploration ChromaDB under `.explorations/`

### Limitations

#### Known Limitations
1. **Wiki documentation updates**: Requires manual re-indexing
2. **Model capabilities**: Limited by Ollama model tool support
3. **SSH tunneling**: Requires proper key setup for remote Ollama
4. **Session storage**: File-based persistence has limitations for very large sessions

#### Safety Considerations
1. **User responsibility**: Ensure input does not contain malicious content
2. **Approval workflow**: All knowledge storage requires user approval
3. **Contamination protection**: Blacklist patterns can be extended
4. **Mode restrictions**: BUILD mode requires explicit confirmation

## Advanced Usage

### Custom Configuration
```python
# Custom configuration in agent.py
config.phase3.session.storage_path = "/custom/path/.session_state"
config.phase3.correction.storage_path = "/custom/path/.corrections"
config.phase3.task.storage_path = "/custom/path/.tasks"
```

### Integrating with External Systems
1. **Pipeline workflows**: Use `--workflow <name>` argument
2. **Session logging**: Automatically logs to workspace/.session-log/agent.log
3. **Knowledge ingestion**: `/resume` commands trigger knowledge re-ingestion

## Troubleshooting

### Common Issues

#### Ollama Connection Failed
```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Start Ollama if not running
ollama serve
```

#### SSH Tunnel Issues
```bash
# Check tunnel status
systemctl --user status ollama-tunnel

# View logs
journalctl --user -u ollama-tunnel -n 50

# Restart if needed
systemctl --user restart ollama-tunnel

# Manual diagnostics (legacy script)
./scout/cgi-bin/workspace/tunnel_check.py check
```

#### Token Budget Exhaustion
```bash
# Reduce context window in config.yaml
agent:
  max_context_tokens: 1000  # Halved for testing
```

### Getting Help
- **Issues**: Report at https://github.com/anomalyco/opencode/issues
- **Discussions**: GitHub Discussions tab
- **Community**: Slack/Discord channels (if available)

## License

This project is licensed under the MIT License.

## Contributing

### Contributing Guidelines
1. **Phase 1/2 changes**: Follow existing code patterns
2. **Phase 3 additions**: Ensure backward compatibility
3. **Testing**: Add comprehensive unit tests
4. **Documentation**: Update relevant README sections

### Code Quality Standards
- Python 3.13+ type hints
- Async/await for all I/O operations
- Comprehensive unit tests
- Black formatting compliance
- ESLint/flake8 linting

---

*Generated with Phase 3: Task Continuity & Context Stitching implementation*