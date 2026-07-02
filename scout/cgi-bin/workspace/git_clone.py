#!/usr/bin/env python3
"""Clone a git repository into the workspace."""
import json, subprocess, sys
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    url = args.get("url", "")
    if not url:
        print(json.dumps({"success": False, "error": "Missing url parameter"}))
        sys.exit(1)

    # Optional subdirectory within workspace
    subdir = args.get("path", "")
    if subdir:
        clone_dest = (WORKSPACE_ROOT / subdir).resolve()
        if not str(clone_dest).startswith(str(WORKSPACE_ROOT)):
            print(json.dumps({"success": False, "error": "Path outside workspace"}))
            sys.exit(1)
        clone_dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", url, str(clone_dest)]
    else:
        # Clone into workspace root — git creates repo-name/ automatically
        cmd = ["git", "clone", url]
        clone_dest = WORKSPACE_ROOT

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
            cwd=str(WORKSPACE_ROOT) if not subdir else None,
        )
        success = result.returncode == 0
        output = {
            "success": success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
        if success:
            output["path"] = str(clone_dest)
        print(json.dumps(output))
    except subprocess.TimeoutExpired:
        print(json.dumps({"success": False, "error": "git clone timed out after 120s"}))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({"success": False, "error": "git not found on system"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
