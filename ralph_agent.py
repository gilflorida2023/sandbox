#!/usr/bin/env python3
"""
Ralph agent — stateless Ollama tool caller with built-in inner loop.
Reads prompt from stdin (plain text or JSON messages), sends to Ollama with tools,
loops internally executing tool calls until the model produces text, then outputs it.

Input:  plain text prompt OR JSON array of messages
Output: JSON array of messages (default) or final text (--text flag)
"""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("LLM_BUILD_MODEL", "qwen3:0.6b")
TOOLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_definitions.json")
MCP_TOOL_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_tool.sh")
MAX_INNER = 20
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv or os.environ.get("RALPH_VERBOSE") == "1"

def vlog(*args):
    if VERBOSE:
        t = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[v] {t}", *args, file=sys.stderr, flush=True)

def load_tools():
    with open(TOOLS_FILE) as f:
        d = json.load(f)
    for t in d:
        fn = t.get("function", {})
        if "type" in fn:
            del fn["type"]
    return d

def call_ollama(messages, tools):
    payload = json.dumps({
        "model": MODEL, "messages": messages, "tools": tools,
        "stream": False, "options": {"temperature": 0.3, "num_ctx": 8192}
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        start = time.time()
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read()).get("message", {})
        vlog(f"Ollama ({time.time()-start:.1f}s)")
        return result
    except Exception as e:
        msg = f"Ollama error: {e}"
        sys.stderr.write(msg + "\n")
        sys.exit(1)

def normalize(name):
    name = name.lstrip("/")
    return name.replace("_", ".")

def failure_key(tc, result):
    """Generate a key for repeated-failure detection."""
    name = tc.get("function", {}).get("name", "?")
    try:
        r = json.loads(result)
        error = r.get("error", "")[:80]
    except (json.JSONDecodeError, TypeError, AttributeError):
        error = str(result)[:80]
    return f"{name}:{error}"

def extract_tool_calls(msg):
    content = msg.get("content", "")
    tcs = msg.get("tool_calls", [])
    if tcs:
        return tcs, content

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

def run_tool(tc, it):
    fn = tc.get("function", {})
    name = fn.get("name", "")
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    vlog(f"iter {it} tool: {name} {json.dumps(args)[:300]}")
    start = time.time()
    try:
        r = subprocess.run(["bash", MCP_TOOL_SH, name, json.dumps(args)],
            capture_output=True, text=True, timeout=60)
        elapsed = time.time() - start
        result = r.stdout.strip() or json.dumps({"error": r.stderr.strip() or "no output"})
        vlog(f"iter {it} result ({elapsed:.1f}s): {result[:200]}")
        return result
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        vlog(f"iter {it} TIMEOUT ({elapsed:.1f}s)")
        return json.dumps({"error": f"tool {name} timed out after 60s", "retryable": True})
    except Exception as e:
        vlog(f"iter {it} FAILED: {e}")
        return json.dumps({"error": f"tool {name} failed: {e}", "retryable": True})

def main():
    TEXT_ONLY = "--text" in sys.argv or os.environ.get("RALPH_TEXT_ONLY") == "1"

    inp = sys.stdin.read().strip()
    if not inp:
        inp = os.environ.get("RALPH_PROMPT", "")
    if not inp:
        sys.stderr.write("No input\n")
        sys.exit(1)

    try:
        messages = json.loads(inp)
        if not isinstance(messages, list):
            messages = [{"role": "user", "content": str(messages)}]
    except (json.JSONDecodeError, TypeError):
        messages = [{"role": "user", "content": inp}]

    tools = load_tools()
    vlog(f"Model: {MODEL}, tools: {len(tools)}, text_only: {TEXT_ONLY}")

    failure_counts = {}

    for inner in range(MAX_INNER):
        it = inner + 1
        vlog(f"iter {it} → Ollama ({len(messages)} messages)")
        msg = call_ollama(messages, tools)
        tcs, content = extract_tool_calls(msg)

        if tcs:
            for tc in tcs:
                n = tc.get("function", {}).get("name", "?")
                a = tc.get("function", {}).get("arguments", {})
                vlog(f"iter {it} ← tool: {n} {json.dumps(a)[:200]}")
        else:
            vlog(f"iter {it} ← text ({len(content)} chars)")

        messages.append(msg)

        if not tcs:
            if TEXT_ONLY:
                sys.stdout.write(content)
            else:
                sys.stdout.write(json.dumps(messages))
            sys.stdout.flush()
            return

        for tc in tcs:
            out = run_tool(tc, it)
            tc_id = tc.get("id", f"call_{tcs.index(tc)}")
            messages.append({"role": "tool", "content": out, "tool_call_id": tc_id})

            # Repeated-failure detection: same tool+error 3× → abort
            fk = failure_key(tc, out)
            failure_counts[fk] = failure_counts.get(fk, 0) + 1
            if failure_counts[fk] >= 3:
                vlog(f"Repeated failure ({failure_counts[fk]}×): {fk}")
                messages.append({
                    "role": "tool",
                    "content": json.dumps({"error": f"Repeated failure: {tc.get('function', {}).get('name', '?')} failed {failure_counts[fk]} times with same error. Report this as a blocker — do NOT retry."}),
                    "tool_call_id": f"blocker_{inner}"
                })
                break
        else:
            continue
        break

    sys.stderr.write("Max inner iterations reached\n")
    sys.stderr.write("Last messages:\n")
    for m in messages[-5:]:
        role = m.get("role", "?")
        if m.get("tool_calls"):
            sys.stderr.write(f"  [{role}] tool_calls: {json.dumps(m['tool_calls'])[:200]}\n")
        elif m.get("content", ""):
            sys.stderr.write(f"  [{role}] {m['content'][:300]}\n")
        else:
            sys.stderr.write(f"  [{role}] (no content)\n")
    sys.exit(1)

if __name__ == "__main__":
    main()
