# workspace.webfetch

Fetch a URL and return its text content. Useful for retrieving documentation, API responses, web pages, or any publicly accessible URL.

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | yes | — | The URL to fetch |
| `timeout` | integer | no | 30 | Request timeout in seconds |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the fetch succeeded |
| `url` | string | Final URL after redirects |
| `status_code` | integer | HTTP status code |
| `content_type` | string | Response content-type header |
| `content` | string | Response body text (first 50000 chars) |
| `truncated` | boolean | Whether content was truncated |

## Example

```json
{"name": "workspace.webfetch", "arguments": {"url": "https://example.com/api/docs"}}
```

## Notes

- Follows redirects automatically
- Sends a standard browser User-Agent header
- Content is limited to 50000 characters to avoid token overflow
- Use for reading documentation, checking API responses, or scraping text content
