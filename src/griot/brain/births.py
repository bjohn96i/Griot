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

    def poll(self, now: float) -> list[int]:
        if now - self._last < self.interval:
            return []
        self._last = now
        try:
            fresh = graph_module.load_or_build(self.vault_path, self.cache_path)
        except OSError:
            return []                      # keep the graph we have; try again later
        if fresh.n == 0 and self.graph.n:
            return []                      # an empty read is a failure, not an empty vault
        born = [index for path, index in fresh.by_path.items() if path not in self._known]
        self.graph = fresh
        self._known = set(fresh.by_path)
        return born

    def swallows_write(self, path: str, now: float) -> bool:
        """True while a write's birth is still expected. Expires so that a
        note the rescan never sees still produces some animation."""
        if path in self._known:
            return False
        return now - self._last <= self.suppress
