# RLM Mode — Quick Start

## What It Is

The Recursive Language Model (RLM) replaces the standard tool-calling loop. Instead of the LLM emitting structured tool calls that the agent parses and executes, the **Root LLM writes Python code** that runs in a persistent sandboxed REPL. The code can inspect context, call sub-LLMs, and execute MCP tools — all from inside the generated Python. The loop continues until the model sets `final_answer` or calls `FINAL()`.

## Prerequisites

```bash
# 1. Start the Scout CGI server
cd /home/scout/projects/sandbox/scout
nohup ./bin/scout > scout.log 2>&1 &
curl http://localhost:8080/health

# 2. Start the SSH tunnel to Mac Ollama
ssh -L 11434:localhost:11434 m4@192.168.0.7 -N -f
curl http://localhost:11434/api/tags
```

## Start the REPL

```bash
cd /home/scout/projects/sandbox/mcp_poc
venv/bin/python repl.py
```

## Enable RLM Mode

Inside the REPL, toggle RLM mode on:

```
>>> /rlm
RLM mode: ON
```

The prompt will show `RLM: ON`. When RLM mode is active, every task you submit goes through the RLM engine instead of the standard agent tool loop.

## Submit a Task

Simply type your query:

```
>>> Count the files in workspace and tell me what programming languages are used
```

The RLM will:
1. Generate Python code using `call_tool("workspace.list", ...)` and `call_tool("workspace.read", ...)`
2. Execute it in the sandbox
3. See the output
4. Iterate until it produces a final answer

## Available Inside the Python Sandbox

When the Root LLM generates code, these are available:

| Function / Variable | What It Does |
|---|---|
| `query` (str) | Your original query |
| `context` (str) | Long context / documents |
| `storage` (dict) | Persists across iterations |
| `llm_query(prompt, system)` | Calls a sub-LLM (blocks until done) |
| `call_tool(name, args)` | Executes an MCP tool (workspace operations) |
| `search_context(query, k)` | Vector search over context |
| `chunk_text(text, size, overlap)` | Split text into chunks |
| `FINAL(answer)` | Terminate and return answer |
| `print(...)` | Stdout captured and returned next turn |

## Example Session

```
$ venv/bin/python repl.py
✅ Ollama accessible via SSH tunnel at localhost:11434
Model: qwen3:0.6b

>>> /rlm
RLM mode: ON

>>> What files are in the workspace root?
=== RLM Iteration 1 ===
[RLM generates Python code using call_tool("workspace.list", ...)]
[Code runs, output captured, fed back to RLM]
=== RLM Iteration 2 ===
[RLM sees results, generates final answer]
✅ RLM finished successfully!

Result: The workspace root contains: src/, tests/, README.md, ...
```

## Turn RLM Off

```
>>> /rlm
RLM mode: OFF
```

## Configuration

Edit `config.yaml`:

```yaml
rlm:
  enabled: false          # false = standard agent, true = RLM on startup
  max_iterations: 30      # max code-gen cycles
  max_llm_calls: 50       # max sub-LLM calls across all iterations
  temperature: 0.3        # LLM temperature
  num_ctx: 32768          # context window size
```

## How It Differs From Standard Mode

| Aspect | Standard Mode | RLM Mode |
|---|---|---|
| LLM output | Tool calls (JSON) | Python code |
| Execution | Agent parses + dispatches | `exec()` in sandboxed REPL |
| Sub-tasks | Agent routes between tools | `llm_query()` in generated code |
| State | Agent maintains message list | Python variables in env dict |
| Control flow | LLM → tool → result → LLM | LLM → code → exec → output → LLM |
| Termination | Max turns or tool-stop | `final_answer` / `FINAL()` |
