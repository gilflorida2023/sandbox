#!/bin/bash
set -euo pipefail

INPUT=$(cat)

cat << 'TOOLS'
{
  "tools": [
    {"name": "workspace.read", "description": "Read a file from workspace", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "workspace.write", "description": "Write a file to workspace", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "workspace.list", "description": "List files in workspace directory", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}},
    {"name": "workspace.delete", "description": "Delete file or directory from workspace", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean", "default": false}}, "required": ["path"]}},
    {"name": "workspace.run", "description": "Run code: compiles C/Go/Rust automatically, executes Python/bash scripts and binaries", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}, "default": []}, "timeout": {"type": "integer", "default": 30}}, "required": ["path"]}},
    {"name": "workspace.search", "description": "Search code with grep", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}, "file_pattern": {"type": "string"}, "context_lines": {"type": "integer", "default": 2}}, "required": ["pattern"]}},
    {"name": "wiki.lookup", "description": "Look up tool or guide documentation", "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "workspace.webfetch", "description": "Fetch a URL and return its text content", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}, "timeout": {"type": "integer", "default": 30}}, "required": ["url"]}},
    {"name": "workspace.websearch", "description": "Search the web for a query and return results with titles, URLs, and snippets", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}, "timeout": {"type": "integer", "default": 15}}, "required": ["query"]}}
  ]
}
TOOLS
