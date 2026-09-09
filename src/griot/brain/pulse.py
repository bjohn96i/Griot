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

HOP_AMPLITUDE = (1.0, 0.55, 0.30)
# A hop is carried by a spark travelling the connection, not by a timer: the
# old fixed delay lit every neighbour of a hub simultaneously, which reads as a
# ring flashing on rather than a signal propagating.
SPARK_SPEED = 2.6         # edges per second
SPARK_FANOUT = 3          # onward connections a spark lights from where it lands
SPARK_FIRST_FANOUT = 24   # from the originating node; a degree-134 hub would
                          # otherwise spawn 134 sparks and then thousands
MAX_SPARKS = 500
ELECTRONS_PER_EDGE = 1
AMBIENT_SPEED = 0.08      # fraction of an edge per second at rest
BOOST_SPEED = 0.9
QUIET = 0.01

KINDS = {
    WRITE: {"scale": 1.0, "decay": 0.75, "hops": 5},
    READ: {"scale": 0.85, "decay": 0.55, "hops": 5},
}


class Pulses:
    def __init__(self, graph: Graph, hops: int = 3) -> None:
        self.graph = graph
        self.hops = hops
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
        count = len(graph.edges) * ELECTRONS_PER_EDGE
        self._edge_of = np.repeat(np.arange(len(graph.edges)), ELECTRONS_PER_EDGE)
        self._t = (np.tile(np.arange(ELECTRONS_PER_EDGE) / ELECTRONS_PER_EDGE,
                           len(graph.edges)).astype(np.float32)
                   if count else np.zeros(0, np.float32))

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
        fan = SPARK_FIRST_FANOUT if hop == 1 else SPARK_FANOUT
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
        amplitude = HOP_AMPLITUDE[0] * spec["scale"]
        if amplitude >= float(self.energy[node]):
            self.energy[node] = amplitude
            self.decay[node] = spec["decay"]
            self.kind_of[node] = kind
        self._emit(node, HOP_AMPLITUDE[1] * spec["scale"], kind, 1, came_from=-1)

    def advance(self, dt: float) -> None:
        self._clock += dt

        # Advance the sparks. One that reaches its far end fires that node and
        # hands the signal on, weaker — the cascade is carried by the particles
        # rather than scheduled, so distant nodes light in sequence.
        if self._sparks:
            arrived, travelling = [], []
            for spark in self._sparks:
                spark[2] += SPARK_SPEED * dt
                (arrived if spark[2] >= 1.0 else travelling).append(spark)
            self._sparks = travelling
            for index, node, _progress, amplitude, kind, hop in arrived:
                if amplitude >= float(self.energy[node]):
                    self.energy[node] = amplitude
                    self.decay[node] = KINDS[kind]["decay"]
                    self.kind_of[node] = kind
                a, b = self.graph.edges[index]
                self._emit(node, amplitude * (HOP_AMPLITUDE[2] / HOP_AMPLITUDE[1]),
                           kind, hop + 1, came_from=a if node == b else b)

        self.energy *= np.exp(-dt / self.decay).astype(np.float32)
        self.energy[self.energy < QUIET / 10] = 0.0

        if self._t.size:
            self._t = (self._t + self._edge_speed() * dt) % 1.0

    def _edge_speed(self) -> np.ndarray:
        if not self.graph.edges:
            return np.zeros(0, np.float32)
        e = np.asarray(self.graph.edges, np.int32)
        hot = np.maximum(self.energy[e[:, 0]], self.energy[e[:, 1]])
        return (AMBIENT_SPEED + BOOST_SPEED * hot)[self._edge_of]

    def electrons(self) -> list[tuple[int, float, float]]:
        if not self._t.size:
            return []
        e = np.asarray(self.graph.edges, np.int32)
        hot = np.maximum(self.energy[e[:, 0]], self.energy[e[:, 1]])[self._edge_of]
        return [(int(edge), float(t), float(b))
                for edge, t, b in zip(self._edge_of, self._t, hot)]
