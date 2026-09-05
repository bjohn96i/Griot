"""Kimoyo bead pulse — Griot's heartbeat. Pure frame math + a thin widget."""
from rich.text import Text
from textual.widgets import Static

from griot import theme

GLYPHS = " ○◎◉●"
NORMAL_INTERVAL = 0.15
EXCITED_TICKS = 67  # ~10s at 0.15s/tick


def bead_intensities(tick: int, n: int = 9) -> list[int]:
    period = 2 * n - 2
    pos = tick % period
    if pos >= n:
        pos = period - pos
    return [max(0, 4 - abs(i - pos)) for i in range(n)]


def render_beads(tick: int, n: int = 9) -> str:
    return " ".join(GLYPHS[i] if i else GLYPHS[1] for i in bead_intensities(tick, n))


class Beads(Static):
    def __init__(self, id: str | None = None) -> None:
        super().__init__("", id=id)
        self.tick = 0
        self.excited = 0

    def on_mount(self) -> None:
        self.set_interval(NORMAL_INTERVAL, self._advance)

    def excite(self) -> None:
        self.excited = EXCITED_TICKS

    def _advance(self) -> None:
        step = 2 if self.excited > 0 else 1
        self.excited = max(0, self.excited - 1)
        self.tick += step
        style = theme.GOLD_BRIGHT if self.excited else theme.GOLD
        self.update(Text(render_beads(self.tick), style=style, justify="center"))
