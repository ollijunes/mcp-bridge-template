import concurrent.futures
import hmac
import http.client
import json
import queue
import socket
import sqlite3
import time
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import patch

import httpx
import pytest
from conftest import COLLECT_TOKEN, run_collect

from collect import collect_service


@pytest.fixture
def client(collect_server):
    with httpx.Client(
        base_url=collect_server[1],
        headers={"Authorization": f"Bearer {COLLECT_TOKEN}"},
        trust_env=False,
    ) as client:
        yield client


def test_crud_and_filter(client):
    assert client.get("/notes").json() == []
    first = client.post("/notes", json={"text": "first", "tags": ["one", "two"]})
    assert first.status_code == 201
    assert datetime.fromisoformat(first.json()["created_at"]).utcoffset().total_seconds() == 0
    second = client.post("/notes", json={"text": "second", "tags": ["two"]}).json()
    assert client.get("/notes").json() == [second, first.json()]
    assert client.get("/notes?limit=1").json() == [second]
    assert client.get("/notes?tag=one").json() == [first.json()]
    assert client.get("/notes?tag=absent").json() == []
    assert client.get("/unknown").status_code == 404
    assert client.put("/notes").status_code == 405


@pytest.mark.parametrize(
    "method,path", [("GET", "/notes"), ("POST", "/notes"), ("DELETE", "/x"), ("BREW", "/notes")]
)
@pytest.mark.parametrize("token", ["", "wrong", "bearer " + COLLECT_TOKEN])
def test_auth(client, method, path, token):
    response = client.request(method, path, headers={"Authorization": token})
    assert response.status_code == 401
    assert response.json() == {"error": "Unauthorized"}


def test_constant_time_and_health(client):
    with patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as compare:
        assert client.get("/notes").status_code == 200
        compare.assert_called_once()
    assert client.get("/healthz", headers={"Authorization": ""}).json() == {"status": "ok"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        None,
        {"text": "", "tags": []},
        {"text": "x" * 2001, "tags": []},
        {"text": 1, "tags": []},
        {"text": "private-canary", "tags": ["UPPER"]},
        {"text": "x", "tags": [""]},
        {"text": "x", "tags": ["x" * 33]},
        {"text": "x", "tags": ["x"] * 11},
        {"text": "x", "tags": [1]},
        {"text": "x", "tags": "tag"},
        {"text": "x"},
        {"text": "x", "tags": [], "extra": True},
        {"text": "\ud800", "tags": []},
    ],
)
def test_invalid_notes(client, body):
    response = client.post("/notes", content=json.dumps(body))
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid note"}
    assert "private-canary" not in response.text


@pytest.mark.parametrize("raw", [b"not-json-secret", b"\xff", b"[" * 2000])
def test_invalid_json(client, raw):
    response = client.post("/notes", content=raw)
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid JSON"}


def test_body_limit(client):
    assert client.post("/notes", content=b"x" * (16384 + 1)).status_code == 413
    assert client.post("/notes", content=b"x" * 16384).status_code == 400
    assert (
        client.post("/notes", json={"text": "x" * 2000, "tags": ["a" * 32] * 10}).status_code == 201
    )


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=no",
        "tag=UPPER",
        "tag=",
        "x=y",
        "limit=1&limit=2",
        "&".join(["tag=x"] * 11),
    ],
)
def test_invalid_query(client, query):
    response = client.get("/notes?" + query)
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid query"}


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Content-Length", "-1")],
        [("Content-Length", "bad")],
        [("Content-Length", "0"), ("Content-Length", "0")],
        [("Transfer-Encoding", "chunked")],
    ],
)
def test_invalid_framing(collect_server, headers):
    connection = http.client.HTTPConnection("127.0.0.1", collect_server[0].server_port)
    connection.putrequest("POST", "/notes")
    connection.putheader("Authorization", "Bearer " + COLLECT_TOKEN)
    for key, value in headers:
        connection.putheader(key, value)
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {"error": "Invalid request body"}
    connection.close()


def test_persistence_and_concurrency(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with run_collect(path) as (_, url):

        def post(number):
            return httpx.post(
                url + "/notes",
                json={"text": str(number), "tags": []},
                headers={"Authorization": "Bearer " + COLLECT_TOKEN},
                trust_env=False,
            ).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(post, range(8))) == [201] * 8
    with run_collect(path) as (_, url):
        response = httpx.get(
            url + "/notes", headers={"Authorization": "Bearer " + COLLECT_TOKEN}, trust_env=False
        )
        assert len(response.json()) == 8


def test_database_failure(client, collect_server):
    with patch.object(collect_server[0], "connect", side_effect=sqlite3.OperationalError):
        assert client.get("/healthz").status_code == 503
        assert client.get("/notes").json() == {"error": "Database unavailable"}


def test_no_logs(client, caplog, capsys):
    client.post("/notes", json={"text": "private-note-canary", "tags": []})
    client.get("/notes", headers={"Authorization": "Bearer wrong-secret"})
    output = caplog.text + str(capsys.readouterr())
    assert COLLECT_TOKEN not in output
    assert "wrong-secret" not in output
    assert "private-note-canary" not in output


def test_main(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECT_DB_PATH", str(tmp_path / "main.sqlite3"))
    with patch.object(collect_service, "NotesServer") as server:
        collect_service.main()
        server.return_value.serve_forever.assert_called_once()


@pytest.mark.parametrize("partial", [b"GET /no", b"GET /notes HTTP/1.1\r\nHost: local"])
def test_partial_request_times_out(collect_server, partial):
    started = time.monotonic()
    with socket.create_connection(collect_server[0].server_address, timeout=6) as sock:
        sock.sendall(partial)
        assert sock.recv(1) == b""
    assert 4.5 <= time.monotonic() - started < 6


def test_idle_connection_limit_and_recovery(collect_server, client, monkeypatch):
    accepted = queue.Queue()
    original_setup = collect_service.NotesHandler.setup

    def setup(handler):
        original_setup(handler)
        accepted.put(True)

    monkeypatch.setattr(collect_service.NotesHandler, "setup", setup)
    address = collect_server[0].server_address
    with ExitStack() as stack:
        idle = []
        for _ in range(32):
            idle.append(stack.enter_context(socket.create_connection(address, timeout=6)))
            accepted.get(timeout=1)
        for _ in range(4):
            with socket.create_connection(address, timeout=1) as excess:
                assert excess.recv(1) == b""
        assert accepted.empty()
        for sock in idle:
            assert sock.recv(1) == b""
        response = client.get("/notes")
        assert response.status_code == 200
        assert response.json() == []


def test_connection_slots_released_on_thread_start_failure(collect_server, client):
    server = collect_server[0]
    with (
        socket.socket() as request,
        patch.object(
            collect_service.ThreadingHTTPServer,
            "process_request",
            side_effect=RuntimeError("start"),
        ),
    ):
        for _ in range(33):
            with pytest.raises(RuntimeError, match="start"):
                server.process_request(request, ("127.0.0.1", 12345))
    assert client.get("/notes").status_code == 200
