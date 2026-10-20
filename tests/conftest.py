import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn

from collect.collect_service import NotesServer

COLLECT_TOKEN = "synthetic-collect-token-" + "c" * 32
BRIDGE_TOKEN = "synthetic-bridge-token-" + "b" * 32


@pytest.fixture
def unreachable_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"


@pytest.fixture(autouse=True)
def synthetic_environment(monkeypatch, unreachable_url):
    monkeypatch.setenv("COLLECT_TOKEN", COLLECT_TOKEN)
    monkeypatch.setenv("BRIDGE_TOKEN", BRIDGE_TOKEN)
    monkeypatch.setenv("COLLECT_URL", unreachable_url)
    monkeypatch.setenv("COLLECT_DB_PATH", ":memory:")


@contextmanager
def run_collect(path):
    server = NotesServer(("127.0.0.1", 0), path, COLLECT_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def collect_server(tmp_path, monkeypatch):
    with run_collect(tmp_path / "notes.sqlite3") as (server, url):
        monkeypatch.setenv("COLLECT_URL", url)
        yield server, url


@contextmanager
def run_asgi(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Test server failed to start")
                time.sleep(0.01)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
