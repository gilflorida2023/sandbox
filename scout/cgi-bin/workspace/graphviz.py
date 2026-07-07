#!/usr/bin/env python3
"""Generate a diagram from DOT source using Graphviz."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    dot_source = args.get("dot_source", "")
    output = args.get("output", "")

    if not dot_source:
        print(json.dumps({"success": False, "error": "Missing dot_source parameter"}))
        sys.exit(1)
    if not output:
        print(json.dumps({"success": False, "error": "Missing output parameter"}))
        sys.exit(1)

    out_path = (WORKSPACE_ROOT / output).resolve()
    if not str(out_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Output path outside workspace"}))
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
        f.write(dot_source)
        dot_file = f.name

    try:
        result = subprocess.run(
            ["dot", "-Tpng", "-o", str(out_path), dot_file],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(json.dumps({
                "success": True,
                "output": str(out_path),
                "size": out_path.stat().st_size,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }))
        else:
            print(json.dumps({
                "success": False,
                "error": f"dot failed: {result.stderr}",
                "stdout": result.stdout,
                "stderr": result.stderr,
            }))
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print(json.dumps({"success": False, "error": "dot timed out after 30s"}))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({"success": False, "error": "dot (graphviz) not found"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)
    finally:
        os.unlink(dot_file)

if __name__ == "__main__":
    main()
