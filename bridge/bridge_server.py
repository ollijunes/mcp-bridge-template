"""Authenticated Streamable HTTP bridge to the notes service."""

import asyncio
import hmac
import os
from time import monotonic
from typing import Annotated
from urllib.parse import urlsplit

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.responses import JSONResponse

from collect.collect_service import require_token

UPSTREAM_ERROR = "Collect request failed"


class CollectClient:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("COLLECT_URL must be an HTTP origin without credentials")
        self.url = url.rstrip("/")
        self.token = token
        self._health_lock = asyncio.Lock()
        self._health_status = None
        self._health_expires_at = 0.0

    async def request(self, method, path, **kwargs):
        try:
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    self.url + path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    **kwargs,
                )
                response.raise_for_status()
                body = response.json()
                if path == "/healthz" and body != {"status": "ok"}:
                    raise ValueError
                if path == "/notes":
                    notes = body if method == "GET" else [body]
                    if not isinstance(notes, list) or any(
                        not isinstance(note, dict)
                        or set(note) != {"id", "text", "tags", "created_at"}
                        for note in notes
                    ):
                        raise ValueError
                return body
        except (httpx.HTTPError, ValueError, RecursionError):
            raise ToolError(UPSTREAM_ERROR) from None

    async def health(self):
        async with self._health_lock:
            if self._health_status is None or monotonic() >= self._health_expires_at:
                try:
                    await self.request("GET", "/healthz")
                    self._health_status = "ok"
                except ToolError:
                    self._health_status = "degraded"
                self._health_expires_at = monotonic() + 5
            return {"status": self._health_status}


class BearerAuth:
    def __init__(self, app, token, collect):
        self.app = app
        self.token = ("Bearer " + token).encode()
        self.collect = collect

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if scope["path"] == "/healthz" and scope["method"] == "GET":
                # Keep 200 when collect is down: this healthcheck tracks the bridge process.
                response = JSONResponse(await self.collect.health())
                await response(scope, receive, send)
                return
            values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            candidate = values[0] if len(values) == 1 else b""
            if not hmac.compare_digest(candidate, self.token):
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app():
    bridge_token = require_token("BRIDGE_TOKEN")
    collect_token = require_token("COLLECT_TOKEN")
    collect = CollectClient(os.environ.get("COLLECT_URL", "http://collect:8080"), collect_token)
    server = MCPServer("notes-bridge")

    @server.tool()
    async def add_note(text: str, tags: Annotated[list[str], Field(default_factory=list)]) -> dict:
        """Store a short note with optional tags."""
        return await collect.request("POST", "/notes", json={"text": text, "tags": tags})

    @server.tool()
    async def list_notes(limit: int = 20, tag: str | None = None) -> list[dict]:
        """List the newest notes, optionally filtered by tag."""
        params = {"limit": str(limit)}
        if tag is not None:
            params["tag"] = tag
        return await collect.request("GET", "/notes", params=params)

    @server.tool()
    async def collect_health() -> dict:
        """Report whether collect is reachable and healthy."""
        return await collect.health()

    app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True
    )
    return BearerAuth(app, bridge_token, collect)


def main():
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)  # noqa: S104


if __name__ == "__main__":
    main()
