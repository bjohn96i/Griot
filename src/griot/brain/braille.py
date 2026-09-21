"""A braille dot canvas.

Braille packs 2 dots across and 4 down into one character, so a 43x22 block
of cells addresses 86x88 dots — and because a braille dot is roughly 4.5 x
4.75 real pixels, that canvas is very nearly square.

Colour is the catch: a cell is one glyph and carries one style, so dot
resolution and colour resolution differ by the same 2x4. A cell takes the
highest level plotted into it.
"""
from __future__ import annotations

from rich.text import Text

# Braille bit per (dy, dx) within a cell. The fourth row is the two extra
# dots added for 8-dot braille and is not contiguous with the first three.
BITS = ((0x01, 0x08),
        (0x02, 0x10),
        (0x04, 0x20),
        (0x40, 0x80))
BRAILLE_BASE = 0x2800


class Canvas:
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = max(1, cols)
        self.rows = max(1, rows)
        self.width = self.cols * 2
        self.height = self.rows * 4
        self.clear()

    def clear(self) -> None:
        self._bits = [[0] * self.cols for _ in range(self.rows)]
        self._level = [[0] * self.cols for _ in range(self.rows)]

    def plot(self, x: float, y: float, level: int) -> None:
        if level <= 0:
            return
        xi, yi = int(x), int(y)
        if not (0 <= xi < self.width and 0 <= yi < self.height):
            return
        col, row = xi // 2, yi // 4
        self._bits[row][col] |= BITS[yi % 4][xi % 2]
        if level > self._level[row][col]:
            self._level[row][col] = level

    def render(self, colours: list[str]) -> Text:
        out = Text()
        top = len(colours) - 1
        for row in range(self.rows):
            if row:
                out.append("\n")
            for col in range(self.cols):
                bits = self._bits[row][col]
                if not bits:
                    out.append(" ")
                    continue
                level = min(self._level[row][col], top)
                out.append(chr(BRAILLE_BASE + bits), style=colours[level])
        return out
