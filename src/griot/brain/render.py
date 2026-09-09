"""One frame of the brain, as PNG bytes.

compress_level=1 rather than Pillow's default 6: it costs ~8ms less per frame
and the bytes go straight down a unix socket, so the size never matters.
Colours are theme tokens only — `outline` rather than `border` for edges,
because Dataterm's border is black and would render every edge invisible
against its own background.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from .graph import Graph
from .pulse import READ, Pulses
from .sim import Sim

BASE_RADIUS = 0.9
DEGREE_RADIUS = 0.55
PULSE_RADIUS = 10.0
ELECTRON_RADIUS = 0.8
ELECTRON_GROWTH = 1.6
EDGE_DIM = 0.55
# Edges brighten with the energy at their ends. Without this the wave lit the
# nodes and left the links between them flat, so a pulse read as dots blinking
# rather than something travelling along the connections.
EDGE_RAMP_STEPS = 16
# How far a resting node is faded toward the background. Without this the
# ambient field is as bright as a pulse, so a firing node's peak brightness was
# 1.00x its resting peak — no contrast at all, which is why reads could not be
# seen however large the pulse got. At 0.55 the same read reads 1.47x.
AMBIENT_DIM = 0.55

# Radii are quoted against this width and scaled to whatever canvas is in use,
# so changing `size` changes sharpness rather than how big anything looks.
REFERENCE_WIDTH = 900.0
# The layout fills its box by construction; this pulls it in off the edges.
VIEW_SCALE = 0.88
# Electrons ride in `electron`, a cool blue-white that is deliberately a
# different substance from the nodes rather than a warmer shade of them —
# gold electrons on gold nodes read as one texture. ELECTRON_DIM is how far
# the coldest electron is faded toward the background.
ELECTRON_DIM = 0.6
# A straight trade, measured on a 1400x875 frame with identical sim state:
#   level 0  19.0ms  3590 KB
#   level 1  22.2ms   393 KB
#   level 2  23.5ms   239 KB
#   level 4  27.6ms   196 KB
# Level 1: tried level 2 live and kitty's CPU barely moved (67.5% -> 63.9%,
# inside the noise) while ours rose, so its cost is texture upload rather than
# PNG decode. Fewer bytes buy nothing here; keep the cheapest encode.
PNG_COMPRESS = 1
ELECTRON_RAMP_STEPS = 32
PHANTOM_RADIUS_SCALE = 0.7


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def blend(a: str, b: str, t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    ca, cb = _rgb(a), _rgb(b)
    return tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))


def frame(graph: Graph, sim: Sim, pulses: Pulses,
          palette: dict[str, str], size: tuple[int, int]) -> bytes:
    img = Image.new("RGB", size, _rgb(palette["bg"]))
    draw = ImageDraw.Draw(img)
    scale = size[0] / REFERENCE_WIDTH
    cx, cy = size[0] / 2.0, size[1] / 2.0
    pos = [((x - cx) * VIEW_SCALE + cx, (y - cy) * VIEW_SCALE + cy)
           for x, y in sim.pos.tolist()]
    energy = pulses.energy

    # 2,523 edges at full strength read as a grey wash over the text, so the
    # resting colour is dimmed — but an edge whose ends are lit glows toward
    # the electron colour, the same hue as the traffic riding it.
    cold_edge = blend(palette["outline"], palette["bg"], EDGE_DIM)
    lit_edge = _rgb(palette["electron"])
    edge_ramp = [tuple(int(cold_edge[c] + (lit_edge[c] - cold_edge[c]) * (i / (EDGE_RAMP_STEPS - 1)))
                       for c in range(3))
                 for i in range(EDGE_RAMP_STEPS)]
    if graph.edges:
        ends = np.asarray(graph.edges, np.int32)
        heat = np.maximum(energy[ends[:, 0]], energy[ends[:, 1]])
        shade = (np.clip(heat, 0.0, 1.0) * (EDGE_RAMP_STEPS - 1)).astype(np.int32)
        for (a, b), step in zip(graph.edges, shade.tolist()):
            draw.line([tuple(pos[a]), tuple(pos[b])], fill=edge_ramp[step])

    hot = _rgb(palette["electron"])
    back = _rgb(palette["bg"])
    cold = tuple(int(back[i] + (hot[i] - back[i]) * (1.0 - ELECTRON_DIM)) for i in range(3))
    ramp = [tuple(int(cold[i] + (hot[i] - cold[i]) * (step / (ELECTRON_RAMP_STEPS - 1)))
                  for i in range(3))
            for step in range(ELECTRON_RAMP_STEPS)]

    for edge_index, t, hot in pulses.electrons():
        a, b = graph.edges[edge_index]
        ax, ay = pos[a]
        bx, by = pos[b]
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        r = (ELECTRON_RADIUS + ELECTRON_GROWTH * hot) * scale
        colour = ramp[int(max(0.0, min(1.0, hot)) * (ELECTRON_RAMP_STEPS - 1))]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    muted, accent, bright = palette["muted"], palette["accent"], palette["accent_bright"]
    ambient_node = blend(muted, palette["bg"], AMBIENT_DIM)
    # Reads flash in the electron blue-white, not `secondary`. Measured against
    # the hub with kitty's 0.85 tint applied: rust lifted the neighbourhood
    # 2.1%, which is invisible, because it is DARKER than the ambient gold.
    # Blue-white lifts it 15-20% and stays distinct from a write's warm gold.
    secondary = palette["electron"]
    for i, (x, y) in enumerate(pos):
        e = float(energy[i])
        r = (BASE_RADIUS + DEGREE_RADIUS * (graph.degree[i] ** 0.5) + PULSE_RADIUS * e) * scale
        if e > 0.0:
            hot = secondary if pulses.kind_of[i] == READ else bright
            # Ramp from the resting colour, not from `accent`: starting at a
            # bright token made even a trace of energy jump to full brightness,
            # so the ramp was not monotonic and the bloom had no run-up.
            colour = blend_rgb(ambient_node, _rgb(hot), e)
        else:
            colour = ambient_node
        if graph.paths[i] is None:
            pr = r * PHANTOM_RADIUS_SCALE
            box = [x - pr, y - pr, x + pr, y + pr]
            draw.ellipse(box, outline=colour)     # phantom: a ring, never filled
        else:
            box = [x - r, y - r, x + r, y + r]
            draw.ellipse(box, fill=colour)

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=PNG_COMPRESS)
    return buf.getvalue()
