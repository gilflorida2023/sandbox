#!/usr/bin/env python3
import json
import sys

try:
    import httpx
except ImportError:
    httpx = None


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

    if httpx is None:
        print(json.dumps({"success": False, "error": "httpx not installed"}))
        sys.exit(1)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            print(json.dumps({
                "success": True,
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "content": resp.text[:50000],
                "truncated": len(resp.text) > 50000,
            }))
    except httpx.HTTPStatusError as e:
        print(json.dumps({
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            "url": url,
        }))
    except httpx.TimeoutException:
        print(json.dumps({
            "success": False,
            "error": f"Request timed out after {timeout}s",
            "url": url,
        }))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
            "url": url,
        }))


if __name__ == "__main__":
    main()
