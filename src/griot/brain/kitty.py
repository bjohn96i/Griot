"""Push frames into kitty's window background over remote control.

kitty draws background_image *below* cell backgrounds, which is why this works
under a full-screen TUI: Claude Code sets an explicit background on ~11 cells
of a 120x40 screen, so the image shows through nearly the whole pane. The
graphics protocol is deliberately not used — under tmux it renders via unicode
placeholders that live in real cells, and Claude Code's next repaint destroys
them.

Requires `allow_remote_control socket-only` plus `listen_on` in kitty.conf.
Plain `allow_remote_control yes` makes kitty reject listen_on outright.
"""
from __future__ import annotations

import base64
import json
import os
import select
import socket
import uuid

CHUNK = 2048
VERSION = [0, 26, 0]
LAYOUT = "scaled"


def discover_socket(override: str = "") -> str | None:
    """Config override wins, then KITTY_LISTEN_ON, else there is no kitty."""
    address = override or os.environ.get("KITTY_LISTEN_ON", "")
    if not address:
        return None
    return address[len("unix:"):] if address.startswith("unix:") else address


class KittyBackground:
    def __init__(self, address: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(address)

    def _send(self, payload: dict) -> None:
        self.sock.sendall(b"\x1bP@kitty-cmd" + json.dumps(payload).encode() + b"\x1b\\")

    def send_png(self, data: bytes) -> None:
        encoded = base64.b64encode(data).decode()
        stream_id = uuid.uuid4().hex
        first = True
        for i in range(0, len(encoded), CHUNK):
            message = {"cmd": "set-background-image", "version": VERSION,
                       "stream_id": stream_id,
                       "payload": {"data": encoded[i:i + CHUNK], "layout": LAYOUT}}
            if first:
                message["stream"] = True
                first = False
            self._send(message)
        self._send({"cmd": "set-background-image", "version": VERSION,
                    "stream_id": stream_id, "payload": {"layout": LAYOUT}})

    def clear(self) -> None:
        """Drop the background image so a dead animator leaves no frozen frame."""
        self._send({"cmd": "set-background-image", "version": VERSION,
                    "payload": {"data": "none", "layout": LAYOUT}})

    def focused(self) -> bool:
        """True when the kitty window has focus. Unreadable replies mean yes."""
        self._send({"cmd": "ls", "version": VERSION, "payload": {}})
        ready, _, _ = select.select([self.sock], [], [], 0.5)
        if not ready:
            return True
        raw = self.sock.recv(1 << 16)
        _, _, body = raw.partition(b"\x1bP@kitty-cmd")
        body = body.split(b"\x1b\\", 1)[0]
        try:
            reply = json.loads(body)
            data = reply.get("data")
            windows = json.loads(data) if isinstance(data, str) else data
            return any(_any_focused(w) for w in windows)
        except (ValueError, TypeError, AttributeError):
            return True

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _any_focused(node) -> bool:
    if isinstance(node, dict):
        if node.get("is_focused"):
            return True
        return any(_any_focused(v) for v in node.values())
    if isinstance(node, list):
        return any(_any_focused(v) for v in node)
    return False
