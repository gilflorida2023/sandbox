#!/usr/bin/env python3
"""Find files by glob pattern."""
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

    pattern = args.get("pattern", "")
    search_path = args.get("path", ".")

    if not pattern:
        print(json.dumps({"success": False, "error": "Missing pattern parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / search_path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    matches = sorted(str(p.relative_to(WORKSPACE_ROOT)) for p in full_path.glob(pattern))

    print(json.dumps({"success": True, "pattern": pattern, "matches": matches}))

if __name__ == "__main__":
    main()
