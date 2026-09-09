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
HOP_DELAY = 0.12          # seconds per hop
ELECTRONS_PER_EDGE = 1
AMBIENT_SPEED = 0.08      # fraction of an edge per second at rest
BOOST_SPEED = 0.9
QUIET = 0.01

KINDS = {
    WRITE: {"scale": 1.0, "decay": 1.4, "hops": 3},
    READ: {"scale": 0.85, "decay": 1.0, "hops": 2},
}


class Pulses:
    def __init__(self, graph: Graph, hops: int = 3) -> None:
        self.graph = graph
        self.hops = hops
        self.energy = np.zeros(graph.n, np.float32)
        self.decay = np.full(graph.n, KINDS[WRITE]["decay"], np.float32)
        self.kind_of = np.array([WRITE] * graph.n, dtype=object)
        self._pending: list[tuple[float, int, float, str]] = []   # (delay, node, amp, kind)
        self._clock = 0.0
        count = len(graph.edges) * ELECTRONS_PER_EDGE
        self._edge_of = np.repeat(np.arange(len(graph.edges)), ELECTRONS_PER_EDGE)
        self._t = (np.tile(np.arange(ELECTRONS_PER_EDGE) / ELECTRONS_PER_EDGE,
                           len(graph.edges)).astype(np.float32)
                   if count else np.zeros(0, np.float32))

    @property
    def active(self) -> bool:
        return bool(self.energy.max(initial=0.0) > QUIET) or bool(self._pending)

    def hit(self, node: int, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"kind: expected {READ!r} or {WRITE!r}, got {kind!r}")
        spec = KINDS[kind]
        limit = min(self.hops, spec["hops"])
        seen = {node}
        frontier = [node]
        for hop in range(limit):
            amplitude = HOP_AMPLITUDE[min(hop, len(HOP_AMPLITUDE) - 1)] * spec["scale"]
            if hop == 0:
                # Apply hop 0 immediately
                for target in frontier:
                    if amplitude >= float(self.energy[target]):
                        self.energy[target] = amplitude
                        self.decay[target] = KINDS[kind]["decay"]
                        self.kind_of[target] = kind
            else:
                # Schedule later hops
                for target in frontier:
                    self._pending.append(
                        (self._clock + hop * HOP_DELAY, target, amplitude, kind))
            nxt = []
            for current in frontier:
                for other in self.graph.adjacency[current]:
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break

    def advance(self, dt: float) -> None:
        self._clock += dt
        due = [p for p in self._pending if p[0] <= self._clock]
        if due:
            self._pending = [p for p in self._pending if p[0] > self._clock]
            for _, node, amplitude, kind in due:
                if amplitude >= float(self.energy[node]):
                    self.energy[node] = amplitude
                    self.decay[node] = KINDS[kind]["decay"]
                    self.kind_of[node] = kind

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
