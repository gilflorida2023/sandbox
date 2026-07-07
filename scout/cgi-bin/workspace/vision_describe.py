#!/usr/bin/env python3
"""Describe an image using a vision-capable Ollama model."""
import base64, json, sys, urllib.request
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()
OLLAMA_HOST = "http://localhost:11434"

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    image_path = args.get("image_path", "")
    prompt = args.get("prompt", "Describe this image in detail exactly what you notice.")
    model = args.get("model", "qwen3-vl:2b")

    if not image_path:
        print(json.dumps({"success": False, "error": "Missing image_path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / image_path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)
    if not full_path.is_file():
        print(json.dumps({"success": False, "error": f"File not found: {image_path}"}))
        sys.exit(1)

    with open(full_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        description = data.get("message", {}).get("content", "")
        print(json.dumps({
            "success": True,
            "description": description,
            "model": model,
            "image": image_path,
            "prompt": prompt,
        }))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
