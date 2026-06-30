#!/usr/bin/env python3
import json, sys, os
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        print(json.dumps({"success": False, "error": "Missing path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    bytes_written = len(content.encode("utf-8"))
    print(json.dumps({"success": True, "path": path, "bytes_written": bytes_written}))

if __name__ == "__main__":
    main()
