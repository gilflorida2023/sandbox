#!/usr/bin/env python3
"""Fetch a URL using xh, curl, or urllib (fallback chain)."""
import json, subprocess, sys, urllib.request, urllib.error

def try_xh(url, timeout):
    try:
        r = subprocess.run(["xh", "--timeout", str(timeout), "--follow", "GET", url],
            capture_output=True, text=True, timeout=timeout + 5)
        if r.returncode == 0:
            return r.stdout[:50000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None

def try_curl(url, timeout):
    try:
        r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5)
        if r.returncode == 0 and r.stdout:
            return r.stdout[:50000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None

def try_urllib(url, timeout):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return text[:50000]
    except Exception:
        return None

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

    timeout = args.get("timeout", 30)

    for label, fn in [("xh", try_xh), ("curl", try_curl), ("urllib", try_urllib)]:
        content = fn(url, timeout)
        if content is not None:
            print(json.dumps({
                "success": True, "url": url, "fetcher": label,
                "content": content, "truncated": False,
            }))
            return

    print(json.dumps({"success": False, "error": "All fetchers failed", "url": url}))

if __name__ == "__main__":
    main()
