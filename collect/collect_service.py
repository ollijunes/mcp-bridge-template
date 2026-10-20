"""A small authenticated notes API using only the standard library."""

import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 16 * 1024
TAG = re.compile(r"[a-z0-9-]{1,32}\Z")


def require_token(name):
    value = os.environ.get(name, "")
    if len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 characters")
    return value


def valid_tags(tags):
    return (
        isinstance(tags, list)
        and len(tags) <= 10
        and all(isinstance(tag, str) and TAG.fullmatch(tag) for tag in tags)
    )


class NotesServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path, token):
        self.db_path = str(db_path)
        self.token = token.encode()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS notes ("
                "id INTEGER PRIMARY KEY, text TEXT NOT NULL, tags TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )
        super().__init__(address, NotesHandler)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()


class NotesHandler(BaseHTTPRequestHandler):
    server: NotesServer

    def log_message(self, format, *args):
        # Request paths and headers may contain secrets; do not log them.
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(data)

    def authorized(self):
        headers = self.headers.get_all("Authorization", [])
        candidate = headers[0].encode() if len(headers) == 1 else b""
        if not hmac.compare_digest(candidate, b"Bearer " + self.server.token):
            self.reply(401, {"error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.dispatch
        raise AttributeError(name)

    def dispatch(self):
        self.connection.settimeout(5)
        path = urlsplit(self.path).path
        if self.command == "GET" and path == "/healthz":
            try:
                with self.server.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE notes SET text = text WHERE id = -1")
                    db.rollback()
                self.reply(200, {"status": "ok"})
            except sqlite3.Error:
                self.reply(503, {"status": "unavailable"})
            return
        if not self.authorized():
            return
        try:
            if path != "/notes":
                self.reply(404, {"error": "Not found"})
            elif self.command == "POST":
                self.add_note()
            elif self.command == "GET":
                self.list_notes()
            else:
                self.reply(405, {"error": "Method not allowed"})
        except sqlite3.Error:
            self.reply(503, {"error": "Database unavailable"})

    def add_note(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            self.reply(400, {"error": "Invalid request body"})
            return
        try:
            length = int(lengths[0])
            if length < 0:
                raise ValueError
        except ValueError:
            self.reply(400, {"error": "Invalid request body"})
            return
        if length > MAX_BODY:
            self.reply(413, {"error": "Request body too large"})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError
            body = json.loads(raw)
        except (ValueError, RecursionError, TimeoutError):
            self.reply(400, {"error": "Invalid JSON"})
            return
        if (
            not isinstance(body, dict)
            or set(body) != {"text", "tags"}
            or not isinstance(body["text"], str)
            or not 1 <= len(body["text"]) <= 2000
            or not valid_tags(body["tags"])
        ):
            self.reply(400, {"error": "Invalid note"})
            return
        try:
            body["text"].encode("utf-8")
        except UnicodeEncodeError:
            self.reply(400, {"error": "Invalid note"})
            return
        created_at = datetime.now(UTC).isoformat()
        with self.server.connect() as db:
            cursor = db.execute(
                "INSERT INTO notes (text, tags, created_at) VALUES (?, ?, ?)",
                (body["text"], json.dumps(body["tags"]), created_at),
            )
            note_id = cursor.lastrowid
        self.reply(201, {"id": note_id, **body, "created_at": created_at})

    def list_notes(self):
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=10)
            if set(query) - {"limit", "tag"} or any(len(values) != 1 for values in query.values()):
                raise ValueError
            limit = int(query.get("limit", ["20"])[0])
            tag = query.get("tag", [None])[0]
            if not 1 <= limit <= 100 or (tag is not None and not TAG.fullmatch(tag)):
                raise ValueError
        except ValueError:
            self.reply(400, {"error": "Invalid query"})
            return
        with self.server.connect() as db:
            rows = db.execute(
                "SELECT id, text, tags, created_at FROM notes "
                "WHERE (? IS NULL OR EXISTS (SELECT 1 FROM json_each(notes.tags) WHERE value = ?)) "
                "ORDER BY id DESC LIMIT ?",
                (tag, tag, limit),
            ).fetchall()
        self.reply(200, [{**dict(row), "tags": json.loads(row["tags"])} for row in rows])


def main():
    token = require_token("COLLECT_TOKEN")
    server = NotesServer(
        ("0.0.0.0", 8080),  # noqa: S104 - container listener; Compose keeps it internal.
        os.environ.get("COLLECT_DB_PATH", "/data/notes.sqlite3"),
        token,
    )
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
