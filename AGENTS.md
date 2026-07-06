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
- All paths are relative to workspace root. Do NOT prefix with "workspace/".
- Single source of truth — no migrations, no adapters, no duplicated config.
- When editing, match existing code style (quotes, indentation, ternaries).
- No unnecessary comments in production code.

### Commit Rules
- `git add -A && git commit -m "message"` after each iteration.
- Use descriptive commit messages: `tool: brief summary of change`.
- No `git push` — commits stay local.

### Operational Notes
- Ollama runs locally at localhost:11434. All models are pre-pulled.
- Root model (loop): qwen2.5:7b (simplesieve 21s, native tools 7s — reliable multi-step planning)
- Worker subagent model: qwen3:0.6b (simplesieve 1.43s, native tools 4.46s — fastest, narrow focus prevents hallucination)
- Build fallback root: qwen3:1.7b (simplesieve 5s, native tools 7s — more capable root if 2.5:7b struggles)
- Heavy/analysis: qwen3:8b (simplesieve 20s, native tools 16s — deeper reasoning)
- NOTE: qwen2.5-coder:3b and opencoder models REFUSE tasks — do not use them as defaults
- NOTE: qwen3.5 family has a write-call bug (only emits 1 tool call per turn) — do not use in agent loops
- Environment variable override: LLM_BUILD_MODEL="qwen3:1.7b" for more capable builds
- Scout CGI server runs on :8080 as the MCP tool backend.
- PROMPT_plan.md is used for planning, PROMPT_build.md for implementation.
- IMPLEMENTATION_PLAN.md is the only persistent state across iterations.
- Each loop iteration starts with a fresh context — no conversation history.
- Companion CLI tools (in ~/.local/bin): rg (ripgrep), fd, xh (HTTP client with -j), yq (YAML), jq (JSON).

### Codebase Patterns
