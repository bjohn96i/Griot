# Griot Reactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the vault as an arc-reactor synapse map in the bottom of griot's right pane — notes as points on concentric rings, the vault as a glowing core, lighting up as Claude reads, writes and creates notes.

**Architecture:** A Textual widget on a timer, rendering braille into 43x22 cells. Ring positions are deterministic from folder and path hash, so no force simulation. The graph, pulse and event-spool modules carry over from the kitty build unchanged; the PIL renderer, kitty client, detached animator and force simulation are deleted.

**Tech Stack:** Python 3.13, uv, Textual, Rich, numpy. No new dependencies.

**Spec:** `docs/design/2026-09-09-reactor-design.md`

## Global Constraints

- Python `>=3.13`; `uv` is the package manager; run tests with `uv run pytest` and report the plain invocation's result.
- macOS only, consistent with the rest of griot.
- **Terminal-agnostic.** Nothing may depend on a specific terminal emulator. That is the entire reason this replaces the kitty background.
- No hex colour literals outside `src/griot/theme.py`. `tests/test_theme.py` reads `theme.TOKENS`, so new tokens are covered automatically.
- Follow the house config pattern: `Config` carries a raw dict, the owning module has `resolve()` that validates. `src/griot/sound.py` is the reference.
- Feature is opt-in: `[brain].enabled` defaults to `false`.
- `bin/griot-disk` is NOT touched by this plan. It already spools `<epoch> <read|write> <abs path>` and runs on every Claude tool call.
- Branch: `feat/brain-background` (continues from the kitty work). Do not push; Johnathan reviews and merges.
- After any edit-and-restore experiment, run `find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} +` before re-running. A stale `.pyc` produced a phantom failure during the previous build.
- Never use `git checkout --` to undo a probe on a file with uncommitted work — it reverts to the last commit and discards it. Copy the file aside instead. This cost real work twice in the previous build.

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `src/griot/brain/braille.py` | dot canvas: plot points, resolve one colour per cell, render to Rich `Text` |
| `src/griot/brain/reactor.py` | geometry (folder→ring, path→angle) and scene assembly into a frame |
| `src/griot/brain/births.py` | periodic vault rescan, new-path detection, write suppression |
| `src/griot/status/reactor_widget.py` | the Textual widget on a timer |
| `tests/test_braille.py`, `tests/test_reactor.py`, `tests/test_births.py` | one per unit |

**Modify:** `src/griot/theme.py` (two tokens x three themes), `src/griot/brain/settings.py` (config keys), `src/griot/griot.tcss` (widget height), `src/griot/status/app.py` (mount it), `config.example.toml`, `README.md`.

**Delete:** `src/griot/brain/render.py`, `kitty.py`, `app.py`, `sim.py`, their tests, the `griot-brain` console script, and the launcher wiring in `bin/griot`.

---

### Task 1: Reactor theme tokens

**Files:**
- Modify: `src/griot/theme.py`
- Test: `tests/test_theme.py` (should need no change — confirm)

**Interfaces:**
- Consumes: nothing.
- Produces: `theme.PALETTE["reactor"]` and `theme.PALETTE["reactor_core"]` in all three themes; `theme.REACTOR` / `theme.REACTOR_CORE` module constants via the existing `_apply()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_theme.py`:

```python
def test_the_reactor_core_is_the_brightest_token_in_every_theme():
    """The core is the focal point of the widget; if a theme's core is dimmer
    than its own accent, the reactor reads as a hole rather than a source."""
    def luminance(hex_colour: str) -> float:
        r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    for name, spec in theme.THEMES.items():
        colours = spec["colors"]
        assert luminance(colours["reactor_core"]) > luminance(colours["accent_bright"]), name
        assert luminance(colours["reactor_core"]) > luminance(colours["reactor"]), name
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_theme.py -v`
Expected: FAIL with `KeyError: 'reactor_core'`.

- [ ] **Step 3: Add the tokens**

In `src/griot/theme.py`, add to the `TOKENS` tuple after `"secondary", "electron",`:

```python
          "reactor", "reactor_core",
```

and to each theme's `colors` dict:

```python
# vibranium-night
            "reactor": "#7FD4FF", "reactor_core": "#EAF6FF",
# vaporwave-mono
            "reactor": "#01CDFE", "reactor_core": "#F2FBFF",
# dataterm
            "reactor": "#FFC061", "reactor_core": "#FFF6E0",
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_theme.py -v`
Expected: PASS, including the pre-existing `test_every_theme_has_every_token_as_hex` and `test_css_variables_cover_every_token`, which read `theme.TOKENS` and so pick the new tokens up without modification.

- [ ] **Step 5: Commit**

```bash
git add src/griot/theme.py tests/test_theme.py
git commit -m "theme: reactor and reactor_core tokens"
```

---

### Task 2: Braille canvas

**Files:**
- Create: `src/griot/brain/braille.py`
- Test: `tests/test_braille.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Canvas(cols: int, rows: int)` with attributes `cols`, `rows`, `width` (= cols*2), `height` (= rows*4), methods `plot(x: float, y: float, level: int) -> None`, `clear() -> None`, and `render(colours: list[str]) -> rich.text.Text` where `colours[level]` is a hex string. Level 0 means "not lit" and is never drawn.

Braille cells pack 2 dots across and 4 down, so a 43x22 block addresses 86x88 dots. Colour, however, is per *cell* — one glyph, one style. A cell takes the highest level plotted in it.

- [ ] **Step 1: Write the failing test**

```python
"""The braille dot canvas: 2x4 dots per cell, one colour per cell."""
import pytest
from rich.text import Text

from griot.brain.braille import Canvas


def test_dot_resolution_is_two_by_four_per_cell():
    c = Canvas(10, 5)
    assert (c.width, c.height) == (20, 20)


def test_a_plotted_dot_lights_exactly_one_cell():
    c = Canvas(4, 2)
    c.plot(0, 0, 1)
    text = c.render(["", "#FF0000"])
    assert text.plain[0] == "⠁", "top-left dot is braille bit 1"
    assert text.plain[1] == " ", "neighbouring cells stay blank"


def test_all_eight_dots_in_a_cell_fill_it():
    c = Canvas(1, 1)
    for x in range(2):
        for y in range(4):
            c.plot(x, y, 1)
    assert c.render(["", "#FF0000"]).plain[0] == "⣿", "every bit set"


def test_a_cell_takes_the_brightest_level_plotted_in_it():
    c = Canvas(1, 1)
    c.plot(0, 0, 1)
    c.plot(1, 0, 3)
    text = c.render(["", "#111111", "#222222", "#333333"])
    assert str(text.spans[0].style).lower().endswith("333333"), \
        "colour is per cell, so the cell must take the brighter of the two"


def test_dots_outside_the_canvas_are_dropped_not_wrapped():
    c = Canvas(2, 1)
    for x, y in ((-1, 0), (0, -1), (99, 0), (0, 99)):
        c.plot(x, y, 1)
    assert c.render(["", "#FF0000"]).plain.strip() == "", "nothing should be drawn"


def test_level_zero_draws_nothing():
    c = Canvas(2, 1)
    c.plot(0, 0, 0)
    assert c.render(["", "#FF0000"]).plain.strip() == ""


def test_render_returns_one_line_per_row():
    c = Canvas(6, 3)
    assert len(c.render(["", "#FF0000"]).plain.split("\n")) == 3


def test_clear_resets_the_canvas():
    c = Canvas(2, 1)
    c.plot(0, 0, 2)
    c.clear()
    assert c.render(["", "#111111", "#222222"]).plain.strip() == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_braille.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.braille'`.

- [ ] **Step 3: Write the canvas**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_braille.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/griot/brain/braille.py tests/test_braille.py
git commit -m "brain: braille dot canvas"
```

---

### Task 3: Ring geometry

**Files:**
- Create: `src/griot/brain/reactor.py`
- Test: `tests/test_reactor.py`

**Interfaces:**
- Consumes: `griot.brain.graph.Graph` — fields `names`, `paths` (absolute path strings, `None` for phantoms), `degree`, `n`.
- Produces: `RING_RADII: tuple[float, ...]`, `ring_of(graph) -> list[int]` (node index → ring index 0..3, innermost first), `angle_of(key: str) -> float` (radians, stable), `positions(graph, rings, centre, spin) -> list[tuple[float, float]]` (dot coordinates).

The vault's folders are lopsided — Swish Analytics 428 files, Tech Library 378, everything else 232 — so rings are assigned by folder size, biggest to the outermost ring where the circumference is largest.

- [ ] **Step 1: Write the failing test**

```python
"""Ring assignment and angular placement. The load-bearing property is that
a note's angle never moves — that is what makes the vault recognisable."""
import math

import pytest

from griot.brain import graph as g
from griot.brain.reactor import RING_RADII, angle_of, positions, ring_of


def vault_graph(folders: dict[str, int]):
    names, paths = [], []
    for folder, count in folders.items():
        for i in range(count):
            names.append(f"{folder}-{i}")
            paths.append(f"/vault/{folder}/note{i}.md")
    n = len(names)
    return g.Graph(names=names, paths=paths, edges=[], degree=[0] * n,
                   by_path={p: i for i, p in enumerate(paths)},
                   adjacency=[[] for _ in range(n)], fingerprint="test")


def test_the_biggest_folder_takes_the_outermost_ring():
    graph = vault_graph({"Big": 400, "Medium": 100, "Small": 10})
    rings = ring_of(graph)
    big = rings[graph.names.index("Big-0")]
    small = rings[graph.names.index("Small-0")]
    assert big > small, "more notes means further out, where the circumference is"
    assert big == len(RING_RADII) - 1


def test_every_node_lands_on_a_real_ring():
    graph = vault_graph({"A": 5, "B": 5})
    assert all(0 <= r < len(RING_RADII) for r in ring_of(graph))


def test_phantoms_go_to_the_innermost_ring():
    """Phantoms have no file and no folder, so they have no natural home."""
    graph = g.Graph(names=["real", "ghost"], paths=["/vault/A/real.md", None],
                    edges=[], degree=[0, 0], by_path={"/vault/A/real.md": 0},
                    adjacency=[[], []], fingerprint="test")
    assert ring_of(graph)[1] == 0


def test_the_same_path_always_gets_the_same_angle():
    """Stability across processes is the point: a note keeps its place."""
    a = angle_of("/vault/Swish Analytics/SAPI Caching.md")
    b = angle_of("/vault/Swish Analytics/SAPI Caching.md")
    assert a == b
    assert 0.0 <= a < 2 * math.pi


def test_different_paths_get_different_angles():
    angles = {angle_of(f"/vault/note{i}.md") for i in range(200)}
    assert len(angles) > 150, "hashing should spread notes around the ring"


def test_angles_do_not_depend_on_python_hash_randomisation():
    """`hash()` is salted per process; a note must not move between runs."""
    import subprocess, sys
    code = ("from griot.brain.reactor import angle_of;"
            "print(f'{angle_of(\"/vault/x.md\"):.12f}')")
    runs = {subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
                           ).stdout.strip()
            for seed in ("0", "1", "12345")}
    assert len(runs) == 1, f"angle changed with the hash seed: {runs}"


def test_positions_land_inside_the_canvas():
    graph = vault_graph({"A": 50})
    pos = positions(graph, ring_of(graph), centre=(43.0, 44.0), spin=0.0)
    assert len(pos) == graph.n
    for x, y in pos:
        assert 0 <= x <= 86 and 0 <= y <= 88


def test_spin_rotates_every_node_by_the_same_angle():
    graph = vault_graph({"A": 20})
    rings = ring_of(graph)
    a = positions(graph, rings, centre=(43.0, 44.0), spin=0.0)
    b = positions(graph, rings, centre=(43.0, 44.0), spin=math.pi / 2)
    assert a != b
    def radius(p):
        return round(math.hypot(p[0] - 43.0, p[1] - 44.0), 6)
    assert [radius(p) for p in a] == [radius(p) for p in b], \
        "rotation must not change any radius"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.reactor'`.

- [ ] **Step 3: Write the geometry**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Check it against the real vault**

```bash
uv run python -c "
from pathlib import Path
from collections import Counter
from griot.brain import graph as gm, settings
from griot.brain.reactor import RING_RADII, ring_of
import math
g = gm.load_or_build(Path.home() / 'Library/Mobile Documents/iCloud~md~obsidian/Documents/MindVault', settings.GRAPH_CACHE)
rings = ring_of(g)
for ring, count in sorted(Counter(rings).items()):
    capacity = int(2 * math.pi * RING_RADII[ring])
    print(f'ring {ring} r={RING_RADII[ring]:>4}  {count:>4} notes  {capacity:>4} positions  '
          f'{count/capacity:.1f} notes/dot')
"
```

Expected: four rings, the outermost carrying the most notes, and every ring under about 2.0 notes/dot. Anything above 3.0 means the ring assignment is crowding and should be reported, not tuned away silently.

- [ ] **Step 6: Commit**

```bash
git add src/griot/brain/reactor.py tests/test_reactor.py
git commit -m "brain: deterministic ring geometry for the reactor"
```

---

### Task 4: The scene

**Files:**
- Modify: `src/griot/brain/reactor.py`
- Test: `tests/test_reactor.py`

**Interfaces:**
- Consumes: `Canvas` from Task 2, `ring_of`/`positions` from Task 3, `griot.brain.pulse.Pulses` (`energy` array, `kind_of`, `sparks()` yielding `(edge_index, t, amplitude)`).
- Produces: `LEVELS: int`, `scene(graph, pulses, rings, cols, rows, spin, core_phase) -> Canvas` and `ramp(palette: dict[str, str]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reactor.py`:

```python
def test_the_core_is_drawn_at_the_centre():
    from griot.brain.pulse import Pulses
    from griot.brain.reactor import scene
    graph = vault_graph({"A": 20})
    canvas = scene(graph, Pulses(graph), ring_of(graph), cols=43, rows=22,
                   spin=0.0, core_phase=0.0)
    text = canvas.render(["", "#111111", "#222222", "#333333"]).plain
    middle = text.split("\n")[len(text.split("\n")) // 2]
    assert middle.strip(), "the middle row must contain the core"


def test_the_interior_is_empty_at_rest_and_busy_during_a_cascade():
    """Links are not drawn as chords: at 86x88 dots that is a grey wash. An
    arc across the disc must only ever mean something is happening."""
    from griot.brain.pulse import Pulses, WRITE
    from griot.brain.reactor import scene
    names = [f"N{i}" for i in range(30)]
    paths = [f"/vault/A/n{i}.md" for i in range(30)]
    edges = [(i, i + 1) for i in range(29)]
    adjacency = [[] for _ in range(30)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    graph = g.Graph(names=names, paths=paths, edges=edges,
                    degree=[len(x) for x in adjacency],
                    by_path={p: i for i, p in enumerate(paths)},
                    adjacency=adjacency, fingerprint="test")

    def interior_dots(pulses):
        canvas = scene(graph, pulses, ring_of(graph), cols=43, rows=22,
                       spin=0.0, core_phase=0.0)
        lit = 0
        for row in range(canvas.rows):
            for col in range(canvas.cols):
                dx, dy = col * 2 - 43, row * 4 - 44
                if 10 < (dx * dx + dy * dy) ** 0.5 < 15 and canvas._bits[row][col]:
                    lit += 1
        return lit

    quiet = Pulses(graph, hops=5)
    firing = Pulses(graph, hops=5)
    firing.positions = None
    firing.hit(0, WRITE)
    firing.advance(0.3)
    assert interior_dots(firing) > interior_dots(quiet), \
        "a travelling cascade should put arcs across the empty interior"


def test_a_lit_note_is_brighter_than_a_resting_one():
    from griot.brain.pulse import Pulses, WRITE
    from griot.brain.reactor import LEVELS, scene
    graph = vault_graph({"A": 20})
    rings = ring_of(graph)
    quiet = scene(graph, Pulses(graph), rings, 43, 22, 0.0, 0.0)
    pulses = Pulses(graph)
    pulses.hit(0, WRITE)
    hot = scene(graph, pulses, rings, 43, 22, 0.0, 0.0)
    assert max(map(max, hot._level)) > max(map(max, quiet._level))
    assert max(map(max, hot._level)) <= LEVELS - 1


def test_the_frame_matches_the_requested_size():
    from griot.brain.pulse import Pulses
    from griot.brain.reactor import ramp, scene
    from griot import theme
    graph = vault_graph({"A": 10})
    canvas = scene(graph, Pulses(graph), ring_of(graph), cols=30, rows=10,
                   spin=0.0, core_phase=0.0)
    lines = canvas.render(ramp(theme.PALETTE)).plain.split("\n")
    assert len(lines) == 10
    assert all(len(line) <= 30 for line in lines)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: FAIL — `ImportError: cannot import name 'scene'`.

- [ ] **Step 3: Write the scene**

Append to `src/griot/brain/reactor.py`:

```python
LEVELS = 5                 # 0 unlit, 1 dim ring, 2..3 active, 4 core
CORE_RADIUS = 6.0
HOUSING_RADIUS = 10.0
HOUSING_SPOKES = 12
ARC_STEPS = 14


def ramp(palette: dict[str, str]) -> list[str]:
    """Level -> colour. Level 0 is never drawn."""
    return ["", palette["muted"], palette["reactor"],
            palette["accent_bright"], palette["reactor_core"]]


def _level_for(energy: float) -> int:
    if energy <= 0.01:
        return 1
    if energy < 0.35:
        return 2
    return 3


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
    _draw_disc(canvas, cx, cy, CORE_RADIUS * breath, LEVELS - 1)

    # arcs for sparks in flight, from one ring position to another
    node_pos = positions(graph, rings, (cx, cy), spin)
    for edge_index, t, amplitude in pulses.sparks():
        a, b = graph.edges[edge_index]
        ax, ay = node_pos[a]
        bx, by = node_pos[b]
        head = max(0.0, min(1.0, t))
        level = 3 if amplitude >= 0.35 else 2
        for step in range(ARC_STEPS):
            f = head * step / max(1, ARC_STEPS - 1)
            # bow the arc toward the core so it reads as a curve, not a chord
            bow = 1.0 - 0.35 * math.sin(math.pi * f)
            canvas.plot(cx + (ax + (bx - ax) * f - cx) * bow,
                        cy + (ay + (by - ay) * f - cy) * bow, level)

    # the notes themselves
    energy = pulses.energy
    for index, (x, y) in enumerate(node_pos):
        canvas.plot(x, y, _level_for(float(energy[index])))

    return canvas
```

Add `from .braille import Canvas` to the imports at the top of the module.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_reactor.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Narrow the fan-out for the smaller canvas**

In `src/griot/brain/pulse.py`, change:

```python
SPARK_FIRST_FANOUT = 6    # was 12: twelve arcs inside an 86-dot disc is a
                          # starburst, six reads as branching
```

This is a judgement, not a measurement — the spec says so — and is expected to
need tuning once the widget is on screen. Leave `SPARK_FANOUT` (the onward
fan-out of 3) alone.

Run `uv run pytest tests/test_brain_pulse.py -v`. `test_the_cascade_prefers_nearby_connections` reads `SPARK_FIRST_FANOUT` from the module rather than hardcoding it, so it should adapt; if it fails, report rather than editing the test.

- [ ] **Step 6: Look at one frame**

```bash
uv run python -c "
from pathlib import Path
from rich.console import Console
from griot import theme
from griot.brain import graph as gm, settings
from griot.brain.pulse import Pulses, WRITE
from griot.brain.reactor import ring_of, scene, ramp
from griot.config import load_config
conf = load_config(); theme.activate_from_config(conf)
g = gm.load_or_build(conf.vault_path, settings.GRAPH_CACHE)
rings = ring_of(g)
p = Pulses(g, hops=5); p.hit(12, WRITE); p.advance(0.6)
Console().print(scene(g, p, rings, 43, 22, 0.0, 0.0).render(ramp(theme.PALETTE)))
"
```

Expected: a circular reactor with a bright core, a housing ring with spokes, four dotted rings of notes, and a few arcs. Report what it looks like — this is the first time anyone sees it, and it is worth a sentence.

- [ ] **Step 7: Commit**

```bash
git add src/griot/brain/reactor.py src/griot/brain/pulse.py tests/test_reactor.py
git commit -m "brain: assemble the reactor scene"
```

---

### Task 5: Birth detection

**Files:**
- Create: `src/griot/brain/births.py`
- Test: `tests/test_births.py`

**Interfaces:**
- Consumes: `griot.brain.graph.load_or_build`, `Graph.by_path`.
- Produces: `BirthWatcher(vault_path, cache_path, interval=5.0, suppress=5.0)` with attribute `graph: Graph`, and methods `poll(now: float) -> list[int]` (node indices newly born) and `swallows_write(path: str, now: float) -> bool`.

A note Claude creates and writes produces a hook write immediately and a birth up to `interval` seconds later. The birth is the better animation and the truer event, so the write is suppressed when a birth for the same path is about to land.

- [ ] **Step 1: Write the failing test**

```python
"""New notes are their own event — the one the feature exists for."""
from griot.brain.births import BirthWatcher


def write_note(root, name, body="x"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return str(path.resolve())


def test_a_new_note_is_reported_once(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)                                   # first poll establishes the baseline
    born = write_note(vault, "B.md")
    fresh = w.poll(1.0)
    assert len(fresh) == 1
    assert w.graph.paths[fresh[0]] == born
    assert w.poll(2.0) == [], "a birth is reported once, not every poll"


def test_an_edit_to_an_existing_note_is_not_a_birth(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)
    write_note(vault, "A.md", body="changed")
    assert w.poll(1.0) == []


def test_polling_respects_the_interval(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0)
    w.poll(0.0)
    write_note(vault, "B.md")
    assert w.poll(1.0) == [], "too soon — no rescan"
    assert len(w.poll(6.0)) == 1


def test_a_write_is_swallowed_when_its_birth_is_still_coming(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    born = write_note(vault, "B.md")
    assert w.swallows_write(born, 1.0), "the birth animation is the better event"


def test_a_write_to_a_known_note_is_never_swallowed(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    known = write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    assert not w.swallows_write(known, 1.0)


def test_suppression_expires(tmp_path):
    """If the rescan somehow never sees it, the write must still get through
    rather than the event vanishing entirely."""
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    unknown = str((vault / "ghost.md").resolve())
    assert w.swallows_write(unknown, 1.0)
    assert not w.swallows_write(unknown, 99.0)


def test_a_vault_that_cannot_be_read_keeps_the_previous_graph(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)
    before = w.graph
    w.vault_path = tmp_path / "gone"
    assert w.poll(1.0) == []
    assert w.graph is before, "a failed rescan must not blank the reactor"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_births.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.births'`.

- [ ] **Step 3: Write the watcher**

```python
"""Notice new notes.

The hook tells us about reads and writes, but not that a file is new — and a
note being born is the event this whole widget exists to show. The graph's
fingerprint already keys on note count plus newest mtime, so a rescan is
cheap and only rebuilds when something actually changed.
"""
from __future__ import annotations

from pathlib import Path

from . import graph as graph_module
from .graph import Graph


class BirthWatcher:
    def __init__(self, vault_path: Path, cache_path: Path,
                 interval: float = 5.0, suppress: float = 5.0) -> None:
        self.vault_path = Path(vault_path)
        self.cache_path = Path(cache_path)
        self.interval = interval
        self.suppress = suppress
        self.graph: Graph = graph_module.load_or_build(self.vault_path, self.cache_path)
        self._known: set[str] = set(self.graph.by_path)
        self._last = float("-inf")

    def poll(self, now: float) -> list[int]:
        if now - self._last < self.interval:
            return []
        self._last = now
        try:
            fresh = graph_module.load_or_build(self.vault_path, self.cache_path)
        except OSError:
            return []                      # keep the graph we have; try again later
        if fresh.n == 0 and self.graph.n:
            return []                      # an empty read is a failure, not an empty vault
        born = [index for path, index in fresh.by_path.items() if path not in self._known]
        self.graph = fresh
        self._known = set(fresh.by_path)
        return born

    def swallows_write(self, path: str, now: float) -> bool:
        """True while a write's birth is still expected. Expires so that a
        note the rescan never sees still produces some animation."""
        if path in self._known:
            return False
        return now - self._last <= self.suppress
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_births.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Time a rescan against the real vault**

```bash
uv run python -c "
import time
from pathlib import Path
from griot.brain import settings
from griot.brain.births import BirthWatcher
v = Path.home() / 'Library/Mobile Documents/iCloud~md~obsidian/Documents/MindVault'
w = BirthWatcher(v, settings.GRAPH_CACHE, interval=0.0)
t0 = time.perf_counter(); w.poll(1.0); print(f'unchanged rescan: {(time.perf_counter()-t0)*1000:.0f} ms')
"
```

Expected: under 150ms for ~1,000 files with no rebuild. If it is much slower the interval needs raising, and that should be reported rather than absorbed.

- [ ] **Step 6: Commit**

```bash
git add src/griot/brain/births.py tests/test_births.py
git commit -m "brain: notice new notes so a birth is its own event"
```

---

### Task 6: The widget

**Files:**
- Create: `src/griot/status/reactor_widget.py`
- Modify: `src/griot/brain/settings.py`, `src/griot/griot.tcss`, `src/griot/status/app.py`, `config.example.toml`
- Test: `tests/test_reactor_widget.py`, `tests/test_brain_settings.py`

**Interfaces:**
- Consumes: everything above, plus `griot.brain.events.Spool` and `events.resolve`, and `griot.brain.pulse.Pulses`.
- Produces: `Reactor(cfg: dict, vault_path, spool_path, id=None)` — a Textual `Static` with `tick()` for tests and `on_mount()` wiring the interval.

`settings.resolve()` loses the kitty-era keys. Replace `DEFAULTS` with:

```python
DEFAULTS: dict[str, object] = {
    "enabled": False,
    "fps": 12,
    "hops": 5,
}
```

and drop the `fps_idle`/`fps_active`/`size`/`socket`/`active_window` handling from `resolve()`, keeping the positive-integer validation for `fps` and `hops`. `write_params()` and the cache paths stay exactly as they are — the hook still reads them.

- [ ] **Step 1: Write the failing test**

```python
"""The widget: a timer, a spool, and a frame. No terminal required."""
import pytest

from griot.brain import settings
from griot.status.reactor_widget import Reactor


def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    for i in range(12):
        (root / "Notes" / f"n{i}.md").write_text(f"see [[n{(i + 1) % 12}]]")
    return root


def widget(tmp_path, **overrides):
    cfg = settings.resolve({"enabled": True, **overrides})
    return Reactor(cfg, vault_path=vault(tmp_path), spool_path=tmp_path / "events",
                   cache_path=tmp_path / "graph.json")


def test_a_tick_produces_a_frame(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    assert w.last_frame is not None
    assert len(w.last_frame.plain.split("\n")) == 22


def test_a_spooled_read_lights_a_note(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    target = next(p for p in w.watcher.graph.by_path)
    (tmp_path / "events").write_text(f"1 read {target}\n")
    w.tick(now=1.0)
    assert float(w.pulses.energy.max()) > 0.5, "the note should be lit"


def test_an_unknown_path_is_ignored(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    (tmp_path / "events").write_text("1 read /somewhere/else.md\n")
    w.tick(now=1.0)
    assert float(w.pulses.energy.max()) <= 0.25, "only idle twinkling"


def test_the_frame_changes_between_ticks(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    first = w.last_frame.plain
    for i in range(1, 12):
        w.tick(now=i * 0.1)
    assert w.last_frame.plain != first, "the reactor should be animating"


def test_a_missing_spool_is_not_an_error(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)          # the spool file was never created
    assert w.last_frame is not None
```

Add to `tests/test_brain_settings.py`:

```python
def test_the_kitty_era_keys_are_gone():
    cfg = settings.resolve({})
    assert set(cfg) == {"enabled", "fps", "hops"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_reactor_widget.py tests/test_brain_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.status.reactor_widget'`.

- [ ] **Step 3: Write the widget**

```python
"""The reactor widget.

Lives in the right pane on a timer. There is no separate process: the status
app already runs a Textual event loop, and putting the animation inside it
removes the pidfile, the focus gate, the socket and the log that the previous
implementation needed.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from textual.widgets import Static

from griot import theme
from griot.brain.births import BirthWatcher
from griot.brain.events import Spool, resolve as resolve_events
from griot.brain.pulse import Pulses, WRITE
from griot.brain.reactor import positions, ramp, ring_of, scene

SPIN_RATE = 0.05          # radians per second
CORE_RATE = 1.1           # core breathing, radians per second
BIRTH_AMPLITUDE = 1.0


class Reactor(Static):
    def __init__(self, cfg: dict, vault_path: Path, spool_path: Path,
                 cache_path: Path, id: str | None = None) -> None:
        super().__init__("", id=id)
        self.cfg = cfg
        self.spool = Spool(Path(spool_path))
        self.watcher = BirthWatcher(Path(vault_path), Path(cache_path))
        self.rings = ring_of(self.watcher.graph)
        self.pulses = Pulses(self.watcher.graph, hops=int(cfg["hops"]))
        self.last_frame = None
        self._spin = 0.0
        self._phase = 0.0
        self._previous = None

    def _dims(self) -> tuple[int, int]:
        """Textual only knows the real size once mounted; tests drive tick()
        directly on an unmounted widget, so fall back rather than raise."""
        try:
            width, height = self.size.width, self.size.height
        except Exception:
            width = height = 0
        return max(10, width or 43), max(6, height or 22)

    def on_mount(self) -> None:
        self.set_interval(1.0 / float(self.cfg["fps"]), self._advance)
        self._advance()

    def _advance(self) -> None:
        self.tick(time.monotonic())
        self.update(self.last_frame)

    def tick(self, now: float) -> None:
        step = 1.0 / float(self.cfg["fps"])
        if self._previous is not None:
            step = max(1e-3, now - self._previous)
        self._previous = now

        for index in self.watcher.poll(now):
            self._rebuild()
            self.pulses.energy[index] = BIRTH_AMPLITUDE
            self.pulses.kind_of[index] = WRITE

        for node, kind in resolve_events(self.spool.read_new(), self.watcher.graph):
            path = self.watcher.graph.paths[node]
            if kind == "write" and path and self.watcher.swallows_write(path, now):
                continue          # its birth is coming, and that is the better event
            self.pulses.hit(node, kind)

        self._spin += SPIN_RATE * step
        self._phase += CORE_RATE * step
        self.pulses.advance(step)

        cols, rows = self._dims()
        canvas = scene(self.watcher.graph, self.pulses, self.rings,
                       cols, rows, self._spin, self._phase)
        self.pulses.positions = positions(self.watcher.graph, self.rings,
                                          (canvas.width / 2.0, canvas.height / 2.0),
                                          self._spin)
        self.last_frame = canvas.render(ramp(theme.PALETTE))

    def _rebuild(self) -> None:
        """The vault grew, so the graph and rings are stale. Energy is not
        carried over — indices have moved."""
        self.rings = ring_of(self.watcher.graph)
        self.pulses = Pulses(self.watcher.graph, hops=int(self.cfg["hops"]))
```

In `src/griot/griot.tcss`:

```css
#reactor {
    height: 22;
    background: $bg;
}
```

In `src/griot/status/app.py`, import it and mount it between the scroll area and the footer:

```python
from griot.status.reactor_widget import Reactor
```

```python
        if self.brain_cfg["enabled"]:
            yield Reactor(self.brain_cfg, self.config.vault_path,
                          brain_settings.SPOOL_FILE, brain_settings.GRAPH_CACHE,
                          id="reactor")
        yield DriveFooter(bool(self.sound_cfg["enabled"]), id="drive-footer")
```

resolving `self.brain_cfg = brain_settings.resolve(self.config.brain)` in `__init__` beside the existing `sound_cfg`, and calling `brain_settings.write_params(self.brain_cfg)` there too so the hook learns whether it should spool.

In `config.example.toml`, replace the `[brain]` block with:

```toml
# The vault as an arc reactor in the bottom of the right pane. Notes are
# points on rings, the core is the vault, and reads, writes and new notes
# light it up.
[brain]
enabled = false
fps     = 12       # smoothness only; every timing is wall-clock
hops    = 5        # how far a cascade travels
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_reactor_widget.py tests/test_brain_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Measure a frame against the real vault**

```bash
uv run python -c "
import time
from pathlib import Path
from griot import theme
from griot.brain import settings
from griot.status.reactor_widget import Reactor
from griot.config import load_config
conf = load_config(); theme.activate_from_config(conf)
cfg = settings.resolve({'enabled': True})
w = Reactor(cfg, conf.vault_path, settings.SPOOL_FILE, settings.GRAPH_CACHE)
w.tick(0.0)
t0 = time.perf_counter()
for i in range(20): w.tick(i * 0.08)
ms = (time.perf_counter()-t0)/20*1000
print(f'{ms:.1f} ms/frame -> {ms*12/10:.0f}% of a core at 12fps')
"
```

Expected: single-digit milliseconds, so a few percent of a core. The kitty version cost 25ms and about 75%. If it is above 20ms, report it.

- [ ] **Step 6: Commit**

```bash
git add src/griot/status/reactor_widget.py src/griot/brain/settings.py \
        src/griot/griot.tcss src/griot/status/app.py config.example.toml \
        tests/test_reactor_widget.py tests/test_brain_settings.py
git commit -m "reactor: mount the widget in the right pane"
```

---

### Task 7: Delete the kitty pipeline

**Files:**
- Delete: `src/griot/brain/render.py`, `src/griot/brain/kitty.py`, `src/griot/brain/app.py`, `src/griot/brain/sim.py`, `tests/test_brain_render.py`, `tests/test_brain_kitty.py`, `tests/test_brain_app.py`, `tests/test_brain_sim.py`
- Modify: `pyproject.toml`, `bin/griot`, `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. This task only removes.

Do this last so the tree stays green throughout. The kitty implementation stays in git history and in `docs/design/2026-09-09-brain-background-build-log.md`; it is not maintained.

- [ ] **Step 1: Confirm nothing still imports the doomed modules**

```bash
grep -rn "brain.render\|brain\.kitty\|brain\.app\|brain\.sim\|from .render\|from .kitty\|from .sim\|griot-brain" \
     src/ bin/ tests/ pyproject.toml | grep -v "^docs/"
```

Expected: matches only in the files being deleted or edited in this task. Anything else is a dependency the plan missed — report it rather than deleting anyway.

- [ ] **Step 2: Delete the modules and their tests**

```bash
git rm src/griot/brain/render.py src/griot/brain/kitty.py \
       src/griot/brain/app.py src/griot/brain/sim.py \
       tests/test_brain_render.py tests/test_brain_kitty.py \
       tests/test_brain_app.py tests/test_brain_sim.py
```

- [ ] **Step 3: Remove the console script and the launcher wiring**

In `pyproject.toml`, delete the line:

```toml
griot-brain = "griot.brain.app:main"
```

In `bin/griot`, delete the `BRAIN_PID_FILE` definition, the pidfile kill and `rm -f` inside the `restart` branch, and the whole spawn block that launches `griot-brain`. `numpy` stays in `dependencies` — `pulse.py` uses it.

- [ ] **Step 4: Verify**

```bash
find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} +
uv run pytest -q
sh -n bin/griot && echo "bin/griot parses clean"
uv sync
```

Expected: the suite passes with the four test modules gone, `bin/griot` parses, and `uv sync` succeeds with the console script removed.

Do NOT run `griot restart` — it tears down the live workstation.

- [ ] **Step 5: Rewrite the README section**

Replace the `### Brain background (kitty only)` section with:

````markdown
### The reactor

The bottom of the right pane holds an arc-reactor map of the vault. Notes are
points on concentric rings — the rings are your top-level folders, sized so
the biggest folder gets the outermost ring where there is the most room — and
the glowing core is the vault itself.

It reacts to Claude's work. A read lights that note's point and sends an arc
inward to the core; a write is heavier; and a brand-new note gets its own
moment, igniting at the rim before settling permanently onto its ring. A
note's position is a hash of its path, so it never moves between sessions and
you come to recognise where things live.

Off by default. In `~/.config/griot/config.toml`:

```toml
[brain]
enabled = true
```

Activity comes from `bin/griot-disk`, the PostToolUse hook that already drives
the drive sounds, so nothing extra needs installing. New notes are found by
rescanning the vault every few seconds.

No terminal-specific support is required — it is braille and colour, like the
heartbeat animation above it.
````

Also remove the `kitty` row from the requirements table.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Delete the kitty background pipeline"
```

---

## Verification checklist

- [ ] `uv run pytest -q` — green, with the four deleted test modules gone
- [ ] `grep -rn "kitty" src/ bin/ --include='*.py' --include='griot*'` returns nothing outside comments
- [ ] The frame measurement from Task 6 Step 5 is single-digit milliseconds
- [ ] A read of a real vault note lights a point: append one to the spool by hand and watch a `tick()` respond
- [ ] Creating a file in the vault produces a birth within the poll interval, and the hook's write for it is suppressed
- [ ] Set `enabled = false`, confirm the widget is not mounted and the right pane is unchanged
