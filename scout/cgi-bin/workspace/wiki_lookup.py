#!/usr/bin/env python3
import json, sys
from pathlib import Path

WIKI_ROOT = Path("/home/scout/projects/sandbox/workspace/.wiki").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    topic = args.get("topic", "")
    if not topic:
        print(json.dumps({"success": False, "error": "Missing topic parameter"}))
        sys.exit(1)

    found = ""
    content = ""

    candidates = [
        WIKI_ROOT / "tools" / f"{topic}.md",
        WIKI_ROOT / "guides" / f"{topic}.md",
        WIKI_ROOT / "tools" / f"{topic}.md",
        WIKI_ROOT / "guides" / f"{topic}.md",
    ]

    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text()
            found = str(candidate.relative_to(WIKI_ROOT.parent))
            break

    if not content:
        print(json.dumps({"success": False, "error": "Topic not found"}))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "topic": topic,
        "file": found,
        "content": content
    }))

if __name__ == "__main__":
    main()
