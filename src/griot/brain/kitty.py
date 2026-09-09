"""Push frames into kitty's window background over remote control.

kitty draws background_image *below* cell backgrounds, which is why this works
under a full-screen TUI: Claude Code sets an explicit background on ~11 cells
of a 120x40 screen, so the image shows through nearly the whole pane. The
graphics protocol is deliberately not used — under tmux it renders via unicode
placeholders that live in real cells, and Claude Code's next repaint destroys
them.

Requires `allow_remote_control socket-only` plus `listen_on` in kitty.conf.
`socket-only` is preferred because it refuses remote-control commands
arriving over the terminal's own escape channel, which plain `yes` permits —
both settings were tested against kitty 0.48.2 and both work.
"""
from __future__ import annotations

import base64
import json
import os
import select
import socket
import time
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
    def __init__(self, address: str, timeout: float = 2.0) -> None:
        self.timeout = timeout
        self._buf = b""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(address)

    def _send(self, payload: dict) -> None:
        self.sock.sendall(b"\x1bP@kitty-cmd" + json.dumps(payload).encode() + b"\x1b\\")

    def _take_messages(self) -> list[dict]:
        """Parse whole `\\x1bP@kitty-cmd...\\x1b\\\\` frames out of the buffer.

        Buffered rather than one-shot because a reply can arrive split across
        recv boundaries, or two replies can arrive coalesced in one.
        """
        messages = []
        while b"\x1b\\" in self._buf:
            head, self._buf = self._buf.split(b"\x1b\\", 1)
            _, _, body = head.partition(b"\x1bP@kitty-cmd")
            if not body:
                continue
            try:
                messages.append(json.loads(body))
            except ValueError:
                pass
        return messages

    def _read_available(self, timeout: float) -> None:
        ready, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if ready:
            chunk = self.sock.recv(1 << 16)
            if chunk:
                self._buf += chunk

    def _discard_acks(self) -> None:
        """kitty acks every set-background-image stream. Unread, those acks
        fill the 8 KB socket buffer after ~35s of animation and then block
        kitty's own writes — measured against kitty 0.48.2.
        """
        while True:
            ready, _, _ = select.select([self.sock], [], [], 0)
            if not ready:
                break
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                break
            self._buf += chunk
        self._take_messages()

    def send_png(self, data: bytes) -> None:
        encoded = base64.b64encode(data).decode()
        stream_id = uuid.uuid4().hex
        first = True
        for i in range(0, len(encoded), CHUNK):
            message = {"cmd": "set-background-image", "version": VERSION,
                       "stream_id": stream_id, "no_response": True,
                       "payload": {"data": encoded[i:i + CHUNK], "layout": LAYOUT}}
            if first:
                message["stream"] = True
                first = False
            self._send(message)
        self._send({"cmd": "set-background-image", "version": VERSION,
                    "stream_id": stream_id, "no_response": True,
                    "payload": {"layout": LAYOUT}})
        self._discard_acks()

    def clear(self) -> None:
        """Drop the background image so a dead animator leaves no frozen frame."""
        self._send({"cmd": "set-background-image", "version": VERSION, "no_response": True,
                    "payload": {"data": "none", "layout": LAYOUT}})
        self._discard_acks()

    def focused(self) -> bool:
        """True when the kitty window has focus. Anything unreadable means yes
        — a missing answer must never pause the animation.
        """
        self._discard_acks()
        self._send({"cmd": "ls", "version": VERSION, "payload": {}})
        deadline = time.monotonic() + 0.5
        while True:
            for message in self._take_messages():
                verdict = _focus_verdict(message)
                if verdict is not None:
                    return verdict
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._read_available(remaining)

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


def _carries_focus(node) -> bool:
    if isinstance(node, dict):
        return "is_focused" in node or any(_carries_focus(v) for v in node.values())
    if isinstance(node, list):
        return any(_carries_focus(v) for v in node)
    return False


def _focus_verdict(message: dict) -> bool | None:
    """None when this message is not a focus answer — an ack, say."""
    data = message.get("data")
    try:
        windows = json.loads(data) if isinstance(data, str) else data
    except (ValueError, TypeError):
        return None
    if not _carries_focus(windows):
        return None
    return _any_focused(windows)
