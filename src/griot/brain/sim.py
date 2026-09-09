"""Force-directed layout, recomputed every frame.

Repulsion is short-range against a spatial grid rather than all pairs: the
3x3 neighbourhood costs ~5ms for this vault against ~27ms for the naive
O(n^2), and cell-local repulsion alone clumps at cell boundaries. The
temperature floor is load-bearing — without it the layout settles to a
low-energy plateau with minimal motion. With it, the system maintains
motion at a watchable amplitude indefinitely.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .graph import Graph

CELL = 60.0
REPULSION = 40.0
SPRING = 0.02
REST_LENGTH = 40.0
CENTERING = 0.06        # 0.01 pressed 36 nodes flat against the frame
# TEMPERATURE drives drift; measured at steady state (post-3000 frame convergence):
# 0.4 → ~0.3 px/sec (appears frozen), 20.0 → ~3.0 px/sec at 15fps (watchable float).
# Kinetic energy is wrong observable (spring energy dominates first ~1500 frames);
# mean path length distinguishes floating from frozen.
TEMPERATURE = 20.0
DAMPING = 0.85
MAX_SPEED = 40.0
# The constants above were tuned at this step. Damping is applied per step and
# the jitter is injected per step, so without correction a higher frame rate
# runs the world faster rather than drawing it more smoothly — measured 8.83
# px/sec of drift at 30fps against 4.49 at 15.
REF_DT = 1.0 / 15.0


class Sim:
    def __init__(self, graph: Graph, size: tuple[int, int], seed: int = 0) -> None:
        self.graph = graph
        self.size = size
        self.rng = np.random.default_rng(seed)
        n = graph.n
        self.pos = (self.rng.random((n, 2)) * size).astype(np.float32)
        self.vel = np.zeros((n, 2), np.float32)
        # inv_mass scales by 1/degree (not 1/sqrt): hubs have ~60x lower mass than
        # leaves on a 60-node star, which is necessary to keep hubs from moving
        # 3.6x more than leaves. sqrt alone is insufficient under actual forces.
        self.inv_mass = (1.0 / np.maximum(graph.degree, 1, dtype=np.float32)
                         ).astype(np.float32)
        if graph.edges:
            e = np.asarray(graph.edges, np.int32)
            self.ea, self.eb = e[:, 0], e[:, 1]
        else:
            self.ea = self.eb = np.zeros(0, np.int32)

    def kinetic_energy(self) -> float:
        return float((self.vel * self.vel).sum())

    def impulse(self, node: int, strength: float) -> None:
        """Shove a node's neighbours outward — a write disturbs its region."""
        for other in self.graph.adjacency[node]:
            delta = self.pos[other] - self.pos[node]
            norm = float(np.linalg.norm(delta)) or 1.0
            self.vel[other] += (delta / norm) * strength * self.inv_mass[other]

    def _repel(self) -> np.ndarray:
        force = np.zeros_like(self.pos)
        cells = np.floor(self.pos / CELL).astype(np.int32)
        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (cx, cy) in enumerate(cells):
            buckets[(int(cx), int(cy))].append(i)
        for (cx, cy), members in buckets.items():
            neighbours: list[int] = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbours.extend(buckets.get((cx + dx, cy + dy), ()))
            if len(neighbours) < 2:
                continue
            idx = np.asarray(members, np.int32)
            near = np.asarray(neighbours, np.int32)
            delta = self.pos[idx][:, None, :] - self.pos[near][None, :, :]
            dist2 = (delta * delta).sum(-1) + 1e-3
            force[idx] = (delta / dist2[..., None]).sum(1) * REPULSION
        return force

    def step(self, dt: float = REF_DT) -> None:
        force = self._repel()

        if self.ea.size:
            span = self.pos[self.eb] - self.pos[self.ea]
            length = np.linalg.norm(span, axis=1, keepdims=True) + 1e-6
            pull = span * (SPRING * (length - REST_LENGTH) / length)
            np.add.at(force, self.ea, pull)
            np.add.at(force, self.eb, -pull)

        force -= (self.pos - self.pos.mean(0)) * CENTERING
        # Random-walk variance accumulates as steps * (T*dt)^2, so holding the
        # per-second amplitude fixed means scaling T by sqrt(REF_DT / dt).
        pace = dt / REF_DT
        force += self.rng.normal(0.0, TEMPERATURE / np.sqrt(pace), self.pos.shape)

        self.vel = (self.vel + force * self.inv_mass[:, None] * dt) * (DAMPING ** pace)
        # +eps because np.where evaluates both branches, and a resting node
        # has speed 0 — the discarded branch would still emit a divide warning.
        speed = np.linalg.norm(self.vel, axis=1, keepdims=True) + 1e-9
        too_fast = speed > MAX_SPEED
        self.vel = np.where(too_fast, self.vel / speed * MAX_SPEED, self.vel)
        self.pos = self.pos + self.vel * dt

        width, height = self.size
        self.pos[:, 0] = np.clip(self.pos[:, 0], 0, width)
        self.pos[:, 1] = np.clip(self.pos[:, 1], 0, height)
        self.pos = self.pos.astype(np.float32)
        self.vel = self.vel.astype(np.float32)
