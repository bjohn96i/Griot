"""Arc-reactor geometry: which ring a note sits on, and where on it.

Positions are deterministic. There is no force simulation here — rings ARE
the arc reactor, and a note keeping the same place across restarts is what
lets you recognise your own vault rather than watch abstract motion.
"""
from __future__ import annotations

import hashlib
import math
import os
from collections import Counter

from .graph import Graph

# Dot radii, innermost first. A ring at radius r holds about 2*pi*r dot
# positions, which is why the largest folders are placed furthest out.
RING_RADII = (16.0, 24.0, 32.0, 40.0)
TWO_PI = 2.0 * math.pi


def _vault_root(paths: list[str | None]) -> str:
    """The common ancestor directory of every real note, used so `_folder`
    can read a note's *top-level* folder rather than its immediate parent.

    Built from `dirname(path)`, not `path` itself, so a vault with a single
    real note does not make that note's own directory look like the root.
    """
    dirs = [os.path.dirname(p) for p in paths if p]
    if not dirs:
        return ""
    try:
        return os.path.commonpath(dirs)
    except ValueError:
        return ""


def _folder(path: str | None, root: str) -> str:
    """Top-level folder under `root`, or "" for a phantom or a root-level note."""
    if not path or not root:
        return ""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return ""
    parts = [p for p in rel.split(os.sep) if p not in ("", ".", "..")]
    return parts[0] if len(parts) >= 2 else ""


def ring_of(graph: Graph) -> list[int]:
    """Node index -> ring index. Bigger folders go further out, where there
    is more circumference; phantoms and root notes go innermost."""
    root = _vault_root(graph.paths)
    folders = [_folder(p, root) for p in graph.paths]
    if root and not any(folders):
        # Every real note shares one top folder, so `commonpath` swallowed
        # the level we actually want. Back off once — no further retries.
        root = os.path.dirname(root)
        folders = [_folder(p, root) for p in graph.paths]
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
