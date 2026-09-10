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
from griot.brain.pulse import Pulses, READ, WRITE
from griot.brain.reactor import positions, ramp, ring_of, scene

SPIN_RATE = 0.05          # radians per second
CORE_RATE = 1.1           # core breathing, radians per second
BIRTH_AMPLITUDE = 1.0
# What an event gives the core. The spec: "every event feeds the core, so
# the reactor draws power from wherever the work is happening" — a write is
# the heavier event and a birth is the one the feature exists for.
CORE_GAIN = {READ: 0.45, WRITE: 0.7}
BIRTH_CORE_GAIN = 1.0
# The core cools on the same constant a written node does, so the flare and
# the dot that caused it fade together instead of drifting apart.
CORE_DECAY = 1.6
FEED_TIME = 0.5           # seconds for an inward arc to reach the core
MAX_FEEDS = 24            # a burst of parallel tool calls is a starburst otherwise


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
        self._core = 0.0                     # the vault's own activity, 0..1
        self._feeds: list[list] = []         # [node index, how far in 0..1]
        self._scanning = False               # a rescan is out with a worker

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
        self._cool(step)

        self._start_scan(now)

        for node, kind in resolve_events(self.spool.read_new(), self.watcher.graph):
            path = self.watcher.graph.paths[node]
            if kind == "write" and path and self.watcher.swallows_write(path, now):
                continue          # its birth is coming, and that is the better event
            self.pulses.hit(node, kind)
            self._charge(node, CORE_GAIN[kind])

        cols, rows = self._dims()
        canvas = scene(self.watcher.graph, self.pulses, self.rings,
                       cols, rows, self._spin, self._phase,
                       core_energy=self._core,
                       feeds=[(index, head) for index, head in self._feeds])
        # pulse.Pulses._emit() ranks a node's onward connections by squared
        # distance via vector subtraction (`self.positions[c[1]] - here`),
        # which a plain list of tuples does not support — reactor.positions()
        # returns exactly that, so it has to become an array before it is
        # handed over.
        self.pulses.positions = np.asarray(
            positions(self.watcher.graph, self.rings,
                      (canvas.width / 2.0, canvas.height / 2.0), self._spin))
        self.last_frame = canvas.render(ramp(theme.PALETTE))

    # --- the rescan -------------------------------------------------------
    # A full vault walk costs 60ms on 986 notes (fingerprint's ~1,013 stat
    # calls are essentially all of it), against an 83ms frame at 12fps. Run
    # inline on the event loop it stalled the WHOLE status app — not just
    # the reactor — every 5 seconds for the entire session, and "smooth" is
    # the thing this feature was asked for. Measured on the real vault, the
    # worst main-thread gap over 1.5s of back-to-back scans: 63.5ms inline,
    # 15.3ms on a worker thread against a 10.9ms idle baseline. The stat
    # calls release the GIL, so the handover is nearly free.
    #
    # Only `watcher.scan()` goes to the thread. It mutates nothing, and
    # every decision that touches widget state — adopting the graph,
    # rebuilding the pulses, carrying energy across — happens back on the
    # event loop in `_adopt`, so a swap can never land halfway through a
    # frame.

    def _start_scan(self, now: float) -> None:
        if self._scanning or not self.watcher.due(now):
            return
        self.watcher.mark(now)
        self._scanning = True
        if not self._dispatch_scan():
            self._adopt(self.watcher.scan())     # no event loop: scan inline

    def _dispatch_scan(self) -> bool:
        """Hand the scan to a Textual thread worker. False when there is no
        running app — an unmounted widget, as the tests drive it — in which
        case the caller does the same work inline."""
        try:
            self.run_worker(self._scan_in_thread, thread=True,
                            exclusive=True, group="reactor-rescan")
        except Exception:
            return False
        return True

    def _scan_in_thread(self) -> None:
        """The worker body. Everything here is off the event loop, so it
        must not touch widget state — it reads the vault and hands the
        result back."""
        try:
            fresh = self.watcher.scan()
        except Exception:
            fresh = None                     # never strand self._scanning
        self._marshal(self._adopt, fresh)

    def _marshal(self, fn, *args) -> None:
        self.app.call_from_thread(fn, *args)

    def _adopt(self, fresh) -> None:
        """Back on the event loop with a scanned graph."""
        self._scanning = False
        was_graph, was_pulses = self.watcher.graph, self.pulses
        # Rebuild on any change to the vault, not only on a birth. A note
        # being DELETED or renamed moves every index after it and produces
        # no births at all, which left self.rings and self.pulses sized and
        # ordered for a graph that no longer existed.
        changed = fresh is not None and fresh.fingerprint != was_graph.fingerprint
        # Rebuild ONCE for the whole rescan, not once per birth: the rebuild
        # replaces self.pulses, so doing it per birth zeroed the one before
        # it — a turn that created three notes animated exactly one — and
        # wiped any cascade in flight (energy sum 1.494 -> 1.000 after a
        # single birth).
        born = self.watcher.adopt(fresh)
        if not changed:
            return
        self._rebuild(was_graph, was_pulses)
        for index in born:              # indices into the NEW graph
            self.pulses.energy[index] = BIRTH_AMPLITUDE
            self.pulses.kind_of[index] = WRITE
            self._charge(index, BIRTH_CORE_GAIN)

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

        self._feeds = [[moved[i], head] for i, head in self._feeds if i in moved]
        self.pulses = pulses

    def _cool(self, step: float) -> None:
        """The core loses charge the way a node does, and the arcs feeding
        it keep travelling inward."""
        self._core *= math.exp(-step / CORE_DECAY)
        if self._core < 0.005:
            self._core = 0.0
        for feed in self._feeds:
            feed[1] += step / FEED_TIME
        self._feeds = [f for f in self._feeds if f[1] <= 1.0]

    def _charge(self, index: int, gain: float) -> None:
        """An event reaching the vault: the core takes power from it and an
        arc runs inward from the note it happened to.

        Only real events do this. Idle twinkles set node energy directly and
        never come through here, so a resting reactor keeps a still core —
        an arc across the disc always means something is happening.
        """
        self._core = min(1.0, self._core + gain)
        if len(self._feeds) < MAX_FEEDS:
            self._feeds.append([index, 0.0])
