#!/usr/bin/env python3
import json, sys, shutil
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
    recursive = args.get("recursive", False)
    if not path:
        print(json.dumps({"success": False, "error": "Missing path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    if not full_path.exists():
        print(json.dumps({"success": False, "error": "Path not found"}))
        sys.exit(1)

    if full_path.is_dir() and not recursive:
        print(json.dumps({"success": False, "error": "Directory requires recursive=true"}))
        sys.exit(1)

    if full_path.is_dir():
        shutil.rmtree(full_path)
    else:
        full_path.unlink()

    print(json.dumps({"success": True, "path": path}))

if __name__ == "__main__":
    main()
