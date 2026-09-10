"""Node energy and the electrons riding the edges.

A hit blooms the node and sends a wave outward, weakening at each hop and
dying at the limit — so writing a hub lights up a cluster and writing an
orphan barely flickers, which is how the vault's structure becomes visible
through activity. Reads are the lighter event, mirroring the asymmetry
sound.py already established for the drive.
"""
from __future__ import annotations

import numpy as np

from .graph import Graph

READ, WRITE = "read", "write"

ORIGIN_AMPLITUDE = 1.0
# What each hop keeps of the one before it. This was implicit in the ratio of
# the last two entries of an amplitude tuple — 0.545 — which put hop 3 at 0.138 and
# hop 4 at 0.075. Measured: after 0.5s not one node was above 0.30, so the
# cascade was invisible past the first flash however long it ran. At 0.78 the
# series is 0.85 / 0.72 / 0.61 / 0.52 / 0.44 — still visibly declining, but
# every hop stays bright enough to see.
HOP_FALLOFF = 0.85
# A hop is carried by a spark travelling the connection, not by a timer: the
# old fixed delay lit every neighbour of a hub simultaneously, which reads as a
# ring flashing on rather than a signal propagating.
SPARK_SPEED = 1.0         # edges per second
SPARK_FANOUT = 3          # onward connections a spark lights from where it lands
SPARK_FIRST_FANOUT = 6    # was 12: twelve arcs inside an 86-dot disc is a
                          # starburst, six reads as branching
MAX_SPARKS = 500
# Idle life: instead of electrons circulating on every edge, random nodes
# twinkle on their own. Edge traffic at rest read as noise and competed with
# the cascade; a quiet node blinking does not.
IDLE_RATE = 14.0          # twinkles per second across the whole graph
IDLE_AMPLITUDE = 0.22
IDLE_DECAY = 0.8
QUIET = 0.01

KINDS = {
    WRITE: {"scale": 1.0, "decay": 1.6, "hops": 5},
    READ: {"scale": 0.85, "decay": 1.2, "hops": 5},
}


class Pulses:
    def __init__(self, graph: Graph, hops: int = 5, speed: float = 1.0,
                 spread: float = 1.0) -> None:
        self.graph = graph
        self.hops = hops
        # `speed` and `spread` are multipliers on the tuned constants rather
        # than replacements for them, so 1.0 is exactly the tuned reactor and
        # the constants stay the single place the baseline is recorded.
        # Fan-outs floor at 1: a multiplier small enough to round to zero
        # would turn every hit into a lone dot with no cascade at all.
        self.speed = SPARK_SPEED * speed
        self.first_fanout = max(1, round(SPARK_FIRST_FANOUT * spread))
        self.fanout = max(1, round(SPARK_FANOUT * spread))
        self.energy = np.zeros(graph.n, np.float32)
        self.decay = np.full(graph.n, KINDS[WRITE]["decay"], np.float32)
        self.kind_of = np.array([WRITE] * graph.n, dtype=object)
        # each spark: [edge index, node it is heading for, progress 0..1,
        #              amplitude it will deliver, kind, hop number]
        self._sparks: list[list] = []
        # The app points this at the live layout each tick. Without it the
        # cascade fans out by edge index, which on this vault meant a median
        # hop of 445px across a 1400px canvas — sparks flying to scattered
        # distant nodes, which reads as random rather than as a wave.
        self.positions = None
        self._clock = 0.0
        self._incident: list[list[tuple[int, int]]] = [[] for _ in range(graph.n)]
        for index, (a, b) in enumerate(graph.edges):
            self._incident[a].append((index, b))
            self._incident[b].append((index, a))
        self._rng = np.random.default_rng(17)

    @property
    def active(self) -> bool:
        return bool(self.energy.max(initial=0.0) > QUIET) or bool(self._sparks)

    def sparks(self) -> list[tuple[int, float, float]]:
        """(edge index, position along that edge 0..1, amplitude) per spark."""
        out = []
        for index, target, progress, amplitude, _kind, _hop in self._sparks:
            a, _b = self.graph.edges[index]
            out.append((index, progress if target != a else 1.0 - progress, amplitude))
        return out

    def _emit(self, node: int, amplitude: float, kind: str, hop: int, came_from: int) -> None:
        """Send sparks out along this node's connections."""
        limit = min(self.hops, KINDS[kind]["hops"])
        if hop > limit or amplitude < QUIET:
            return
        fan = self.first_fanout if hop == 1 else self.fanout
        room = MAX_SPARKS - len(self._sparks)
        if room <= 0:
            return
        candidates = [c for c in self._incident[node] if c[1] != came_from]
        if self.positions is not None:
            here = self.positions[node]
            candidates.sort(key=lambda c: float(((self.positions[c[1]] - here) ** 2).sum()))
        for index, other in candidates[:max(0, min(fan, room))]:
            self._sparks.append([index, other, 0.0, amplitude, kind, hop])

    def hit(self, node: int, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"kind: expected {READ!r} or {WRITE!r}, got {kind!r}")
        spec = KINDS[kind]
        amplitude = ORIGIN_AMPLITUDE * spec["scale"]
        if amplitude >= float(self.energy[node]):
            self.energy[node] = amplitude
            self.decay[node] = spec["decay"]
            self.kind_of[node] = kind
        # hop 1 takes the same falloff as every other hop; it used to take a
        # separate, steeper 0.55, which pushed hop 3 to 0.284 — under the
        # threshold at which anything is visible.
        self._emit(node, amplitude * HOP_FALLOFF, kind, 1, came_from=-1)

    def advance(self, dt: float) -> None:
        self._clock += dt

        # Advance the sparks. One that reaches its far end fires that node and
        # hands the signal on, weaker — the cascade is carried by the particles
        # rather than scheduled, so distant nodes light in sequence.
        if self._sparks:
            arrived, travelling = [], []
            for spark in self._sparks:
                spark[2] += self.speed * dt
                (arrived if spark[2] >= 1.0 else travelling).append(spark)
            self._sparks = travelling
            for index, node, _progress, amplitude, kind, hop in arrived:
                if amplitude >= float(self.energy[node]):
                    self.energy[node] = amplitude
                    self.decay[node] = KINDS[kind]["decay"]
                    self.kind_of[node] = kind
                a, b = self.graph.edges[index]
                self._emit(node, amplitude * HOP_FALLOFF,
                           kind, hop + 1, came_from=a if node == b else b)

        self.energy *= np.exp(-dt / self.decay).astype(np.float32)
        self.energy[self.energy < QUIET / 10] = 0.0

        # Random nodes stir on their own so the graph is alive at rest. These
        # never cascade — they set energy directly rather than going through
        # hit(), so an idle twinkle cannot be mistaken for activity.
        if IDLE_RATE and self.graph.n:
            for node in self._rng.integers(0, self.graph.n,
                                           self._rng.poisson(IDLE_RATE * dt)):
                if self.energy[node] < IDLE_AMPLITUDE:
                    self.energy[node] = IDLE_AMPLITUDE
                    self.decay[node] = IDLE_DECAY
                    self.kind_of[node] = READ

