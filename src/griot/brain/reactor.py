"""Arc-reactor geometry: which ring a note sits on, and where on it.

Positions are deterministic. There is no force simulation here — rings ARE
the arc reactor, and a note keeping the same place across restarts is what
lets you recognise your own vault rather than watch abstract motion.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter

from .graph import Graph

# Dot radii, innermost first. A ring at radius r holds about 2*pi*r dot
# positions, which is why the largest folders are placed furthest out.
RING_RADII = (16.0, 24.0, 32.0, 40.0)
TWO_PI = 2.0 * math.pi


def _folder(path: str | None) -> str:
    """Top-level folder under the vault, or "" for a phantom or a root note."""
    if not path:
        return ""
    parts = [p for p in path.split("/") if p]
    return parts[-2] if len(parts) >= 2 else ""


def ring_of(graph: Graph) -> list[int]:
    """Node index -> ring index. Bigger folders go further out, where there
    is more circumference; phantoms and root notes go innermost."""
    folders = [_folder(p) for p in graph.paths]
    sizes = Counter(f for f in folders if f)
    ranked = [f for f, _ in sizes.most_common()]
    outermost = len(RING_RADII) - 1
    # The biggest folder takes the outermost ring, the next the one inside it,
    # and everything past that shares the second ring so the small folders do
    # not each claim one.
    assignment: dict[str, int] = {}
    for position, folder in enumerate(ranked):
        assignment[folder] = max(1, outermost - position)
    return [assignment.get(f, 0) for f in folders]


def angle_of(key: str) -> float:
    """A stable angle for a path. Deliberately not `hash()`, which is salted
    per process — a note must not move when the animator restarts."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64) * TWO_PI


def positions(graph: Graph, rings: list[int], centre: tuple[float, float],
              spin: float) -> list[tuple[float, float]]:
    cx, cy = centre
    out = []
    for index in range(graph.n):
        key = graph.paths[index] or graph.names[index]
        angle = angle_of(key) + spin
        radius = RING_RADII[rings[index]]
        out.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return out
