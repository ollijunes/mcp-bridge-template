#!/bin/sh
set -eu
# Execute inside the bridge so credentials stay in its existing environment.
docker compose exec -T bridge /app/.venv/bin/python - <<'PY'
import asyncio
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    url = "http://127.0.0.1:8000"
    async with httpx2.AsyncClient(trust_env=False, timeout=10) as client:
        health = await client.get(url + "/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert (await client.post(url + "/mcp")).status_code == 401
        client.headers["Authorization"] = "Bearer " + os.environ["BRIDGE_TOKEN"]
        async with streamable_http_client(url + "/mcp", http_client=client) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"add_note", "list_notes", "collect_health"}
                added = await session.call_tool("add_note", {"text": "smoke-note", "tags": ["smoke"]})
                assert not added.is_error
                listed = await session.call_tool("list_notes", {"limit": 1, "tag": "smoke"})
                assert not listed.is_error
                assert "smoke-note" in listed.content[0].text
    print("Compose smoke test passed")


asyncio.run(main())
PY
