#!/usr/bin/env python3
"""Describe an image using an Ollama vision model.

Lets a non-vision model (e.g. qwen2.5:7b) interact with images: the image is
sent to a vision-capable Ollama model and the resulting text description is
returned, so a text-only model can reason about image content.

Reads JSON from stdin:
  { "image_path": "<path relative to workspace root, or absolute>",
    "prompt": "<optional>",
    "model": "<optional, default qwen3-vl:2b>" }
Prints JSON to stdout:
  { "success": true, "description": "...", "model": "..." }
  { "success": false, "error": "..." }
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("VISION_MODEL", "qwen3-vl:2b")


def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    image_path = args.get("image_path", "")
    prompt = args.get("prompt") or "Describe this image in detail."
    model = args.get("model") or DEFAULT_MODEL

    if not image_path:
        print(json.dumps({"success": False, "error": "Missing image_path parameter"}))
        sys.exit(1)

    p = Path(image_path)
    if not p.is_absolute():
        p = (WORKSPACE_ROOT / p).resolve()
    if not p.is_file():
        print(json.dumps({"success": False, "error": f"Image not found: {image_path}"}))
        sys.exit(1)

    try:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:
        print(json.dumps({"success": False, "error": f"Could not read image: {e}"}))
        sys.exit(1)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        content = out.get("message", {}).get("content", "")
        if not content:
            print(json.dumps({"success": False, "error": "Vision model returned empty response", "raw": out}))
            sys.exit(1)
        print(json.dumps({"success": True, "description": content, "model": model}))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        print(json.dumps({"success": False, "error": f"Ollama HTTP error {e.code}: {body}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"success": False, "error": f"Vision model call failed: {e}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
