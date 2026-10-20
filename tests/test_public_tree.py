import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "public_tree", Path(__file__).parents[1] / "scripts" / "check_public_tree.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_canaries():
    checker.self_test()


@pytest.mark.parametrize(
    "path", [".env", ".env.local", "nested/.env", "private.key", "data.sqlite3", "private.log"]
)
def test_private_files(path):
    assert checker.private_path(path)


@pytest.mark.parametrize("path", [".env.example", "compose.yaml", "bridge/bridge_server.py"])
def test_public_files(path):
    assert not checker.private_path(path)


def test_invalid_date_is_not_identity_code():
    number = "32" + "13" + "00" + "123"
    check = chr(checker.CHECK_CHARACTERS[int(number) % 31])
    assert not checker.detect((number[:6] + "A" + number[6:] + check).encode())


def test_email_allowlist():
    assert not checker.detect(b"@".join((b"noreply", b"github.com")))
    assert checker.detect(b"@".join((b"someone", b"github.com"))) == ["non-example email address"]


def test_markdown_decorator_is_not_email():
    assert not checker.detect(b"`@server.tool()`")
    address = b"@".join((b"someone", b"github.com"))
    assert checker.detect(b"`" + address + b"`") == ["non-example email address"]


def test_working_file_and_history_detection(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path("safe.txt").write_text("safe")
    Path(".env").write_text("synthetic")
    Path("link").symlink_to("safe.txt")

    def git(*args):
        if args[0] == "rev-list":
            return b"abc123\n"
        if args[0] == "show":
            return b"@".join((b"synthetic", b"example.com"))
        if args[0] == "ls-tree":
            return b"100644 blob abc\t.env\0"
        if args[0] == "cat-file":
            return b"safe"
        if args[0] == "ls-files":
            return b"safe.txt\0.env\0link\0missing\0"
        raise AssertionError(args)

    monkeypatch.setattr(checker, "git", git)
    monkeypatch.setattr(checker.sys, "argv", ["checker"])
    assert checker.main() == 1
    output = capsys.readouterr().out
    assert "symbolic link" in output
    assert "private runtime/photo file" in output
    assert "FAIL: working file .env" not in output
