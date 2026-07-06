#!/usr/bin/env python3
"""
Ralph agent — single-turn Ollama tool caller.
Reads conversation JSON from stdin, sends to Ollama with tools,
executes any tool_calls, outputs updated conversation JSON on stdout.

Input:  JSON array of messages (conversation)
Output: JSON array of messages (conversation + assistant reply + tool results)
"""
import json, os, re, subprocess, sys, urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("LLM_BUILD_MODEL", "qwen3:0.6b")
TOOLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_definitions.json")
MCP_TOOL_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_tool.sh")

def load_tools():
    with open(TOOLS_FILE) as f:
        d = json.load(f)
    for t in d:
        if "type" in t.get("function", {}):
            del t["function"]["type"]
    return d

def call_ollama(messages, tools):
    payload = json.dumps({
        "model": MODEL, "messages": messages, "tools": tools,
        "stream": False, "options": {"temperature": 0.3, "num_ctx": 8192}
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read()).get("message", {})
    except Exception as e:
        sys.stderr.write(f"Ollama error: {e}\n"); sys.exit(1)

def normalize(name):
    name = name.lstrip("/")
    return name.replace("_", ".")

def extract_tool_calls(msg):
    content = msg.get("content", "")
    tcs = msg.get("tool_calls", [])
    if tcs:
        return tcs, content

    # Strip markdown fences
    text = content.strip()
    for fence in ["```json\n", "```\n", "```"]:
        text = text.replace(fence, "")
    text = text.rstrip("`").strip()

    calls = []
    rest_lines = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Try JSON object per line
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                args = obj["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        pass
                if isinstance(args, dict):
                    for k, v in args.items():
                        if isinstance(v, str) and v.startswith("/"):
                            args[k] = v.lstrip("/")
                calls.append({
                    "id": f"call_{len(calls)}",
                    "function": {"name": normalize(obj["name"]), "arguments": args}
                })
                continue
        except (json.JSONDecodeError, TypeError):
            pass

        # Try ##mcp_tool format
        m = re.match(r"##mcp_tool\s+(\S+)\s+(.*)", line)
        if m:
            args_s = m.group(2).strip()
            try:
                args = json.loads(args_s)
            except json.JSONDecodeError:
                args = {"raw": args_s}
            calls.append({
                "id": f"call_t{len(calls)}",
                "function": {"name": m.group(1), "arguments": args}
            })
            continue

        rest_lines.append(line)

    if calls:
        return calls, "\n".join(rest_lines)
    return [], content

def run_tool(tc):
    fn = tc.get("function", {})
    name = fn.get("name", "")
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    sys.stderr.write(f"[tool] {name}\n")
    try:
        r = subprocess.run(["bash", MCP_TOOL_SH, name, json.dumps(args)],
            capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or json.dumps({"error": r.stderr.strip() or "no output"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"tool {name} timed out after 60s", "retryable": True})
    except Exception as e:
        return json.dumps({"error": f"tool {name} failed: {e}", "retryable": True})

def main():
    inp = sys.stdin.read().strip()
    if not inp:
        inp = os.environ.get("RALPH_PROMPT", "")
    if not inp:
        sys.stderr.write("No input\n"); sys.exit(1)
    try:
        messages = json.loads(inp)
        if not isinstance(messages, list):
            messages = [{"role": "user", "content": str(messages)}]
    except (json.JSONDecodeError, TypeError):
        messages = [{"role": "user", "content": inp}]

    tools = load_tools()
    msg = call_ollama(messages, tools)
    tcs, content = extract_tool_calls(msg)

    # Append assistant message
    messages.append(msg)

    # Execute tool calls and append results
    for tc in tcs:
        out = run_tool(tc)
        tc_id = tc.get("id", f"call_{tcs.index(tc)}")
        messages.append({"role": "tool", "content": out, "tool_call_id": tc_id})

    sys.stdout.write(json.dumps(messages))
    sys.stdout.flush()

if __name__ == "__main__":
    main()
