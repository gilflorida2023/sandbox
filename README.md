# MCP + Ollama Coding Agent — Proof of Concept

> **Acknowledgments:** The pure-bash inner-loop agent architecture (`ralph-agent.sh`, `loop.sh`, `subagent.sh`) is adapted from the [**Ralph Wiggum**](https://github.com/standhartinger/ralph-wiggum) open-source coding agent by **Sam T. Hartinger**, documented at [alviano.com/2025/06/03/ralph-wiggum-an-open-source-coding-agent](https://alviano.com/2025/06/03/ralph-wiggum-an-open-source-coding-agent/). The canonical patterns — fresh-context outer loop, `<promise>DONE</promise>` completion signal, AGENTS.md constitution, IMPLEMENTATION_PLAN.md as shared state — are derived directly from that design. Thanks Sam!

An LLM-powered coding agent that runs on a **Linux host** (scout) and uses **Ollama on an Apple M4 Mac** for reasoning, with tool access via a **CGI-based MCP server**. The agent manages a workspace for file operations, compilation, and execution.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Mac M4 (192.168.0.7)                  Ollama :11434            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  qwen2.5-coder:7b                                        │   │
│  │  (LLM reasoning + tool calling)                          │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │ SSH tunnel                            │
│                         │ -L 11434:localhost:11434               │
└─────────────────────────┼───────────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────────┐
│  Scout (Linux host)     │                                        │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Python Agent (mcp_poc/agent.py)                         │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │   │
│  │  │ OllamaClient│  │ MCPClient    │  │ ContextManager│  │   │
│  │  │ localhost   │  │ localhost    │  │ (history +    │  │   │
│  │  │ :11434      │  │ :8080/tools  │  │  wiki)        │  │   │
│  │  └──────┬──────┘  └──────┬───────┘  └───────────────┘  │   │
│  └─────────┼────────────────┼─────────────────────────────┘   │
│            │                │                                  │
│  ┌─────────▼────────────────▼─────────────────────────────┐   │
│  │  Scout CGI MCP Server (Go :8080)                       │   │
│  │  ├─ mcp/tools/list.sh   (tool registry)                │   │
│  │  ├─ mcp/tools/call.sh   (tool dispatcher)              │   │
│   │  ├─ workspace/*.py       (8 CGI tool scripts)           │   │
│  │  └─ /health, /status, /events                          │   │
│  └────────────────────────────────────────────────────────┘   │
│            │                                                  │
│  ┌─────────▼─────────────────────────────────────────────┐   │
│  │  Workspace (/home/scout/projects/sandbox/workspace/)  │   │
│  │  ├─ .wiki/index.json     (tool/guide registry)        │   │
│  │  ├─ .wiki/tools/*.md     (7 tool documentation)       │   │
│  │  └─ .wiki/guides/*.md    (4 guides)                   │   │
│  └────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User** gives a task to the Python agent
2. **QueryRouter** classifies the input: `direct` (trivial) or `tool` (needs workspace)
3. For `direct` queries, Ollama answers immediately with the direct prompt — no tools involved
4. For `tool` queries, the agent generates a plan, then enters the execute loop:
   - **Agent** sends conversation (system prompt + plan + context + history) to Ollama via `/api/chat`
   - If the model supports tool calling (detected via `GET /api/tags` capabilities), tools are included in the payload
   - **Ollama** reasons and returns text (answer) or tool calls
5. **Agent** parses tool calls, executes them via Scout's CGI MCP tools (`POST /cgi-bin/mcp/tools/call.sh`)
6. **Tool results** are appended to the conversation and sent back to Ollama for the next turn
7. Loop continues until Ollama returns a natural language response (no tool call)
8. Session is logged, knowledge chunks are extracted and held in the approval gate for user review
9. Approved chunks are embedded via `nomic-embed-text` and indexed in Qdrant for future semantic retrieval

### Current Limitations vs. Classical MCP

This PoC implements a **minimal MCP protocol** over CGI. A full MCP implementation would include:

| Layer | Current | Classical MCP |
|-------|---------|---------------|
| **Input Validation** | None — CGI scripts parse JSON ad-hoc with `grep`/`sed` | Schema validation (JSON Schema / Pydantic) at server boundary; reject malformed requests before dispatch |
| **Context Management** | Client-side `context_manager.py` tracks history | Server manages session state, TTL, and context lifecycle; supports resume, timeout, and eviction |
| **Context Formatting & Serialization** | Hand-rolled JSON in bash CGI scripts; fragile escaping (`sed` for JSON-safe strings) | Standard MCP envelope (`jsonrpc`), typed content blocks, content negotiation, streaming |
| **Resource Allocation** | Unlimited concurrent tool calls, no quotas | Rate limiting, concurrency slots, per-session resource budgets, cancellation |
| **Access Control** | None — open HTTP on :8080, no auth | Capability-based security, OAuth/API keys, per-tool ACL, audit logging |
| **Tool Discovery** | Static JSON array in `list.sh` | Dynamic registration, tool versioning, capability negotiation |
| **Transport** | HTTP POST with raw JSON body | Multiple transports: stdio, SSE, WebSocket; request batching |

For a production system these gaps would need to be addressed, particularly **access control** and **input validation** before exposing the server beyond localhost.

## Project Structure

```
mcp_poc/                          # Python agent (PoC)
├── agent.py                      # Main loop: Ollama → tool call → execute → repeat
├── config.yaml                   # Scout, Ollama, Workspace configuration
├── config.py                     # Config loader (dataclasses from YAML)
├── mcp_client.py                 # HTTP client → Scout CGI /mcp/tools
├── ollama_client.py              # HTTP client → Ollama /api/chat
├── tool_wiki.py                  # Wiki index + tool/guide doc loader
├── context_manager.py            # Conversation history + context extraction + approval gate
├── user_approval.py              # Approval manager for knowledge chunks
├── session_log.py                # Session log extraction + persistence
├── router.py                     # Query router (direct answer vs. tool route)
├── embedding_service.py          # Ollama /api/embed wrapper with LRU cache
├── vector_store.py               # Qdrant in-process vector store (persisted to disk)
├── knowledge_indexer.py          # Chunk wiki docs, embed, index; semantic search
├── prompts/system_prompt.txt     # Agent system instructions
├── tests/                        # Unit tests
│   ├── test_config.py
│   ├── test_context_manager.py
│   ├── test_windowed_context_db.py
│   ├── test_user_approval.py
│   ├── test_embedding_service.py
│   ├── test_vector_store.py
│   └── test_knowledge_indexer.py
├── requirements.txt              # Python dependencies (mcp, httpx, pyyaml, rich)
└── venv/                         # Virtual environment

scout/                            # Scout CGI server (Go)
├── bin/scout                     # Compiled server binary (port 8080)
├── scout.go                      # Source — CGI handler, sessions, HTTP routing
├── start_scout.sh                # Init script
├── cgi-bin/
│   ├── mcp/tools/
│   │   ├── list.sh               # Tool definitions (8 workspace/wiki tools)
│   │   └── call.sh               # Routes tool name → workspace/*.sh script
│   └── workspace/
│       ├── list.py               # workspace.list — list directory
│       ├── read.py               # workspace.read — read file
│       ├── write.py              # workspace.write — write file
│       ├── delete.py             # workspace.delete — remove file/dir
│       ├── compile.py            # workspace.compile — build code (go, python, c, cpp, rust)
│       ├── run.py                # workspace.run — execute binary/script
│       ├── search.py             # workspace.search — grep code
│       └── wiki_lookup.py        # wiki.lookup — docs lookup
└── sessions/                     # Session state (JSON files)

workspace/                        # Agent workspace root
├── .wiki/
│   ├── index.json                # Tool + guide registry
│   ├── tools/                    # Tool docs (Markdown)
│   │   ├── read_file.md
│   │   ├── write_file.md
│   │   ├── list_files.md
│   │   ├── delete_file.md
│   │   ├── compile.md
│   │   ├── run.md
│   │   ├── search.md
│   │   └── wiki_lookup.md
│   └── guides/                   # Guides (Markdown)
│       ├── getting_started.md
│       ├── go_development.md
│       ├── python_development.md
│       └── searching_code.md
└── (your project files go here)

services/ollama_client/ollama/
└── chat.go                     # Go ChatClient for Ollama /api/chat (reference only)
```

## Prerequisites

- **Ollama** running on a host with a tool-capable model (e.g., `qwen2.5-coder:7b`)
- **Go 1.21+** (to build scout, or use the prebuilt binary)
- **Python 3.13+** for the agent

### Model Setup

Pull a tool-capable model on the Mac:

```bash
ollama pull qwen2.5-coder:7b
```

For semantic search (Phase 2), pull a lightweight embedding model:

```bash
ollama pull nomic-embed-text
```

## Start Commands

All commands run on the **scout (Linux host)** unless noted.

### 1. Start Scout CGI Server

```bash
cd /home/scout/projects/sandbox/scout
nohup ./bin/scout > scout.log 2>&1 &
```

Verify it's running:

```bash
curl http://localhost:8080/health
```
Expected: `{"service":"scout-cgi-mcp","status":"ok","version":"1.0.0"}`

### 2. SSH Tunnel to Mac Ollama

Ollama on the Mac listens only on `localhost:11434`. Forward it to scout:

```bash
ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f
```

If port **11434** is already in use (e.g. after a dropped session), kill the stale process and retry:

```bash
kill -9 $(lsof -ti:11434)
ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f
```

Verify:

```bash
curl http://localhost:11434/api/tags
```
Expected: A list of models including `qwen2.5-coder:7b`

### 3. Install Python Dependencies

```bash
cd /home/scout/projects/sandbox/mcp_poc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run the Agent

```bash
cd /home/scout/projects/sandbox/mcp_poc
source venv/bin/activate
python agent.py "Your coding task here"
```

## Usage Examples

### Single Task

```bash
cd /home/scout/projects/sandbox/mcp_poc
python agent.py "List files in workspace"
```

| Command | What Happens |
|---------|-------------|
| `python agent.py "List files in workspace"` | Calls `workspace.list` |
| `python agent.py "Read the getting_started guide"` | Calls `wiki.lookup` |
| `python agent.py "Create hello.py that prints Fibonacci"` | Calls `workspace.write` then `workspace.run` |
| `python agent.py "Search for 'TODO' in workspace"` | Calls `workspace.search` |
| `python agent.py "Read hello.py and explain it"` | Calls `workspace.read` |

### Interactive REPL

```bash
cd /home/scout/projects/sandbox/mcp_poc
python repl.py
```

**REPL commands:**

| Command | Description |
|---------|-------------|
| `/plan` | Switch to read-only PLAN mode |
| `/build` | Switch to read/write BUILD mode |
| `/pending` | List knowledge chunks awaiting approval |
| `/approve <id>` | Approve a pending knowledge chunk |
| `/reject <id>` | Reject a pending knowledge chunk |
| `/blacklist <pattern>` | Add contamination pattern at runtime (`re:` prefix = regex) |
| `/search <query>` | Semantic search across wiki docs and accumulated knowledge |
| `exit` / `quit` | Exit the REPL |

## Available Tools

| Tool | Description |
|------|-------------|
| `workspace.read` | Read a file from workspace |
| `workspace.write` | Write a file to workspace |
| `workspace.list` | List directory contents |
| `workspace.delete` | Delete a file or directory |
| `workspace.compile` | Compile source code (Go, Python, C, C++, Rust) |
| `workspace.run` | Execute a binary or script |
| `workspace.search` | Search code with grep |
| `wiki.lookup` | Look up tool or guide documentation |

## Context Management

The agent manages context across four layers to prevent contamination, enforce token budgets, and enable semantic retrieval.

### Token Budget

All injected context (wiki docs, knowledge chunks, accumulated knowledge) is capped at `max_context_tokens` (default: 2000). Each section is progressively truncated to fit the budget. Warning logs are emitted when truncation occurs.

### Contamination Blacklist

Keywords that indicate contaminated or noisy knowledge are filtered before storage. The blacklist supports two modes:

- **Substring matching** — entries in the `blacklist` list are matched as case-insensitive substrings
- **Regex matching** — entries in the `blacklist_regex` list are matched as compiled regex patterns

Both lists can be extended at runtime via the `/blacklist` REPL command. Use the `re:` prefix for regex patterns:

```
/blacklist re:sieve\s+of
```

### User Approval Gate

Knowledge chunks extracted from session logs are held in a pending queue instead of being stored directly into the knowledge database. The user reviews and decides:

- `/pending` — list all pending chunks
- `/approve <id>` — store the chunk in persistent knowledge
- `/reject <id>` — discard the chunk

This prevents "poison pills" (incorrect or harmful facts) from persisting without consent. The gate can be disabled by setting `require_user_approval: false` in config.yaml.

### Semantic Search (Phase 2)

Wiki docs and approved knowledge chunks are embedded using `nomic-embed-text` (768-dim vectors via Ollama's `/api/embed`) and stored in a local Qdrant vector store (in-process mode, persisted to `workspace/.context/vectors/`).

During context assembly, the agent runs a semantic search alongside the keyword-based lookup. Results from both are merged into the context window under the token budget. This captures conceptually relevant docs even when keyword terms don't match exactly.

**REPL command:**
```
/search how do I compile C code
```

**Indexing is automatic:**
- Wiki tool/guide docs are chunked by heading and indexed on agent startup (~60 chunks)
- Approved knowledge chunks are indexed as they're stored
- Semantic search runs on every `get_relevant_context()` call with a `score_threshold >= 0.4`

### Architecture

```
User Input
    │
    ▼
┌─────────────────────────────────────────┐
│       Context Budget Manager            │
│  max_context_tokens = 2000              │
│  ├─ Wiki docs (keyword match)           │
│  ├─ Knowledge chunks (keyword match)    │
│  ├─ Semantic search (embedding match)   │
│  └─ Accumulated Knowledge (window)      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│       ApprovalManager                   │
│  Pending → /approve | /reject           │
│  Contamination blacklist enforced       │
└──────────────┬──────────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────┐    ┌──────────────────┐
│ WindowedDB   │    │ KnowledgeIndexer │
│ (SQLite+FTS5)│    │ (Qdrant vectors) │
│ Deduped,     │    │ nomic-embed-text │
│ weighted,    │    │ semantic search  │
│ persistent   │    │ /search <query>  │
└──────────────┘    └──────────────────┘
```

## Query Router

The `router.py` module (`QueryRouter`) classifies each user input into one of two routes:

- **`direct`** — trivial queries (greetings, yes/no) that don't need tool access; answered immediately with the direct prompt
- **`tool`** — coding tasks that require workspace tools; triggers the full plan + execute cycle

The classifier uses keyword scoring against tool names (e.g., "read", "write", "compile") and always falls back to `"direct"` when no keywords match.

## Ollama Client — Tool Support Detection

The `ollama_client.py` module (`OllamaClient`) auto-detects whether the loaded model supports function/tool calling. On first `chat()` call, it queries `GET /api/tags` on the Ollama host and inspects the `capabilities` field of the model listing. If the model lacks `"tools"` in its capabilities, the `tools` field is omitted from the chat payload, preventing API errors.

Detection is cached (`supports_tools_cache`) for the lifetime of the client. If the capability check fails (network error, unexpected response format), tools are assumed supported as a safe default.

## Extending: Adding New Tools

To add a new tool (e.g., `git.status`):

### 1. Create the CGI script

`scout/cgi-bin/workspace/git_status.sh`:

```bash
#!/bin/bash
INPUT=$(cat)
WORKSPACE="/home/scout/projects/sandbox/workspace"
cd "$WORKSPACE"
OUTPUT=$(git status --porcelain 2>&1)
echo "{\"success\":true,\"status\":\"$(echo "$OUTPUT" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')\"}"
```

Make it executable: `chmod +x scout/cgi-bin/workspace/git_status.sh`

### 2. Write the wiki documentation

`workspace/.wiki/tools/git_status.md`:

```markdown
# Tool: git.status

## Description
Show the working tree status in the workspace git repository.

## Parameters
(none)

## Returns
- `status` (string): Git status output (porcelain format)
```

### 3. Register in `workspace/.wiki/index.json`

Add to the `tools` array:

```json
{
  "name": "git.status",
  "description": "Show working tree status",
  "parameters": {"type": "object", "properties": {}},
  "wiki_file": "tools/git_status.md"
}
```

### 4. Register in `scout/cgi-bin/mcp/tools/list.sh`

Add to the JSON array:

```json
{"name": "git.status", "description": "Show working tree status", "input_schema": {"type": "object", "properties": {}}}
```

### 5. Add routing in `scout/cgi-bin/mcp/tools/call.sh`

Add a new case:

```bash
"git.status")
    exec "$WORKSPACE_DIR/git_status.sh"
    ;;
```

### 6. Restart is not needed

The CGI scripts are loaded on each request — just ensure `list.sh` and `call.sh` are updated.

## Extending: Adding Guides

Guides are reference documents the agent can fetch with `wiki.lookup`.

To add a guide (e.g., a Git workflow guide):

### 1. Create the Markdown file

`workspace/.wiki/guides/git_workflow.md`:

```markdown
# Guide: Git Workflow

## Recommended Git Workflow for Coding Tasks

1. `git.status` — check current state
2. `git.add` — stage relevant files
3. `git.commit` — commit with descriptive message
4. `git.log` — review history
```

### 2. Register in `workspace/.wiki/index.json`

Add to the `guides` array:

```json
{"name": "git_workflow", "file": "guides/git_workflow.md"}
```

The agent discovers it via `wiki.lookup({"topic": "git_workflow"})`.

## API Reference

| Route | Method | Description |
|-------|--------|-------------|
| `GET /health` | GET | Health check |
| `GET /status` | GET | Server status, sessions, workers |
| `GET /events` | GET | Server-Sent Events stream |
| `POST /cgi-bin/mcp/tools/list.sh` | POST | Get tool definitions |
| `POST /cgi-bin/mcp/tools/call.sh` | POST | Execute a tool (`{"name":"...","arguments":{...}}`) |

Tool calls to `call.sh` require a JSON body with `name` (tool name) and `arguments` (object). Sessions are managed via `scout_session` cookie.

## Configuration

`mcp_poc/config.yaml` — all fields with defaults:

```yaml
scout:
  host: "localhost"
  port: 8080
  base_url: "http://localhost:8080/cgi-bin/mcp/tools"

ollama:
  host: "localhost"
  port: 11434
  model: "qwen2.5-coder:7b"
  timeout: 300

workspace:
  path: "/home/scout/projects/sandbox/workspace"
  wiki_path: "/home/scout/projects/sandbox/workspace/.wiki"

agent:
  max_turns: 20
  temperature: 0.1
  max_context_tokens: 2000

  knowledge:
    ingest_on_startup: false
    require_user_approval: true
    blacklist:
      - simplesieve
      - primesieve
      - prime sieve
      - sieve of eratosthenes
    blacklist_regex: []
    max_chunks_per_session: 50

  context:
    session_tokens: 500
    conversation_tokens: 500
    knowledge_tokens: 500
    task_tokens: 500

embedding:
  model: "nomic-embed-text"
  host: "localhost"
  port: 11434

vector_store:
  storage_path: "/home/scout/projects/sandbox/workspace/.context/vectors"
  embedding_dim: 768
```

### Config Fields

| Path | Default | Description |
|------|---------|-------------|
| `ollama.model` | `qwen2.5-coder:7b` | Model name for chat + embeddings |
| `agent.max_turns` | `20` | Max tool-call iterations per task |
| `agent.max_context_tokens` | `2000` | Hard cap on injected context tokens |
| `agent.knowledge.ingest_on_startup` | `false` | Auto-ingest past session logs |
| `agent.knowledge.require_user_approval` | `true` | Gate knowledge storage behind user approval |
| `agent.knowledge.blacklist` | `[...]` | Substring contamination patterns |
| `agent.knowledge.blacklist_regex` | `[]` | Regex contamination patterns |
| `agent.knowledge.max_chunks_per_session` | `50` | Max chunks per ingestion batch |
| `agent.context.*_tokens` | `500` | Per-section token budgets (reserved) |
| `embedding.model` | `nomic-embed-text` | Embedding model for semantic search |
| `embedding.host` | `localhost` | Ollama host for embeddings |
| `embedding.port` | `11434` | Ollama port for embeddings |
| `vector_store.storage_path` | `workspace/.context/vectors` | Qdrant persistence path |
| `vector_store.embedding_dim` | `768` | Vector dimension (nomic-embed-text = 768) |
