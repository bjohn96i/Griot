"""Notice new notes.

The hook tells us about reads and writes, but not that a file is new — and a
note being born is the event this whole widget exists to show. The graph's
fingerprint already keys on note count plus newest mtime, so a rescan is
cheap and only rebuilds when something actually changed.
"""
from __future__ import annotations

from pathlib import Path

from . import graph as graph_module
from .graph import Graph


class BirthWatcher:
    def __init__(self, vault_path: Path, cache_path: Path,
                 interval: float = 5.0, suppress: float = 5.0) -> None:
        self.vault_path = Path(vault_path)
        self.cache_path = Path(cache_path)
        self.interval = interval
        self.suppress = suppress
        self.graph: Graph = graph_module.load_or_build(self.vault_path, self.cache_path)
        self._known: set[str] = set(self.graph.by_path)
        self._last = float("-inf")

    # The rescan is split into three so the expensive third of it can run
    # off the caller's thread. `scan()` is the only slow part — measured at
    # 60ms on a 986-node vault, of which fingerprint()'s ~1,013 stat calls
    # are 60ms — and it is deliberately pure: it reads self.graph.n and
    # touches nothing else, so it is safe to run while frames are being
    # drawn from the graph it has not replaced yet. `due`/`mark`/`adopt`
    # are all cheap and belong to whichever thread owns the widget.

    def due(self, now: float) -> bool:
        return now - self._last >= self.interval

    def mark(self, now: float) -> None:
        """Start the interval clock. Called when a rescan is *launched*, so
        `swallows_write` measures from the attempt, not from its result."""
        self._last = now

    def scan(self):
        """Read the vault. Returns the fresh graph, or None if this rescan
        should be ignored. Safe to call off the event loop: it mutates
        nothing."""
        try:
            fresh = graph_module.load_or_build(self.vault_path, self.cache_path)
        except OSError:
            return None                    # keep the graph we have; try again later
        if fresh.n == 0 and self.graph.n:
            return None                    # an empty read is a failure, not an empty vault
        return fresh

    def adopt(self, fresh) -> list[int]:
        """Take a scanned graph as the current one; return the new notes."""
        if fresh is None:
            return []
        born = [index for path, index in fresh.by_path.items() if path not in self._known]
        self.graph = fresh
        self._known = set(fresh.by_path)
        return born

    def poll(self, now: float) -> list[int]:
        """Rescan inline. Convenient and correct, but it costs a whole
        frame on a real vault — the widget hands `scan()` to a worker."""
        if not self.due(now):
            return []
        self.mark(now)
        return self.adopt(self.scan())

    def swallows_write(self, path: str, now: float) -> bool:
        """True while a write's birth is still expected. Expires so that a
        note the rescan never sees still produces some animation."""
        if path in self._known:
            return False
        return now - self._last <= self.suppress
