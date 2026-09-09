"""The kitty remote-control client, against a fake socket that records the wire."""
import json
import os
import socket
import threading

import pytest

from griot.brain import kitty


@pytest.fixture
def fake_kitty(tmp_path):
    """A unix socket that records every kitty-cmd message it receives."""
    address = str(tmp_path / "sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(address)
    server.listen(1)
    received: list[dict] = []

    def serve():
        conn, _ = server.accept()
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\x1b\\" in buf:
                head, buf = buf.split(b"\x1b\\", 1)
                _, _, body = head.partition(b"\x1bP@kitty-cmd")
                if body:
                    received.append(json.loads(body))
                    if json.loads(body).get("cmd") == "ls":
                        conn.sendall(b'\x1bP@kitty-cmd{"ok":true,"data":'
                                     b'"[{\\"is_focused\\":true}]"}\x1b\\')
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield address, received
    server.close()


def test_discover_prefers_an_explicit_override(monkeypatch):
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/from/env")
    assert kitty.discover_socket("unix:/from/config") == "/from/config"


def test_discover_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/from/env")
    assert kitty.discover_socket("") == "/from/env"


def test_discover_returns_none_when_there_is_no_kitty(monkeypatch):
    monkeypatch.delenv("KITTY_LISTEN_ON", raising=False)
    assert kitty.discover_socket("") is None


def test_send_png_streams_chunks_and_closes_the_stream(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.send_png(os.urandom(5000))
    client.close()
    assert received[0]["cmd"] == "set-background-image"
    assert received[0]["stream"] is True
    assert all(m["stream_id"] == received[0]["stream_id"] for m in received)
    assert "data" not in received[-1]["payload"], "final message closes the stream"
    assert len(received) > 3, "5000 bytes must span several chunks"


def test_every_chunk_is_within_the_size_limit(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.send_png(os.urandom(9000))
    client.close()
    assert all(len(m["payload"].get("data", "")) <= kitty.CHUNK for m in received)


def test_clear_removes_the_background(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.clear()
    client.close()
    assert received[-1]["payload"]["data"] == "none"


def test_focused_reads_the_reply(fake_kitty):
    address, _ = fake_kitty
    client = kitty.KittyBackground(address)
    assert client.focused() is True
    client.close()
