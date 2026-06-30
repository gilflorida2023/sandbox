#!/usr/bin/env python3
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        args = {}

    path = args.get("path", ".")
    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    if not full_path.is_dir():
        if full_path.is_file():
            print(json.dumps({
                "success": False,
                "error": f"Not a directory: {path}",
                "suggestion": "Use workspace.read to read files, or use workspace.list on a parent directory."
            }))
        else:
            print(json.dumps({
                "success": False,
                "error": f"Directory not found: {path}",
                "suggestion": "List the parent directory first with workspace.list path='.' to discover correct paths."
            }))
        sys.exit(1)

    files = []
    for entry in sorted(full_path.iterdir()):
        name = entry.name
        if entry.is_dir():
            files.append({"name": name, "type": "directory", "size": 0, "modified": ""})
        else:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            files.append({"name": name, "type": "file", "size": entry.stat().st_size, "modified": mtime})

    print(json.dumps({"success": True, "path": path, "files": files}))

if __name__ == "__main__":
    main()
