# Ralph Wiggum — Open-Source Bash Coding Agent

> **Acknowledgments:** The pure-bash inner-loop agent architecture (`ralph-agent.sh`, `loop.sh`, `subagent.sh`) is adapted from the [**Ralph Wiggum**](https://github.com/standhartinger/ralph-wiggum) open-source coding agent by **Sam T. Hartinger**, documented at [alviano.com/2025/06/03/ralph-wiggum-an-open-source-coding-agent](https://alviano.com/2025/06/03/ralph-wiggum-an-open-source-coding-agent/). The canonical patterns — fresh-context outer loop, `<promise>DONE</promise>` completion signal, AGENTS.md constitution, IMPLEMENTATION_PLAN.md as shared state — are derived directly from that design. This implementation was built by **opencode** (the AI coding agent).
>
> Thanks Sam!

A pure-bash LLM coding agent that runs a **fresh-context outer loop** against local Ollama models. Each iteration feeds a system prompt, constitution, and workspace state to the inner agent, which makes tool calls via a CGI-based MCP server until the task is complete.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  loop.sh (outer loop)                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Each iteration:                                        │    │
│  │  1. Read AGENTS.md, PROMPT_{plan,build}.md              │    │
│  │  2. Gather workspace state (tree, plan)                  │    │
│  │  3. Build system prompt from constitution + mode         │    │
│  │  4. Pipe to ralph-agent.sh                               │    │
│  │  5. If <promise>DONE</promise> → exit                    │    │
│  └─────────────────────┬───────────────────────────────────┘    │
│                        │                                        │
│  ┌─────────────────────▼───────────────────────────────────┐    │
│  │  ralph-agent.sh (inner tool loop)                       │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │  for i in 1..MAX_INNER:                         │    │    │
│  │  │  1. Send messages + tool defs to Ollama          │    │    │
│  │  │  2. Parse JSON response for tool calls           │    │    │
│  │  │  3. Execute via mcp_tool.sh → CGI scripts        │    │    │
│  │  │  4. Append results, loop back to step 1          │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────┬───────────────────────────────────┘    │
│                        │                                        │
│  ┌─────────────────────▼───────────────────────────────────┐    │
│  │  mcp_tool.sh (tool dispatcher)                          │    │
│  │  Routes tool name → scout/cgi-bin/workspace/*.py        │    │
│  │  workspace.(read|write|list|run|search|compile|...)     │    │
│  │  workspace.subagent → subagent.sh → ralph-agent.sh      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                        │                                        │
│  ┌─────────────────────▼───────────────────────────────────┐    │
│  │  Ollama (local LLM)                                    │    │
│  │  /api/chat with tool-calling support                    │    │
│  │  Model: qwen2.5:7b (default, configurable)              │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### Outer Loop (`loop.sh`)

The outer loop maintains a **fresh context** for each iteration:
1. Loads the constitution (`AGENTS.md`) and mode-specific prompt (`PROMPT_build.md` or `PROMPT_plan.md`)
2. Gathers workspace context (directory tree, IMPLEMENTATION_PLAN.md status)
3. Assembles a system prompt and pipes it to `ralph-agent.sh`
4. If the agent outputs `<promise>DONE</promise>`, the loop exits

This prevents context window poisoning — each iteration starts clean with the latest workspace state.

### Inner Loop (`ralph-agent.sh`)

The inner agent loop, directly adapted from Ralph Wiggum's design:
1. Reads tool definitions from `tool_definitions.json` (~30 tools)
2. Sends the conversation + tool schema to Ollama
3. If the model returns **tool calls**, executes them via `mcp_tool.sh`
4. If the model returns **text** (no tool call), treats it as the final answer
5. Loops up to `MAX_INNER` (default: 50) iterations

### Protocol

- **`<promise>DONE</promise>`** — the agent signals completion. The outer loop stops.
- **AGENTS.md** — serves as a constitution: rules, tool descriptions, subagent delegation, safety constraints
- **IMPLEMENTATION_PLAN.md** — shared state. The agent reads it to find tasks, updates it on completion.
- **`success: false`** — if a tool returns an error, the agent must change strategy, not retry.

### Subagent Delegation

Multi-step work (clone+build, build+run, search+analyze) is delegated to a lightweight subagent via `workspace.subagent`, which spawns a fresh `ralph-agent.sh` with a cheaper model (`qwen3:0.6b` by default).

## Project Files

| File | Purpose |
|------|---------|
| `loop.sh` | Outer loop — fresh-context iteration, system prompt assembly, done detection |
| `ralph-agent.sh` | Inner loop — Ollama chat, tool call dispatch, result handling |
| `agent.sh` | Legacy single-shot agent (pre-dates loop.sh) |
| `llm.sh` | Minimal Ollama chat wrapper — reads prompt from stdin |
| `mcp_tool.sh` | Tool dispatcher — routes named tools to CGI scripts |
| `AGENTS.md` | Constitution — rules, workflow, safety, tool docs |
| `PROMPT_build.md` | System prompt for build mode (implement) |
| `PROMPT_plan.md` | System prompt for plan mode (research + plan only) |
| `tool_definitions.json` | Tool schemas sent to Ollama as function definitions |
| `scout/cgi-bin/workspace/subagent.sh` | Subagent wrapper — spawns ralph-agent.sh for a sub-task |

## Quick Start

### Prerequisites

- **Ollama** running locally (default: `http://localhost:11434`)
- A tool-capable model pulled (e.g., `qwen2.5:7b`)
- **Go CGI server** running on port 8080 (for tool execution)
- **jq** for JSON processing

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BUILD_MODEL` | `qwen2.5:7b` | Ollama model for build mode |
| `LLM_PLAN_MODEL` | `qwen2.5-coder:7b` | Ollama model for plan mode |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `MAX_INNER` | `50` | Max tool-call iterations per inner loop |
| `RALPH_VERBOSE` | `0` | Enable verbose logging |

### Usage

```bash
# Build mode (implement tasks)
./loop.sh build

# Plan mode (research, create/update plan)
./loop.sh plan

# Clean mode (reset Ollama context, remove workspace artifacts)
./loop.sh --clean

# Verbose mode
./loop.sh -v
```

## Constitution Highlights

From `AGENTS.md`:

- **Read specs first** — list `specs/` directory and read every `.md` file before starting
- **No retries on failure** — if a tool returns `success: false`, change approach completely
- **Subagent for multi-step work** — delegate clone+build, build+run to a subagent
- **Safety** — no writes to `.netrc`, `.ssh/`, `.git-credentials`; no `sudo`, `apt-get`, `ssh-keygen`
- **Completion** — output `<promise>DONE</promise>` only after verifying all tasks

## Tool Reference

Tools are defined in `tool_definitions.json` and dispatched by `mcp_tool.sh` to CGI scripts in `scout/cgi-bin/workspace/`:

| Tool | Description |
|------|-------------|
| `workspace.read` | Read a file |
| `workspace.write` | Write/create a file |
| `workspace.list` | List directory contents |
| `workspace.delete` | Delete a file or directory |
| `workspace.run` | Execute a binary or script |
| `workspace.compile` | Syntax-check source code |
| `workspace.search` | Grep-like file content search |
| `workspace.git_clone` | Clone a git repository |
| `workspace.subagent` | Delegate a sub-task to a worker agent |
| `workspace.find` | Find files by glob pattern |
| `workspace.run_command` | Run an arbitrary shell command |
| `workspace.websearch` | Search the web |
| `workspace.webfetch` | Fetch a URL |
| `workspace.create_test_image` | Create a test image for CI |

## Credits

- **Sam T. Hartinger** — Original Ralph Wiggum design, documentation, and canonical patterns
- **opencode** — Implementation of the bash-agent loop, subagent delegation, MCP tool integration, and tool definitions
