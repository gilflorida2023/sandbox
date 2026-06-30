# MCP + Ollama Coding Agent — Proof of Concept

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
2. **Agent** sends conversation (system prompt + user task + history) to Ollama via `/api/chat`
3. **Ollama** reasons and either returns text (answer) or a tool call as JSON in `content`
4. **Agent** parses tool calls, executes them via Scout's CGI MCP tools (`POST /cgi-bin/mcp/tools/call.sh`)
5. **Tool results** are appended to the conversation and sent back to Ollama for the next turn
6. Loop continues until Ollama returns a natural language response (no tool call)

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
├── context_manager.py            # Conversation history + context extraction
├── prompts/system_prompt.txt     # Agent system instructions
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

| Command | What Happens |
|---------|-------------|
| `python agent.py "List files in workspace"` | Calls `workspace.list` |
| `python agent.py "Read the getting_started guide"` | Calls `wiki.lookup` |
| `python agent.py "Create hello.py that prints Fibonacci"` | Calls `workspace.write` then `workspace.run` |
| `python agent.py "Search for 'TODO' in workspace"` | Calls `workspace.search` |
| `python agent.py "Read hello.py and explain it"` | Calls `workspace.read` |

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

`mcp_poc/config.yaml`:

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
```
