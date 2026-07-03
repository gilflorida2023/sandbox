#!/usr/bin/env python3
import json, sys
from pathlib import Path

WIKI_ROOT = Path("/home/scout/projects/sandbox/workspace/.wiki").resolve()


def _load_index():
    index_file = WIKI_ROOT / "index.json"
    if index_file.exists():
        return json.loads(index_file.read_text())
    return {"tools": [], "guides": []}


def _build_lookup(index):
    """Build name -> wiki_file mappings from the index."""
    by_tool_name = {}
    by_file_stem = {}
    for tool in index.get("tools", []):
        name = tool.get("name", "")
        wiki_file = tool.get("wiki_file", "")
        if wiki_file:
            by_tool_name[name.lower()] = wiki_file
            stem = Path(wiki_file).stem.lower()
            by_file_stem[stem] = wiki_file
    for guide in index.get("guides", []):
        name = guide.get("name", "")
        wiki_file = guide.get("file", "")
        if wiki_file:
            by_tool_name[name.lower()] = wiki_file
            stem = Path(wiki_file).stem.lower()
            by_file_stem[stem] = wiki_file
    return by_tool_name, by_file_stem


def _normalize(topic):
    """Normalize a topic string for fuzzy matching."""
    t = topic.lower().strip()
    # Strip common prefixes the LLM might add
    for prefix in ("workspace.", "wiki.", "guide."):
        if t.startswith(prefix):
            t = t[len(prefix):]
    # Normalize separators: underscores and hyphens are interchangeable
    t = t.replace("_", " ").replace("-", " ")
    return t


def _find_wiki_file(topic, by_tool_name, by_file_stem):
    """Try to find a wiki file for the given topic using multiple strategies."""
    topic_lower = topic.lower().strip()

    # Strategy 1: Exact tool name match (e.g., "workspace.compile")
    if topic_lower in by_tool_name:
        return by_tool_name[topic_lower]

    # Strategy 2: Strip prefix and match (e.g., "workspace.compile" -> "compile")
    normalized = _normalize(topic)
    for name, path in by_tool_name.items():
        if name == normalized:
            return path

    # Strategy 3: Match against file stems (e.g., "compile" -> "tools/compile.md")
    if normalized in by_file_stem:
        return by_file_stem[normalized]

    # Strategy 4: Partial/substring match on file stems
    for stem, path in by_file_stem.items():
        if normalized in stem or stem in normalized:
            return path

    # Strategy 5: Underscore/hyphen variant (e.g., "git_clone" -> "git_cloning")
    variants = [
        normalized.replace(" ", "_"),
        normalized.replace(" ", "-"),
        normalized + "ing",
        normalized + "s",
    ]
    for variant in variants:
        if variant in by_file_stem:
            return by_file_stem[variant]
        for stem, path in by_file_stem.items():
            if variant == stem:
                return path

    return None


def _available_topics(by_tool_name):
    """Return a sorted list of all available topic names."""
    topics = sorted(by_tool_name.keys())
    return topics


def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        return

    topic = args.get("topic", "")
    if not topic:
        print(json.dumps({"success": False, "error": "Missing topic parameter"}))
        return

    index = _load_index()
    by_tool_name, by_file_stem = _build_lookup(index)

    wiki_rel = _find_wiki_file(topic, by_tool_name, by_file_stem)

    if not wiki_rel:
        available = _available_topics(by_tool_name)
        print(json.dumps({
            "success": False,
            "error": f"Topic not found: {topic}",
            "available_topics": available,
            "hint": f"Try one of: {', '.join(available[:10])}"
        }))
        return

    wiki_file = WIKI_ROOT / wiki_rel
    if not wiki_file.exists():
        available = _available_topics(by_tool_name)
        print(json.dumps({
            "success": False,
            "error": f"Wiki file missing: {wiki_rel}",
            "available_topics": available,
        }))
        return

    content = wiki_file.read_text()
    print(json.dumps({
        "success": True,
        "topic": topic,
        "file": wiki_rel,
        "content": content,
    }))


if __name__ == "__main__":
    main()
