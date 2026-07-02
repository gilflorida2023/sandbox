# workspace.websearch

Search the web using DuckDuckGo and return relevant results. Useful for finding documentation, troubleshooting, researching libraries, or gathering information from the internet.

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | The search query |
| `max_results` | integer | no | 5 | Maximum number of results to return (1-20) |
| `timeout` | integer | no | 15 | Request timeout in seconds |

## Returns

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the search succeeded |
| `query` | string | The original search query |
| `results_count` | integer | Number of results returned |
| `results` | array | List of search results |

Each result contains:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Result title |
| `url` | string | Result URL |
| `snippet` | string | Short text excerpt |

## Example

```json
{"name": "workspace.websearch", "arguments": {"query": "python async programming patterns", "max_results": 5}}
```

## Notes

- Uses DuckDuckGo search (no API key required)
- Results include organic web results and may include ads
- Follow up interesting results with `workspace.webfetch` to read full pages
