import asyncio
import hmac
from unittest.mock import AsyncMock, patch

import httpx
import httpx2
import pytest
from conftest import BRIDGE_TOKEN, COLLECT_TOKEN, run_asgi
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from bridge import bridge_server
from bridge.bridge_server import CollectClient, create_app


@pytest.mark.parametrize(
    "hosts,origins,host,origin,status",
    [
        (None, None, "bridge.example.com", None, 421),
        ("", "", "bridge.example.com", None, 421),
        (" , ", " , ", "bridge.example.com", None, 421),
        (None, None, "127.0.0.1:8000", "http://localhost:8000", 200),
        ("bridge.example.com", None, "bridge.example.com", None, 200),
        ("bridge.example.com", None, "other.example.com", None, 421),
        ("bridge.example.com", None, "bridge.example.com", "https://bridge.example.com", 403),
        ("bridge.example.com", None, "bridge.example.com", "http://localhost:8000", 200),
        (
            " bridge.example.com, vpn.example.com:8443, ",
            " https://bridge.example.com, https://vpn.example.com:8443, ",
            "vpn.example.com:8443",
            "https://vpn.example.com:8443",
            200,
        ),
        (
            "bridge.example.com",
            "https://bridge.example.com",
            "bridge.example.com",
            "https://other.example.com",
            403,
        ),
        (None, "https://bridge.example.com", "localhost:8000", "https://bridge.example.com", 200),
        (None, "https://bridge.example.com", "bridge.example.com", None, 421),
    ],
)
def test_transport_security(monkeypatch, hosts, origins, host, origin, status):
    if hosts is not None:
        monkeypatch.setenv("BRIDGE_ALLOWED_HOSTS", hosts)
    if origins is not None:
        monkeypatch.setenv("BRIDGE_ALLOWED_ORIGINS", origins)
    headers = {
        "Authorization": "Bearer " + BRIDGE_TOKEN,
        "Host": host,
        "Accept": "application/json, text/event-stream",
    }
    if origin is not None:
        headers["Origin"] = origin
    with TestClient(create_app()) as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "transport-security-test", "version": "1.0"},
                },
            },
        )
        assert response.status_code == status
        if status == 200:
            assert response.json()["result"]["serverInfo"]["name"] == "notes-bridge"


@pytest.mark.parametrize("name", ["BRIDGE_TOKEN", "COLLECT_TOKEN"])
@pytest.mark.parametrize("value", [None, "", "short"])
def test_startup_token(monkeypatch, name, value, capsys):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name) as error:
        create_app()
    assert "short" not in str(error.value)
    assert COLLECT_TOKEN not in str(capsys.readouterr())


@pytest.mark.parametrize("path", ["/mcp", "/mcp/", "/unknown"])
@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Bearer ü"])
def test_auth(path, authorization):
    with TestClient(create_app()) as client:
        response = client.post(path, headers={"Authorization": authorization.encode()})
        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}


def test_auth_duplicate_and_constant_time():
    with TestClient(create_app()) as client:
        headers = {"Authorization": "Bearer " + BRIDGE_TOKEN}
        with patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as compare:
            assert client.get("/unknown", headers=headers).status_code == 404
            compare.assert_called_once()
        assert client.get("/mcp", headers=list(headers.items()) * 2).status_code == 401


def test_health_ok(collect_server):
    with TestClient(create_app()) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_health_degraded():
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "degraded"}


@pytest.mark.parametrize("initial_status", ["ok", "degraded"])
def test_health_cache_expiry(initial_status):
    next_status = "degraded" if initial_status == "ok" else "ok"
    outcomes = [
        ToolError("unavailable") if status == "degraded" else {"status": status}
        for status in (initial_status, next_status)
    ]
    with (
        patch.object(CollectClient, "request", side_effect=outcomes) as request,
        patch("bridge.bridge_server.monotonic", return_value=100.0) as now,
        TestClient(create_app()) as client,
    ):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": initial_status}
        now.return_value = 104.999
        assert client.get("/healthz").json() == {"status": initial_status}
        assert request.await_count == 1
        now.return_value = 105.0
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": next_status}
        assert request.await_count == 2


@pytest.mark.parametrize("status", ["ok", "degraded"])
def test_concurrent_health_requests_share_probe(status):
    async def check():
        started = asyncio.Event()
        release = asyncio.Event()

        async def probe(*args):
            started.set()
            await release.wait()
            if status == "degraded":
                raise ToolError("unavailable")
            return {"status": "ok"}

        app = create_app()
        app.collect.request = AsyncMock(side_effect=probe)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://bridge"
        ) as client:
            pending = [asyncio.create_task(client.get("/healthz")) for _ in range(20)]
            await asyncio.wait_for(started.wait(), timeout=1)
            release.set()
            responses = await asyncio.gather(*pending)
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == {"status": status} for response in responses)
        app.collect.request.assert_awaited_once_with("GET", "/healthz")

    asyncio.run(check())


@pytest.mark.parametrize(
    "url",
    [
        "file:///data/notes",
        "http://example.com/a",
        "http://example.com?secret=1",
        "http://example.com#secret",
        "http://user:secret@example.com",
        "http://",
    ],
)
def test_invalid_collect_url(url):
    with pytest.raises(ValueError, match="COLLECT_URL") as error:
        CollectClient(url, COLLECT_TOKEN)
    assert "secret" not in str(error.value)


def test_upstream_failure(caplog, capsys, unreachable_url):
    async def check():
        client = CollectClient(unreachable_url, COLLECT_TOKEN)
        with pytest.raises(ToolError, match="^Collect request failed$"):
            await client.request("GET", "/notes")
        assert await client.health() == {"status": "degraded"}

    asyncio.run(check())
    assert COLLECT_TOKEN not in caplog.text + str(capsys.readouterr())


@pytest.mark.parametrize(
    "status,body",
    [
        (302, b"secret-upstream"),
        (500, b"secret-upstream"),
        (200, b"not-json"),
        (200, b"{}"),
        (200, b"[1]"),
    ],
)
def test_fixed_upstream_errors(status, body):
    async def check():
        response = httpx.Response(
            status, content=body, request=httpx.Request("GET", "http://collect:8080/notes")
        )
        with patch.object(httpx.AsyncClient, "request", return_value=response):
            with pytest.raises(ToolError, match="^Collect request failed$"):
                await CollectClient("http://collect:8080", COLLECT_TOKEN).request("GET", "/notes")

    asyncio.run(check())


def test_upstream_health_invalid():
    async def check():
        response = httpx.Response(
            200,
            json={"status": "other"},
            request=httpx.Request("GET", "http://collect:8080/healthz"),
        )
        with patch.object(httpx.AsyncClient, "request", return_value=response):
            assert await CollectClient("http://collect:8080", COLLECT_TOKEN).health() == {
                "status": "degraded"
            }

    asyncio.run(check())


def test_sdk_end_to_end(collect_server, caplog, capsys):
    async def check(url):
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + BRIDGE_TOKEN}, trust_env=False, timeout=15
        ) as http:
            async with streamable_http_client(url + "/mcp", http_client=http) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {tool.name for tool in tools.tools} == {
                        "add_note",
                        "list_notes",
                        "collect_health",
                    }
                    added = await session.call_tool(
                        "add_note", {"text": "integration-note", "tags": ["test"]}
                    )
                    assert not added.is_error
                    assert "integration-note" in added.content[0].text
                    default = await session.call_tool("add_note", {"text": "default-tags"})
                    assert not default.is_error
                    listed = await session.call_tool("list_notes", {"limit": 1, "tag": "test"})
                    assert not listed.is_error
                    assert "integration-note" in listed.content[0].text
                    assert "default-tags" not in listed.content[0].text
                    assert not (await session.call_tool("list_notes", {})).is_error
                    health = await session.call_tool("collect_health", {})
                    assert "ok" in health.content[0].text
                    invalid = await session.call_tool("add_note", {"text": "", "tags": []})
                    assert invalid.is_error
                    assert (
                        invalid.content[0].text
                        == "Error executing tool add_note: Collect request failed"
                    )

    with run_asgi(create_app()) as url:
        asyncio.run(check(url))
    output = caplog.text + str(capsys.readouterr())
    assert BRIDGE_TOKEN not in output
    assert COLLECT_TOKEN not in output


def test_main():
    with patch.object(bridge_server.uvicorn, "run") as run:
        bridge_server.main()
        assert run.call_args.kwargs["access_log"] is False


def test_sdk_collect_down(caplog, capsys):
    async def check(url):
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + BRIDGE_TOKEN}, trust_env=False, timeout=15
        ) as http:
            async with streamable_http_client(url + "/mcp", http_client=http) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    for name, arguments in (
                        ("add_note", {"text": "test"}),
                        ("list_notes", {}),
                    ):
                        result = await session.call_tool(name, arguments)
                        assert result.is_error
                        assert result.content[0].text == (
                            f"Error executing tool {name}: Collect request failed"
                        )
                    result = await session.call_tool("collect_health", {})
                    assert not result.is_error
                    assert "degraded" in result.content[0].text

    with run_asgi(create_app()) as url:
        asyncio.run(check(url))
    output = caplog.text + str(capsys.readouterr())
    assert BRIDGE_TOKEN not in output
    assert COLLECT_TOKEN not in output
