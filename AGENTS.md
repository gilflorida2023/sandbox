## Build & Run

### Validation
- Tests: `python3 -m pytest mcp_poc/tests/ -x -q 2>&1 | tail -20`
- Typecheck: `python3 -m pyright mcp_poc/ 2>&1 | tail -10`
- Lint: `python3 -m flake8 mcp_poc/ --max-line-length=120 2>&1 | tail -10`
- Scout health: `curl -s http://localhost:8080/health`
- Ollama health: `curl -s http://localhost:11434/api/tags`

### Code Conventions
- Edit existing files; never create new files unless asked.
- Use `mcp_tool.sh workspace.read` to read files, `mcp_tool.sh workspace.write` to write them.
- Use `mcp_tool.sh workspace.run` to execute code or tests.
- All paths are relative to `workspace/`.
- Single source of truth — no migrations, no adapters, no duplicated config.
- When editing, match existing code style (quotes, indentation, ternaries).
- No unnecessary comments in production code.

### Commit Rules
- `git add -A && git commit -m "message"` after each iteration.
- Use descriptive commit messages: `tool: brief summary of change`.
- No `git push` — commits stay local.

### Operational Notes
- Ollama runs locally at localhost:11434. All models are pre-pulled.
- Primary coding model: qwen2.5-coder:3b (fast, code-specialized)
- Plan/analysis model: qwen3:1.7b (general reasoning, lightweight)
- Heavy model: qwen2.5-coder:7b (for complex tasks)
- Scout CGI server runs on :8080 as the MCP tool backend.
- PROMPT_plan.md is used for planning, PROMPT_build.md for implementation.
- IMPLEMENTATION_PLAN.md is the only persistent state across iterations.
- Each loop iteration starts with a fresh context — no conversation history.
- Companion CLI tools (in ~/.local/bin): rg (ripgrep), fd, xh (HTTP client with -j), yq (YAML), jq (JSON).
