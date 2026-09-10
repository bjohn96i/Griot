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

from .braille import Canvas
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


LEVELS = 5                 # 0 unlit, 1 resting/dim, 2 idle twinkle,
                           # 3 core / moderate activity, 4 a hot burst.
                           # The core sits at LEVELS - 2, not LEVELS - 1: it is
                           # drawn on every frame, so if it claimed the top
                           # level a genuinely lit note could never read as
                           # brighter than a resting scene.
CORE_RADIUS = 6.0
HOUSING_RADIUS = 10.0
HOUSING_SPOKES = 12
ARC_STEPS = 14
# How hard an in-flight spark bows toward the core. Two ring positions can
# land at nearly the same angle (adjacent indices are not adjacent angles),
# in which case the straight chord between them barely leaves the ring at
# all — this has to be strong enough that the dip reaches the interior even
# for that near-parallel case, not just for near-antipodal pairs.
ARC_BOW = 0.8


def ramp(palette: dict[str, str]) -> list[str]:
    """Level -> colour. Level 0 is never drawn."""
    return ["", palette["muted"], palette["reactor"],
            palette["accent_bright"], palette["reactor_core"]]


def _level_for(energy: float) -> int:
    if energy <= 0.01:
        return 1
    if energy < 0.35:
        return 2
    if energy < 0.75:
        return 3
    return 4


def _draw_disc(canvas: Canvas, cx: float, cy: float, radius: float, level: int) -> None:
    step = 0.5
    y = -radius
    while y <= radius:
        x = -radius
        while x <= radius:
            if x * x + y * y <= radius * radius:
                canvas.plot(cx + x, cy + y, level)
            x += step
        y += step


def _draw_ring(canvas: Canvas, cx: float, cy: float, radius: float,
               level: int, spin: float, count: int) -> None:
    for i in range(count):
        angle = spin + TWO_PI * i / count
        canvas.plot(cx + radius * math.cos(angle), cy + radius * math.sin(angle), level)


def _draw_arc(canvas: Canvas, cx: float, cy: float, ax: float, ay: float,
              bx: float, by: float, head: float, level: int) -> None:
    """A spark's flight from A to B, in polar terms around the centre rather
    than a straight Cartesian line — a chord between two similar angles would
    otherwise barely leave the outer ring no matter how much it is scaled
    toward the centre. The radius dips toward the core at the midpoint of the
    traversed arc and returns to the endpoints' own radius at either end."""
    ra, aa = math.hypot(ax - cx, ay - cy), math.atan2(ay - cy, ax - cx)
    rb, ab = math.hypot(bx - cx, by - cy), math.atan2(by - cy, bx - cx)
    delta = (ab - aa + math.pi) % TWO_PI - math.pi
    for step in range(ARC_STEPS):
        f = head * step / max(1, ARC_STEPS - 1)
        angle = aa + delta * f
        radius = (ra + (rb - ra) * f) * (1.0 - ARC_BOW * math.sin(math.pi * f))
        canvas.plot(cx + radius * math.cos(angle), cy + radius * math.sin(angle), level)


def scene(graph: Graph, pulses, rings: list[int], cols: int, rows: int,
          spin: float, core_phase: float) -> Canvas:
    """One frame. The interior is deliberately empty apart from travelling
    arcs — drawing every link as a chord is a grey wash at this size."""
    canvas = Canvas(cols, rows)
    cx, cy = canvas.width / 2.0, canvas.height / 2.0

    # housing: a dotted ring plus spokes, the machined part of the reactor
    _draw_ring(canvas, cx, cy, HOUSING_RADIUS, 1, spin, 48)
    for i in range(HOUSING_SPOKES):
        angle = spin + TWO_PI * i / HOUSING_SPOKES
        for step in range(3):
            r = HOUSING_RADIUS + step
            canvas.plot(cx + r * math.cos(angle), cy + r * math.sin(angle), 1)

    # the core: the vault itself, breathing
    breath = 0.85 + 0.15 * math.sin(core_phase)
    _draw_disc(canvas, cx, cy, CORE_RADIUS * breath, LEVELS - 2)

    # arcs for sparks in flight, from one ring position to another
    node_pos = positions(graph, rings, (cx, cy), spin)
    for edge_index, t, amplitude in pulses.sparks():
        a, b = graph.edges[edge_index]
        ax, ay = node_pos[a]
        bx, by = node_pos[b]
        head = max(0.0, min(1.0, t))
        level = 3 if amplitude >= 0.35 else 2
        _draw_arc(canvas, cx, cy, ax, ay, bx, by, head, level)

    # the notes themselves
    energy = pulses.energy
    for index, (x, y) in enumerate(node_pos):
        canvas.plot(x, y, _level_for(float(energy[index])))

    return canvas
