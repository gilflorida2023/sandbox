#!/usr/bin/env python3
import json, sys, re
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
    file_pattern = args.get("file_pattern", "")
    context_lines = args.get("context_lines", 2)

    if not pattern:
        print(json.dumps({"success": False, "error": "Missing pattern parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / search_path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    if not full_path.is_dir():
        print(json.dumps({"success": False, "error": "Search path not found"}))
        sys.exit(1)

    matches = []
    compiled = re.compile(pattern, re.IGNORECASE)

    for file_path in full_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_pattern and not file_path.match(file_pattern):
            continue

        try:
            lines = file_path.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue

        for i, line in enumerate(lines):
            if compiled.search(line):
                rel = file_path.relative_to(WORKSPACE_ROOT)
                matches.append({
                    "file": str(rel),
                    "line": i + 1,
                    "content": line
                })

    print(json.dumps({
        "success": True,
        "pattern": pattern,
        "matches": matches
    }))

if __name__ == "__main__":
    main()
