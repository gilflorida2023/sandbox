## Goal
- Maintain a proof-of-concept MCP + Ollama coding agent on scout (Linux) using Ollama on Mac M4 for LLM reasoning and CGI-based MCP tools for workspace file operations, compilation, execution, and a tool wiki.

## Constraints & Preferences
- Agent runs on scout (Linux host), calls Ollama on Mac M4 via SSH tunnel on localhost:11434
- Uses CGI-based MCP server (scout) for tool execution, not Python MCP SDK directly
- Workspace at `/home/scout/projects/sandbox/workspace/` with `.wiki/` for tool documentation
- General coding tasks
- Model: `qwen2.5-coder:7b` on Mac M4, does NOT support native Ollama tool_calls — outputs JSON in markdown code blocks

## Progress
### Done
- Created all Python agent modules: `agent.py`, `config.py`, `mcp_client.py`, `ollama_client.py`, `tool_wiki.py`, `context_manager.py`, `prompts/system_prompt.txt`
- Scout server running on `localhost:8080` with 8 workspace/wiki tools registered and working
- SSH tunnel established: `scout:11434` → `m4@192.168.0.7:11434`
- Python dependencies installed in `mcp_poc/venv/`
- Agent works end-to-end: tested "Compile the simplesieve project" → list → compile (auto fails → go succeeds) → run → final answer
- Fixed `config.py` dataclass default values (using `field(default_factory=...)`)
- Fixed config attribute access paths in all modules (nested dataclass attributes)
- Added `_parse_text_tool_calls()` to extract JSON tool calls from markdown code blocks (handles single + multi-line, code blocks, plain JSON)
- Updated `compile.sh` to handle Go module directories (`go build -o dirname .`)
- Fixed `search.sh` to produce valid JSON output (no piping subshell, proper array construction)
- Fixed JSON output escaping in all CGI scripts: `compile.sh`, `run.sh`, `read.sh`, `wiki_lookup.sh` — added `\t` escaping to prevent invalid control characters in JSON output
- Updated system prompt: injects live tool definitions + JSON call format + path discovery guidance to compensate for model's lack of native tool_calls support
- Updated `agent.py` to dynamically inject tool definitions into system prompt via `{TOOL_DEFINITIONS}` placeholder
- All CGI scripts located at `/home/scout/projects/sandbox/scout/cgi-bin/workspace/` (active server path)
- Rewrote `README.md` with: architecture diagram, MCP layer education table, project structure, start commands, usage examples, extending docs

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- Text-parsed tool calls with markdown code block extraction — qwen2.5-coder:7b doesn't support Ollama's native `tool_calls` field, outputs JSON in `content` as plain or fenced JSON. Tool schemas are injected into the system prompt so the model knows what's available.
- Batch extraction: `_parse_text_tool_calls()` returns all JSON objects from a code block so multiple tool calls in one response are all executed in one turn
- Server CGI scripts live at `/home/scout/projects/sandbox/scout/cgi-bin/` — all development and execution in one place

## Next Steps
- Fix `compile.sh` auto-detect to also detect language from `go.mod`, `Cargo.toml`, `Makefile` etc. so `language: auto` works for directories
- Add `workspace.git_status`, `workspace.git_commit`, `workspace.git_log` tools if needed for version control tasks
- Consider using a model with native tool_calls support (e.g., llama3.2 or mistral) for more reliable function calling

## Critical Context
- Scout server looks for CGI scripts at `/home/scout/projects/sandbox/scout/cgi-bin/` — sandbox edits must be copied there
- SSH tunnel must be re-established if session drops: `ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f`
- Python agent parses tool calls from text even when Ollama response has no native `tool_calls` — handles single JSON, JSON array, and markdown-fenced multi-line JSON
- JSON escaping must handle tabs (`\t`) in addition to backslashes, double quotes, and newlines — Go compiler errors use tabs for indentation

## Relevant Files
- `/home/scout/projects/sandbox/mcp_poc/agent.py`: Main agent loop; `_parse_text_tool_calls()` handles text-based tool calls from markdown code blocks; injects tool definitions into system prompt
- `/home/scout/projects/sandbox/mcp_poc/config.py`: Dataclass-based config with YAML loader; uses `field(default_factory=...)` for nested configs
- `/home/scout/projects/sandbox/mcp_poc/mcp_client.py`: HTTP POST to Scout CGI, returns parsed JSON
- `/home/scout/projects/sandbox/mcp_poc/ollama_client.py`: HTTP POST to Ollama `/api/chat` with tools array
- `/home/scout/projects/sandbox/mcp_poc/tool_wiki.py`: Loads `index.json`, provides lookup/search on tool docs and guides
- `/home/scout/projects/sandbox/mcp_poc/context_manager.py`: Conversation history, extracts relevant wiki context for queries
- `/home/scout/projects/sandbox/mcp_poc/config.yaml`: Hosts, ports, workspace paths, model name, agent settings
- `/home/scout/projects/sandbox/mcp_poc/prompts/system_prompt.txt`: System prompt with `{TOOL_DEFINITIONS}` placeholder; includes JSON call format instructions and path discovery guidance
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/compile.sh`: Compile script with tab-escaping fix; handles Go directories
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/run.sh`: Run script with tab-escaping fix
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/read.sh`: Read script with tab-escaping fix
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/wiki_lookup.sh`: Wiki lookup with tab-escaping fix
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/search.sh`: Grep-based search; rewritten for valid JSON array output
- `/home/scout/projects/sandbox/workspace/`: Workspace root with `simplesieve/` and `.wiki/`
- `/home/scout/projects/sandbox/scout/cgi-bin/workspace/`: Active CGI scripts
