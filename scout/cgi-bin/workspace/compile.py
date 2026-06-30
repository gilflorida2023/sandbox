#!/usr/bin/env python3
import json, sys, subprocess, os
from pathlib import Path

WORKSPACE_ROOT = Path("/home/scout/projects/sandbox/workspace").resolve()

def detect_language(path: str, is_dir: bool) -> str:
    if is_dir:
        dir_path = WORKSPACE_ROOT / path
        if (dir_path / "go.mod").exists():
            return "go"
        if (dir_path / "Cargo.toml").exists():
            return "rust"
        if (dir_path / "Makefile").exists() or (dir_path / "CMakeLists.txt").exists():
            return "c"
        if (dir_path / "pyproject.toml").exists() or (dir_path / "setup.py").exists() or (dir_path / "requirements.txt").exists():
            return "python"
        if (dir_path / "package.json").exists():
            return "node"
        return "unknown"
    ext = Path(path).suffix.lower()
    return {
        ".go": "go", ".py": "python", ".c": "c",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
        ".rs": "rust",
    }.get(ext, "unknown")

def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    path = args.get("path", "")
    language = args.get("language", "auto")
    if not path:
        print(json.dumps({"success": False, "error": "Missing path parameter"}))
        sys.exit(1)

    full_path = (WORKSPACE_ROOT / path).resolve()
    if not str(full_path).startswith(str(WORKSPACE_ROOT)):
        print(json.dumps({"success": False, "error": "Path outside workspace"}))
        sys.exit(1)

    is_dir = full_path.is_dir()
    if not is_dir and not full_path.is_file():
        print(json.dumps({
            "success": False,
            "error": f"Source file not found: {path}",
            "suggestion": "Use workspace.list to find actual filenames, then use EXACT name from list output."
        }))
        sys.exit(1)

    if language == "auto":
        language = detect_language(path, is_dir)

    binary = ""
    output = ""
    success = False

    try:
        if language == "go":
            if is_dir:
                result = subprocess.run(["go", "build", "-o", full_path.name, "."],
                                        cwd=str(full_path), capture_output=True, text=True, timeout=120)
                output = result.stdout + result.stderr
                if result.returncode == 0:
                    success = True
                    binary = f"{path}/{full_path.name}"
            else:
                binary = str(full_path.with_suffix(""))
                result = subprocess.run(["go", "build", "-o", binary, str(full_path)],
                                        cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=120)
                output = result.stdout + result.stderr
                if result.returncode == 0:
                    success = True

        elif language == "python":
            result = subprocess.run(["python3", "-m", "py_compile", str(full_path)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                success = True
                output = "Syntax OK"
            else:
                output = result.stdout + result.stderr

        elif language == "c":
            binary = str(full_path.with_suffix(""))
            result = subprocess.run(["gcc", "-o", binary, str(full_path)],
                                    cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr
            if result.returncode == 0:
                success = True

        elif language == "cpp":
            binary = str(full_path.with_suffix(""))
            result = subprocess.run(["g++", "-o", binary, str(full_path)],
                                    cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr
            if result.returncode == 0:
                success = True

        elif language == "rust":
            if (full_path / "Cargo.toml").exists():
                result = subprocess.run(["cargo", "build"], cwd=str(full_path),
                                        capture_output=True, text=True, timeout=300)
                output = result.stdout + result.stderr
                if result.returncode == 0:
                    success = True
                    binary = f"{path}/target/debug/{full_path.name}"
            else:
                output = "Cargo.toml not found"
        else:
            output = f"Unknown language: {language}"
            suggestion = "Specify language explicitly (go, python, c, cpp, rust) or use a recognized file extension"
    except subprocess.TimeoutExpired:
        output = "Compilation timed out"
    except FileNotFoundError as e:
        output = f"Compiler not found: {e}"

    result = {
        "success": success,
        "language": language,
        "binary": binary,
        "output": output,
    }
    if not success and "suggestion" in dir():
        result["suggestion"] = suggestion
    print(json.dumps(result))

if __name__ == "__main__":
    main()
