#!/usr/bin/env python3
import json, sys
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
    if not path:
        print(json.dumps({"success": False, "error": "Missing path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    if not full_path.is_file():
        print(json.dumps({
            "success": False,
            "error": f"File not found: {path}",
            "suggestion": "Use workspace.list to find the correct file path, then use the EXACT name from list output."
        }))
        sys.exit(1)

    content = full_path.read_text()
    size = full_path.stat().st_size
    print(json.dumps({"success": True, "path": path, "content": content, "size": size}))

if __name__ == "__main__":
    main()
