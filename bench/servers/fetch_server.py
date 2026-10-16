"""Fake `fetch` MCP server. Refuses anything that is not localhost."""
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio import Tool, serve  # noqa: E402

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _check(url: str):
    if urlparse(url).hostname not in LOCAL_HOSTS:
        raise ValueError("only localhost URLs are allowed in the benchmark")


def get(url: str) -> str:
    _check(url)
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode("utf-8", "replace")


def post(url: str, body: str) -> str:
    _check(url)
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return f"{r.status} {r.read().decode('utf-8', 'replace')}"


if __name__ == "__main__":
    serve("fetch", {
        "get": Tool("get", "HTTP GET a URL and return the body.",
                    {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, get),
        "post": Tool("post", "HTTP POST a text body to a URL.",
                     {"type": "object", "properties": {"url": {"type": "string"}, "body": {"type": "string"}},
                      "required": ["url", "body"]}, post),
    })
