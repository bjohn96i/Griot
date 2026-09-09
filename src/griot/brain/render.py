"""One frame of the brain, as PNG bytes.

compress_level=1 rather than Pillow's default 6: it costs ~8ms less per frame
and the bytes go straight down a unix socket, so the size never matters.
Colours are theme tokens only — `outline` rather than `border` for edges,
because Dataterm's border is black and would render every edge invisible
against its own background.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from .graph import Graph
from .pulse import READ, Pulses
from .sim import Sim

BASE_RADIUS = 1.6
DEGREE_RADIUS = 1.1
PULSE_RADIUS = 5.0
ELECTRON_RADIUS = 1.4
ELECTRON_GROWTH = 2.6


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend(a: str, b: str, t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    ca, cb = _rgb(a), _rgb(b)
    return tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))


def frame(graph: Graph, sim: Sim, pulses: Pulses,
          palette: dict[str, str], size: tuple[int, int]) -> bytes:
    img = Image.new("RGB", size, _rgb(palette["bg"]))
    draw = ImageDraw.Draw(img)
    pos = sim.pos.tolist()
    energy = pulses.energy

    edge_colour = _rgb(palette["outline"])
    for a, b in graph.edges:
        draw.line([tuple(pos[a]), tuple(pos[b])], fill=edge_colour)

    for edge_index, t, hot in pulses.electrons():
        a, b = graph.edges[edge_index]
        ax, ay = pos[a]
        bx, by = pos[b]
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        r = ELECTRON_RADIUS + ELECTRON_GROWTH * hot
        colour = blend(palette["muted"], palette["accent_bright"], hot)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    muted, accent, bright = palette["muted"], palette["accent"], palette["accent_bright"]
    secondary = palette["secondary"]
    for i, (x, y) in enumerate(pos):
        e = float(energy[i])
        r = BASE_RADIUS + DEGREE_RADIUS * (graph.degree[i] ** 0.5) + PULSE_RADIUS * e
        if e > 0.0:
            hot = secondary if pulses.kind_of[i] == READ else bright
            colour = blend(accent, hot, e)
        else:
            colour = _rgb(muted)
        box = [x - r, y - r, x + r, y + r]
        if graph.paths[i] is None:
            draw.ellipse(box, outline=colour)     # phantom: a ring, never filled
        else:
            draw.ellipse(box, fill=colour)

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()
