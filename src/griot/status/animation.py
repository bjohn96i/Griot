"""Griot's heartbeat, four ways: beads, scope, bars, glyphs.

Every style is pure frame math — `*_frame(tick, width, height, ...)` returns a
list of rows, each a list of `(char, level)` cells — plus one thin Textual
widget that ticks a timer and paints the frame with the active theme.

Levels: 0 dim, 1 muted, 2 accent, 3 bright. `excite()` is the shared hook the
status panels call on any state change; each style interprets it its own way,
and it is also where the drive's head-seek chatter fires.
"""
from __future__ import annotations

import math
import random

from rich.text import Text
from textual.widgets import Static

from griot import sound, theme

STYLES = ("beads", "scope", "bars", "glyphs")
EXCITE_SECONDS = 10.0

DEFAULTS: dict[str, object] = {
    "style": "beads", "speed": 0.15, "width": 0, "height": 1,
    # scope
    "wavelength": 12, "amplitude": 1.0, "trail": True,
    # bars
    "bar_width": 1, "gap": 1,
    # glyphs
    "glyph_set": "mixed", "mutation_rate": 0.08, "packets": 2, "packet_length": 5,
    "seed": 0,
}

GLYPH_SETS: dict[str, str] = {
    "katakana": "ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺ",
    "blocks": "▚▞▟▙▛▜▗▖▝▘░▒▓",
    "hex": "0123456789ABCDEF",
}
GLYPH_SETS["mixed"] = (GLYPH_SETS["katakana"] + GLYPH_SETS["blocks"] + GLYPH_SETS["hex"]
                       + "╱╲╳┼")

Frame = list[list[tuple[str, int]]]


def resolve(theme_default: dict, user: dict) -> dict:
    """Effective animation config: built-in defaults < theme default < user."""
    cfg = {**DEFAULTS, **theme_default, **user}
    if cfg["style"] not in STYLES:
        raise ValueError(
            f"unknown animation style {cfg['style']!r}; choose from {', '.join(STYLES)}")
    return cfg


# ---------------------------------------------------------------- beads ----

BEAD_GLYPHS = " ○◎◉●"
_BEAD_LEVEL = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3}


def bead_intensities(tick: int, n: int = 9) -> list[int]:
    period = 2 * n - 2
    pos = tick % period
    if pos >= n:
        pos = period - pos
    return [max(0, 4 - abs(i - pos)) for i in range(n)]


def render_beads(tick: int, n: int = 9) -> str:
    return " ".join(BEAD_GLYPHS[i] if i else BEAD_GLYPHS[1] for i in bead_intensities(tick, n))


def beads_frame(tick: int, width: int, height: int = 1, **_) -> Frame:
    n = max(1, (width + 1) // 2)
    cells: list[tuple[str, int]] = []
    for i, inten in enumerate(bead_intensities(tick, n)):
        if i:
            cells.append((" ", 0))
        cells.append((BEAD_GLYPHS[max(inten, 1)], _BEAD_LEVEL[inten]))
    return [_center(cells, width)]


def _center(cells: list[tuple[str, int]], width: int) -> list[tuple[str, int]]:
    pad = max(0, width - len(cells))
    left = pad // 2
    return [(" ", 0)] * left + cells + [(" ", 0)] * (pad - left)


# ---------------------------------------------------------------- scope ----

_BRAILLE_BIT = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
                (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


def _sine_dots(tick: int, subcols: int, rows: int, wavelength: float, amplitude: float
               ) -> list[int]:
    """Dot-row index (0 = top) of the trace for each braille sub-column."""
    centre = (rows - 1) / 2
    amp = centre * max(0.0, min(1.0, amplitude))
    period = max(2.0, wavelength * 2)  # sub-columns per cycle
    return [int(round(centre - amp * math.sin(2 * math.pi * (x + tick) / period)))
            for x in range(subcols)]


def scope_frame(tick: int, width: int, height: int = 2, wavelength: float = 12,
                amplitude: float = 1.0, trail: bool = True, excited: bool = False, **_
                ) -> Frame:
    """A sine wave scrolling left, drawn in braille (2x4 dots per cell)."""
    rows, subcols = height * 4, width * 2
    if excited:
        wavelength = max(2.0, wavelength / 1.5)
    live = _sine_dots(tick, subcols, rows, wavelength, amplitude)
    ghost = _sine_dots(tick - 2, subcols, rows, wavelength, amplitude) if trail else []
    level_live = 3 if excited else 2
    frame: Frame = []
    for r in range(height):
        row: list[tuple[str, int]] = []
        for x in range(width):
            bits, level = 0, 0
            for sub in (0, 1):
                sx = x * 2 + sub
                for source, lvl in ((ghost, 1), (live, level_live)):
                    if not source:
                        continue
                    y = source[sx]
                    if r * 4 <= y < r * 4 + 4:
                        bits |= _BRAILLE_BIT[(sub, y - r * 4)]
                        level = max(level, lvl)
            row.append((chr(0x2800 + bits), level))
        frame.append(row)
    return frame


# ----------------------------------------------------------------- bars ----

BAR_GLYPHS = " ▁▂▃▄▅▆▇█"


def bar_heights(tick: int, bars: int, wavelength: float, amplitude: float, levels: int
                ) -> list[int]:
    amp = max(0.0, min(1.0, amplitude))
    period = max(2.0, wavelength)
    return [int(round((math.sin(2 * math.pi * (i + tick) / period) + 1) / 2 * amp * levels))
            for i in range(bars)]


def bars_frame(tick: int, width: int, height: int = 2, bar_width: int = 1, gap: int = 1,
               wavelength: float = 8, amplitude: float = 1.0, excited: bool = False, **_
               ) -> Frame:
    """Vertical bars whose heights follow a travelling sine; gaps between bars."""
    bar_width, gap = max(1, bar_width), max(0, gap)
    bars = max(1, (width + gap) // (bar_width + gap))
    levels = height * 8
    heights = bar_heights(tick, bars, wavelength, amplitude, levels)
    peak = max(heights)
    frame: Frame = []
    for r in range(height):
        base = (height - 1 - r) * 8
        row: list[tuple[str, int]] = []
        for i, h in enumerate(heights):
            fill = max(0, min(8, h - base))
            glyph = BAR_GLYPHS[fill]
            level = 0 if fill == 0 else (3 if (excited or h == peak) else 2)
            row.extend([(glyph, level)] * bar_width)
            if i < bars - 1:
                row.extend([(" ", 0)] * gap)
        frame.append(_center(row[:width], width))
    return frame


# --------------------------------------------------------------- glyphs ----

class GlyphStream:
    """A cyberspace data stream: cells mutate at random, bright packets travel.

    Deterministic for a given seed, so frames are testable.
    """

    def __init__(self, width: int, height: int = 1, glyph_set: str = "mixed",
                 mutation_rate: float = 0.08, packets: int = 2, packet_length: int = 5,
                 seed: int = 0) -> None:
        self.width, self.height = max(1, width), max(1, height)
        self.glyphs = GLYPH_SETS[glyph_set]
        self.mutation_rate = mutation_rate
        self.packets, self.packet_length = max(0, packets), max(1, packet_length)
        self.seed = seed
        self.ticks = 0
        rng = random.Random(seed)
        self.cells: list[list[str]] = [[rng.choice(self.glyphs) for _ in range(self.width)]
                                       for _ in range(self.height)]

    def resize(self, width: int, height: int) -> None:
        if (width, height) == (self.width, self.height):
            return
        rng = random.Random(self.seed + 7919 + self.ticks)
        rows = []
        for r in range(max(1, height)):
            old = self.cells[r] if r < len(self.cells) else []
            rows.append((old + [rng.choice(self.glyphs) for _ in range(width)])[:max(1, width)])
        self.cells, self.width, self.height = rows, max(1, width), max(1, height)

    def step(self, excited: bool = False) -> list[list[str]]:
        rate = self.mutation_rate * (3 if excited else 1)
        rng = random.Random(self.seed * 1_000_003 + self.ticks)
        for row in self.cells:
            for i in range(len(row)):
                if rng.random() < rate:
                    row[i] = rng.choice(self.glyphs)
        self.ticks += 1
        return [list(r) for r in self.cells]

    def frame(self, tick: int, excited: bool = False) -> Frame:
        packets = self.packets * (2 if excited else 1)
        span = self.width + self.packet_length
        stride = max(1, span // max(1, packets))
        levels = [[0] * self.width for _ in range(self.height)]
        flicker = random.Random(self.seed * 31 + tick)
        for r in range(self.height):
            for x in range(self.width):
                if flicker.random() < 0.03:
                    levels[r][x] = 1
        for k in range(packets):
            head = (tick + self.packet_length - 1 + k * stride) % span
            row = k % self.height
            for j in range(self.packet_length):
                x = head - j
                if 0 <= x < self.width:
                    levels[row][x] = max(levels[row][x], 3 if j == 0 else 2)
        return [[(self.cells[r][x], levels[r][x]) for x in range(self.width)]
                for r in range(self.height)]


# --------------------------------------------------------------- render ----

def _style(level: int) -> str:
    return {0: theme.BORDER, 1: theme.MUTED, 2: theme.ACCENT,
            3: f"bold {theme.ACCENT_BRIGHT}"}[level]


def render(frame: Frame) -> Text:
    text = Text(justify="center")
    for r, row in enumerate(frame):
        if r:
            text.append("\n")
        for ch, level in row:
            text.append(ch, style=_style(level))
    return text


class Animation(Static):
    """Timer-driven heartbeat widget. `excite()` for a burst on state change."""

    def __init__(self, cfg: dict, id: str | None = None) -> None:
        super().__init__("", id=id)
        self.cfg = cfg
        self.tick = 0
        self.excited = 0
        self._stream: GlyphStream | None = None

    @property
    def style_name(self) -> str:
        return str(self.cfg["style"])

    def _dims(self) -> tuple[int, int]:
        width = int(self.cfg["width"]) or (self.size.width - 2 if self.size.width > 4 else 17)
        return max(5, width), max(1, int(self.cfg["height"]))

    def on_mount(self) -> None:
        self.styles.height = self._dims()[1]
        self.set_interval(float(self.cfg["speed"]), self._advance)
        self._advance()

    def excite(self) -> None:
        self.excited = int(EXCITE_SECONDS / float(self.cfg["speed"]))
        sound.seek()   # no-op unless an engine is installed; never raises

    def _advance(self) -> None:
        hot = self.excited > 0
        self.excited = max(0, self.excited - 1)
        width, height = self._dims()
        c = self.cfg
        if self.style_name == "beads":
            self.tick += 2 if hot else 1
            frame = beads_frame(self.tick, width, height)
        elif self.style_name == "scope":
            self.tick += 1
            frame = scope_frame(self.tick, width, height, float(c["wavelength"]),
                                float(c["amplitude"]), bool(c["trail"]), hot)
        elif self.style_name == "bars":
            self.tick += 1
            frame = bars_frame(self.tick, width, height, int(c["bar_width"]), int(c["gap"]),
                               float(c["wavelength"]), float(c["amplitude"]), hot)
        else:
            if self._stream is None:
                self._stream = GlyphStream(width, height, str(c["glyph_set"]),
                                           float(c["mutation_rate"]), int(c["packets"]),
                                           int(c["packet_length"]), int(c["seed"]))
            self._stream.resize(width, height)
            self._stream.step(hot)
            self.tick += 1
            frame = self._stream.frame(self.tick, hot)
        self.update(render(frame))
