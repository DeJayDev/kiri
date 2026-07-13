from typing import Any

from kiri import config, http

_SEARCH = "https://api.exa.ai/search"
_CONTENTS = "https://api.exa.ai/contents"
_FETCH_CAP = 50000

SEARCH_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web via Exa and return ranked results with highlights. Use "
        "for grounded lookups: find real information to read and compare."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {"type": "integer", "description": "Default 5, max 100."},
        },
        "required": ["query"],
    },
}

FETCH_SCHEMA = {
    "name": "web_fetch",
    "description": "Fetch a URL via Exa and return its content as clean text.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}


async def _post(url, body) -> tuple[Any, str | None]:
    if not config.EXA_API_KEY:
        return None, "error: EXA_API_KEY not set"
    headers = {"x-api-key": config.EXA_API_KEY, "content-type": "application/json"}
    resp = await http.request("POST", url, headers=headers, json=body, timeout=60.0)
    if resp.status_code != 200:
        return None, f"error: Exa {resp.status_code}: {resp.text}"
    return resp.json(), None


async def search(args):
    body = {
        "query": args["query"],
        "type": "auto",
        "numResults": args.get("num_results", 5),
        "contents": {"highlights": True},
    }
    data, err = await _post(_SEARCH, body)
    if err:
        return err

    blocks = []
    for r in data.get("results", []):
        highlights = " ".join(r.get("highlights", []))
        blocks.append(f"{r.get('title', '')}\n{r.get('url', '')}\n{highlights}".strip())
    return "\n\n".join(blocks) or "no results"


async def fetch(args):
    body = {"urls": [args["url"]], "text": True}
    data, err = await _post(_CONTENTS, body)
    if err:
        return err

    results = data.get("results", [])
    if not results:
        return "no content"
    text = results[0].get("text", "")
    if len(text) > _FETCH_CAP:
        text = text[:_FETCH_CAP] + "\n...[truncated]..."
    return text
