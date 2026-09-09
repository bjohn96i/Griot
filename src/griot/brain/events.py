"""Tail the hook's append-only spool.

A plain file with an offset, not a FIFO: a FIFO with no reader blocks its
writer, and the writer here runs on every one of Claude's tool calls. A
stalled hook would stall Claude.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .graph import Graph

KINDS = {"read", "write"}


@dataclass(frozen=True)
class Event:
    ts: float
    kind: str
    path: str


class Spool:
    def __init__(self, path: Path, max_bytes: int = 65536) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.offset = 0

    def read_new(self) -> list[Event]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:            # someone truncated it under us
            self.offset = 0
        events: list[Event] = []
        try:
            with self.path.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith("\n"):
                        break             # a partial write; pick it up next tick
                    self.offset += len(line.encode("utf-8"))
                    event = _parse(line)
                    if event is not None:
                        events.append(event)
        except OSError:
            return events
        if self.offset >= self.max_bytes:
            self._rotate()
        return events

    def _rotate(self) -> None:
        """Truncate only when nothing arrived after our read.

        The hook appends on every Claude tool call, and a blind truncate(0)
        here would destroy anything written between the read loop finishing
        and this call — silently, since we would never have seen it. If the
        file has grown, skip rotation and take it on a later pass; the spool
        is only a little over its ceiling for one cycle.
        """
        try:
            with self.path.open("r+") as f:
                if f.seek(0, 2) != self.offset:
                    return
                f.truncate(0)
            self.offset = 0
        except OSError:
            pass


def _parse(line: str) -> Event | None:
    parts = line.rstrip("\n").split(" ", 2)
    if len(parts) != 3:
        return None
    raw_ts, kind, path = parts
    if kind not in KINDS or not path:
        return None
    try:
        return Event(float(raw_ts), kind, path)
    except ValueError:
        return None


def resolve(events: list[Event], graph: Graph) -> list[tuple[int, str]]:
    """Map spool events onto node indices, dropping paths outside the vault."""
    hits: list[tuple[int, str]] = []
    for event in events:
        node = graph.by_path.get(event.path)
        if node is None:
            node = graph.by_path.get(os.path.realpath(event.path))
        if node is not None:
            hits.append((node, event.kind))
    return hits
