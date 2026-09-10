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

        for index in self.watcher.poll(now):
            self._rebuild()
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

    def _rebuild(self) -> None:
        """The vault grew, so the graph and rings are stale. Energy is not
        carried over — indices have moved."""
        self.rings = ring_of(self.watcher.graph)
        self.pulses = Pulses(self.watcher.graph, hops=int(self.cfg["hops"]))
