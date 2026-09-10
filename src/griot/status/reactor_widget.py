"""The reactor widget.

Lives in the right pane on a timer. There is no separate process: the status
app already runs a Textual event loop, and putting the animation inside it
removes the pidfile, the focus gate, the socket and the log that the previous
implementation needed.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from textual.widgets import Static

from griot import theme
from griot.brain.births import BirthWatcher
from griot.brain.events import Spool, resolve as resolve_events
from griot.brain.pulse import Pulses, WRITE
from griot.brain.reactor import positions, ramp, ring_of, scene

SPIN_RATE = 0.05          # radians per second
CORE_RATE = 1.1           # core breathing, radians per second
BIRTH_AMPLITUDE = 1.0


class Reactor(Static):
    def __init__(self, cfg: dict, vault_path: Path, spool_path: Path,
                 cache_path: Path, id: str | None = None) -> None:
        super().__init__("", id=id)
        self.cfg = cfg
        self.spool = Spool(Path(spool_path))
        self.watcher = BirthWatcher(Path(vault_path), Path(cache_path))
        self.rings = ring_of(self.watcher.graph)
        self.pulses = Pulses(self.watcher.graph, hops=int(cfg["hops"]))
        self.last_frame = None
        self._spin = 0.0
        self._phase = 0.0
        self._previous = None

    def _dims(self) -> tuple[int, int]:
        """Textual only knows the real size once mounted; tests drive tick()
        directly on an unmounted widget, so fall back rather than raise."""
        try:
            width, height = self.size.width, self.size.height
        except Exception:
            width = height = 0
        return max(10, width or 43), max(6, height or 22)

    def on_mount(self) -> None:
        self.set_interval(1.0 / float(self.cfg["fps"]), self._advance)
        self._advance()

    def _advance(self) -> None:
        self.tick(time.monotonic())
        self.update(self.last_frame)

    def tick(self, now: float) -> None:
        step = 1.0 / float(self.cfg["fps"])
        if self._previous is not None:
            step = max(1e-3, now - self._previous)
        self._previous = now

        # Advance the state we already had up to `now` BEFORE landing this
        # tick's own hits — advancing afterwards decayed a hit by the whole
        # gap since the last tick before it was ever rendered. A 0.85-amplitude
        # read with decay=1.2 over a 1s gap fell to 0.37, under the "lit"
        # threshold on the very tick that lit it.
        self._spin += SPIN_RATE * step
        self._phase += CORE_RATE * step
        self.pulses.advance(step)

        # Rebuild ONCE for the whole rescan, not once per birth. The rebuild
        # replaces self.pulses, so doing it inside the loop meant each birth
        # zeroed the one before it — a turn that created three notes animated
        # exactly one of them — and wiped any cascade already in flight
        # (measured: energy sum 1.494 -> 1.000 after a single birth).
        # `poll()` has already swapped watcher.graph, so the old graph and
        # pulses have to be captured before it is called.
        was_graph, was_pulses = self.watcher.graph, self.pulses
        born = self.watcher.poll(now)
        if born:
            self._rebuild(was_graph, was_pulses)
            for index in born:          # indices into the NEW graph
                self.pulses.energy[index] = BIRTH_AMPLITUDE
                self.pulses.kind_of[index] = WRITE

        for node, kind in resolve_events(self.spool.read_new(), self.watcher.graph):
            path = self.watcher.graph.paths[node]
            if kind == "write" and path and self.watcher.swallows_write(path, now):
                continue          # its birth is coming, and that is the better event
            self.pulses.hit(node, kind)

        cols, rows = self._dims()
        canvas = scene(self.watcher.graph, self.pulses, self.rings,
                       cols, rows, self._spin, self._phase)
        # pulse.Pulses._emit() ranks a node's onward connections by squared
        # distance via vector subtraction (`self.positions[c[1]] - here`),
        # which a plain list of tuples does not support — reactor.positions()
        # returns exactly that, so it has to become an array before it is
        # handed over.
        self.pulses.positions = np.asarray(
            positions(self.watcher.graph, self.rings,
                      (canvas.width / 2.0, canvas.height / 2.0), self._spin))
        self.last_frame = canvas.render(ramp(theme.PALETTE))

    def _rebuild(self, was_graph, was_pulses) -> None:
        """The vault grew, so the graph and rings are stale.

        Indices move when the graph is rebuilt, but a note that survived the
        rescan is the same note and must keep doing whatever it was doing —
        so state is carried across by PATH rather than discarded. Dropping
        it meant a note being created extinguished the very cascade its own
        write had started moments earlier.
        """
        fresh = self.watcher.graph
        self.rings = ring_of(fresh)
        pulses = Pulses(fresh, hops=int(self.cfg["hops"]))

        moved: dict[int, int] = {}
        for old, path in enumerate(was_graph.paths):
            new = fresh.by_path.get(path) if path else None
            if new is None:
                continue
            moved[old] = new
            pulses.energy[new] = was_pulses.energy[old]
            pulses.decay[new] = was_pulses.decay[old]      # or it reverts to WRITE's
            pulses.kind_of[new] = was_pulses.kind_of[old]

        # The sparks ARE the cascade — carrying node energy alone would keep
        # what has already been lit and still cancel every hop still to come.
        # Edge indices move too, so each spark's edge is re-found by its
        # endpoints. Anything touching a phantom (no path, so nothing to
        # match on) is dropped rather than guessed at.
        edge_at = {(min(a, b), max(a, b)): i for i, (a, b) in enumerate(fresh.edges)}
        carried = []
        for edge, target, progress, amplitude, kind, hop in was_pulses._sparks:
            a, b = was_graph.edges[edge]
            if a not in moved or b not in moved or target not in moved:
                continue
            index = edge_at.get((min(moved[a], moved[b]), max(moved[a], moved[b])))
            if index is None:
                continue
            carried.append([index, moved[target], progress, amplitude, kind, hop])
        pulses._sparks = carried

        self.pulses = pulses
