#!/usr/bin/env python3
"""Create a simple test image using Pillow."""
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

    output = args.get("output", "test_diagram.png")
    width = args.get("width", 200)
    height = args.get("height", 200)
    shape = args.get("shape", "rectangle")

    out_path = (WORKSPACE_ROOT / output).resolve()
    if not str(out_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Output path outside workspace"}))
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print(json.dumps({"success": False, "error": "Pillow not available"}))
        sys.exit(1)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    margin = max(10, min(width, height) // 10)
    if shape == "rectangle":
        draw.rectangle(
            [margin, margin, width - margin, height - margin],
            outline="black", width=3
        )
        draw.text((width // 3, height // 3), "Test", fill="black")
    elif shape == "circle":
        draw.ellipse(
            [margin, margin, width - margin, height - margin],
            outline="black", width=3
        )
    elif shape == "lines":
        draw.line([(margin, margin), (width - margin, height - margin)], fill="blue", width=3)
        draw.line([(width - margin, margin), (margin, height - margin)], fill="red", width=3)
    else:
        print(json.dumps({"success": False, "error": f"Unknown shape: {shape}"}))
        sys.exit(1)

    try:
        img.save(out_path)
        print(json.dumps({
            "success": True,
            "output": str(out_path.relative_to(WORKSPACE_ROOT)),
            "size": out_path.stat().st_size,
            "width": width,
            "height": height
        }))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
