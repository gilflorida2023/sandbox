#!/usr/bin/env python3
import html
import json
import re
import sys
from urllib.parse import quote_plus

try:
    import httpx
except ImportError:
    httpx = None


DDG_URL = "https://html.duckduckgo.com/html"


def parse_ddg_results(html_text: str, max_results: int) -> list[dict]:
    results = []
    for match in re.finditer(
        r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>',
        html_text,
        re.DOTALL,
    ):
        if len(results) >= max_results:
            break
        url = html.unescape(match.group(1))
        title = html.unescape(re.sub(r"<[^>]+>", "", match.group(2)).strip())

        snippet_match = re.search(
            r'<a class="result__snippet".*?>(.*?)</a>',
            html_text[match.end():],
            re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip())

        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON input"}))
        sys.exit(1)

    query = args.get("query", "")
    if not query:
        print(json.dumps({"success": False, "error": "Missing query parameter"}))
        sys.exit(1)

    max_results = args.get("max_results", 5)
    timeout = args.get("timeout", 15)

    if httpx is None:
        print(json.dumps({"success": False, "error": "httpx not installed"}))
        sys.exit(1)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(
                DDG_URL,
                data={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            resp.raise_for_status()
            results = parse_ddg_results(resp.text, max_results)
            print(json.dumps({
                "success": True,
                "query": query,
                "results_count": len(results),
                "results": results,
            }))
    except httpx.TimeoutException:
        print(json.dumps({
            "success": False,
            "error": f"Search timed out after {timeout}s",
            "query": query,
        }))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
            "query": query,
        }))


if __name__ == "__main__":
    main()
