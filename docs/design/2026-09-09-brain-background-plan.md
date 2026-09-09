# Griot Brain Background — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the vault's link graph as a live, animated background behind the center pane, blooming on whatever note Claude reads or writes.

**Architecture:** A detached `griot-brain` process builds the vault graph, runs a numpy force simulation, renders PNG frames with PIL, and pushes them to kitty's window `background_image` over the remote-control socket. Claude's file activity arrives through an append-only spool written by the existing `bin/griot-disk` PostToolUse hook.

**Tech Stack:** Python 3.13, uv, numpy, Pillow, kitty remote control (unix socket), plain `sh` for the hook.

**Spec:** `docs/design/2026-09-09-brain-background-design.md`

## Global Constraints

- Python `>=3.13`; project managed with `uv`; run tests with `uv run pytest`.
- macOS only (consistent with the rest of griot).
- Requires kitty with `allow_remote_control socket-only` **and** `listen_on`. Plain `allow_remote_control yes` is rejected by kitty and will not work.
- No hex colour literals anywhere outside `theme.py`. Use theme tokens: edges `outline`, ambient nodes `muted`, pulse ramp `accent` → `accent_bright`, reads `secondary`.
- `bin/griot-disk` stays plain `sh` with no `jq` and no Python — it runs on every Claude tool call.
- Feature is opt-in (`[brain].enabled = false` by default) and self-disabling: every failure logs once and exits 0, leaving the workstation untouched.
- Follow the existing config precedent: `Config` carries a raw dict, the owning module has `resolve()` that validates.
- Branch: `feat/brain-background`. Do not push; Johnathan reviews and merges.

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `src/griot/brain/__init__.py` | empty package marker |
| `src/griot/brain/settings.py` | `DEFAULTS`, `resolve()`, cache paths, `write_params()` for the hook |
| `src/griot/brain/graph.py` | vault → nodes/edges/adjacency, artifact filter, disk cache |
| `src/griot/brain/sim.py` | force simulation (grid repulsion, springs, temperature, impulses) |
| `src/griot/brain/pulse.py` | node energy, hop wave, electron positions |
| `src/griot/brain/render.py` | PIL frame → PNG bytes |
| `src/griot/brain/kitty.py` | socket discovery, chunked `set-background-image`, focus query |
| `src/griot/brain/events.py` | spool tail with offset tracking and rotation |
| `src/griot/brain/app.py` | adaptive clock, wiring, pidfile, `--selftest`, `main()` |
| `tests/test_brain_settings.py` … `tests/test_brain_kitty.py` | one test module per unit above |

**Modify:** `pyproject.toml` (deps + script), `src/griot/config.py` (`brain` field), `config.example.toml`, `bin/griot-disk` (spool write), `bin/griot` (spawn/kill), `README.md`, `tests/test_config.py`, `tests/test_hook.py`.

---

### Task 1: Dependencies and `[brain]` settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/griot/config.py:37-40` (dataclass fields), `src/griot/config.py:58-60` (parsing)
- Modify: `config.example.toml`
- Create: `src/griot/brain/__init__.py`, `src/griot/brain/settings.py`
- Test: `tests/test_brain_settings.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.DEFAULTS: dict`, `settings.resolve(user: dict) -> dict`, `settings.CACHE_DIR: Path`, `settings.SPOOL_FILE: Path`, `settings.PARAMS_FILE: Path`, `settings.PID_FILE: Path`, `settings.GRAPH_CACHE: Path`, `settings.write_params(cfg: dict, path: Path | None = None) -> Path`, and `Config.brain: dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_settings.py
"""[brain] config resolution — defaults, validation, and the hook's params file."""
import pytest

from griot.brain import settings


def test_defaults_are_opt_in():
    cfg = settings.resolve({})
    assert cfg["enabled"] is False
    assert cfg["fps_idle"] == 3
    assert cfg["fps_active"] == 15
    assert cfg["hops"] == 3
    assert cfg["size"] == (900, 560)
    assert cfg["socket"] == ""


def test_user_values_override_defaults():
    cfg = settings.resolve({"enabled": True, "fps_active": 10, "size": [640, 400]})
    assert cfg["enabled"] is True
    assert cfg["fps_active"] == 10
    assert cfg["size"] == (640, 400)


@pytest.mark.parametrize("bad, message", [
    ({"fps_idle": 0}, "fps_idle"),
    ({"fps_active": 0}, "fps_active"),
    ({"fps_idle": 20, "fps_active": 5}, "fps_idle"),
    ({"hops": 0}, "hops"),
    ({"active_window": -1}, "active_window"),
    ({"size": [900]}, "size"),
    ({"size": [0, 560]}, "size"),
])
def test_invalid_values_are_rejected_by_name(bad, message):
    with pytest.raises(ValueError) as e:
        settings.resolve(bad)
    assert message in str(e.value)


def test_write_params_renders_shell_assignments(tmp_path):
    target = settings.write_params(settings.resolve({"enabled": True}),
                                   tmp_path / "params")
    body = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert body["enabled"] == "1"
    assert body["spool"].endswith("/brain/events")


def test_write_params_marks_disabled(tmp_path):
    target = settings.write_params(settings.resolve({}), tmp_path / "params")
    assert "enabled=0" in target.read_text()
```

```python
# add to tests/test_config.py
def test_brain_section_is_loaded(tmp_path):
    from griot.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('[brain]\nenabled = true\nfps_active = 12\n')
    assert load_config(p).brain == {"enabled": True, "fps_active": 12}


def test_brain_section_defaults_to_empty(tmp_path):
    from griot.config import load_config
    p = tmp_path / "config.toml"
    p.write_text("")
    assert load_config(p).brain == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_settings.py tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain'` and `AttributeError: 'Config' object has no attribute 'brain'`.

- [ ] **Step 3: Add dependencies and the script entry point**

In `pyproject.toml`, add to `dependencies`:

```toml
    "numpy>=2.0",
    "pillow>=10.0",
```

and to `[project.scripts]`:

```toml
griot-brain = "griot.brain.app:main"
```

Then run `uv sync` to lock them.

- [ ] **Step 4: Write the settings module**

```python
# src/griot/brain/__init__.py
```
(empty file)

```python
# src/griot/brain/settings.py
"""[brain] configuration, cache paths, and the params file the hook reads.

The hook is plain sh and must not parse TOML, so `write_params()` renders the
resolved config as shell assignments — the same contract `sound.write_params()`
uses, and for the same reason: `resolve()` stays the only place enablement is
decided.
"""
from __future__ import annotations

import os
from pathlib import Path

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "griot" / "brain"
SPOOL_FILE = CACHE_DIR / "events"
PARAMS_FILE = CACHE_DIR / "params"
PID_FILE = CACHE_DIR / "pid"
GRAPH_CACHE = CACHE_DIR / "graph.json"

DEFAULTS: dict[str, object] = {
    "enabled": False,
    "fps_idle": 3,
    "fps_active": 15,
    "active_window": 4.0,
    "size": (900, 560),
    "hops": 3,
    "socket": "",
}


def resolve(user: dict) -> dict:
    """Effective brain config: built-in defaults < user. Validates before returning."""
    cfg = {**DEFAULTS, **user}
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["socket"] = str(cfg["socket"])

    for key in ("fps_idle", "fps_active", "hops"):
        try:
            value = int(cfg[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key}: expected a positive integer, got {cfg[key]!r}")
        if value < 1:
            raise ValueError(f"{key}: expected a positive integer, got {value!r}")
        cfg[key] = value
    if cfg["fps_idle"] > cfg["fps_active"]:
        raise ValueError(f"fps_idle ({cfg['fps_idle']}) must not exceed "
                         f"fps_active ({cfg['fps_active']})")

    try:
        window = float(cfg["active_window"])
    except (TypeError, ValueError):
        raise ValueError(f"active_window: expected a number, got {cfg['active_window']!r}")
    if window < 0:
        raise ValueError(f"active_window: expected a non-negative number, got {window!r}")
    cfg["active_window"] = window

    size = tuple(cfg["size"])
    if len(size) != 2:
        raise ValueError(f"size: expected [width, height], got {cfg['size']!r}")
    try:
        w, h = int(size[0]), int(size[1])
    except (TypeError, ValueError):
        raise ValueError(f"size: expected two integers, got {cfg['size']!r}")
    if w < 1 or h < 1:
        raise ValueError(f"size: expected positive dimensions, got {w}x{h}")
    cfg["size"] = (w, h)
    return cfg


def write_params(cfg: dict, path: Path | None = None) -> Path:
    """Render the resolved config as shell assignments for bin/griot-disk."""
    target = Path(path) if path is not None else PARAMS_FILE
    body = (f"enabled={1 if cfg['enabled'] else 0}\n"
            f"spool={SPOOL_FILE}\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return target
```

In `src/griot/config.py`, add the field to the dataclass beside `sound`:

```python
    brain: dict[str, object] = field(default_factory=dict)
```

parse it beside `sound = dict(raw.get("sound", {}))`:

```python
    brain = dict(raw.get("brain", {}))
```

and pass it in the `Config(...)` call beside `sound=sound`:

```python
        brain=brain,
```

Add to `config.example.toml`:

```toml
# The vault's link graph as a live background behind the center pane.
# Requires kitty with remote control — see README "Brain background".
[brain]
enabled       = false
fps_idle      = 3       # frames/sec when nothing is happening
fps_active    = 15      # frames/sec for `active_window` after a read or write
active_window = 4.0
size          = [900, 560]
hops          = 3       # how far a pulse propagates
socket        = ""      # optional; overrides KITTY_LISTEN_ON discovery
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_settings.py tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock config.example.toml src/griot/config.py \
        src/griot/brain/__init__.py src/griot/brain/settings.py \
        tests/test_brain_settings.py tests/test_config.py
git commit -m "brain: [brain] config section, cache paths, and hook params"
```

---

### Task 2: Vault graph builder

**Files:**
- Create: `src/griot/brain/graph.py`
- Test: `tests/test_brain_graph.py`

**Interfaces:**
- Consumes: `settings.GRAPH_CACHE`.
- Produces: `Graph` (frozen dataclass with `names: list[str]`, `paths: list[str | None]`, `edges: list[tuple[int, int]]`, `degree: list[int]`, `by_path: dict[str, int]`, `adjacency: list[list[int]]`, `fingerprint: str`, and property `n: int`), plus `build_graph(vault_path: Path) -> Graph`, `fingerprint(vault_path: Path) -> str`, `load_or_build(vault_path: Path, cache_path: Path) -> Graph`.

Phantom nodes are exactly those whose `paths[i] is None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_graph.py
"""Vault -> graph. Phantom nodes are kept; parse artifacts are not."""
from griot.brain import graph as g


def vault(tmp_path, files: dict[str, str]):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


def test_resolved_links_become_edges(tmp_path):
    v = vault(tmp_path, {"A.md": "see [[B]]", "B.md": "see [[A]]"})
    graph = g.build_graph(v)
    assert set(graph.names) == {"A", "B"}
    a, b = graph.names.index("A"), graph.names.index("B")
    assert graph.edges == [tuple(sorted((a, b)))], "reciprocal links are one edge"


def test_unresolved_targets_become_phantom_nodes(tmp_path):
    v = vault(tmp_path, {"A.md": "see [[Not Written Yet]]"})
    graph = g.build_graph(v)
    i = graph.names.index("Not Written Yet")
    assert graph.paths[i] is None, "phantom nodes carry no file"
    assert graph.paths[graph.names.index("A")] is not None
    assert len(graph.edges) == 1


def test_orphans_are_kept(tmp_path):
    v = vault(tmp_path, {"A.md": "no links here"})
    graph = g.build_graph(v)
    assert graph.names == ["A"]
    assert graph.degree == [0]


def test_links_inside_code_fences_are_ignored(tmp_path):
    v = vault(tmp_path, {"A.md": "```\n[[not a link]]\n```\nreal [[B]]"})
    graph = g.build_graph(v)
    assert "not a link" not in graph.names
    assert "B" in graph.names


def test_artifact_targets_are_filtered(tmp_path):
    v = vault(tmp_path, {"A.md": "[[1]] [[Projects.base]] [[bad\\\\name]] [[Real Note]]"})
    graph = g.build_graph(v)
    assert "1" not in graph.names, "purely numeric"
    assert "Projects.base" not in graph.names, "non-.md extension"
    assert not any("\\\\" in n for n in graph.names), "illegal filename character"
    assert "Real Note" in graph.names


def test_md_extension_on_a_target_is_allowed(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B.md]]", "B.md": "hi"})
    graph = g.build_graph(v)
    assert graph.names.count("B") == 1, "B.md and B are the same node"


def test_hidden_and_trash_directories_are_skipped(tmp_path):
    v = vault(tmp_path, {"A.md": "x", ".trash/Old.md": "y", ".obsidian/Z.md": "z"})
    assert g.build_graph(v).names == ["A"]


def test_self_links_do_not_create_an_edge(tmp_path):
    v = vault(tmp_path, {"A.md": "[[A]]"})
    assert g.build_graph(v).edges == []


def test_adjacency_and_degree_agree_with_edges(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B]] [[C]]", "B.md": "", "C.md": ""})
    graph = g.build_graph(v)
    a = graph.names.index("A")
    assert graph.degree[a] == 2
    assert sorted(graph.adjacency[a]) == sorted(
        [graph.names.index("B"), graph.names.index("C")])


def test_by_path_maps_absolute_paths_to_indices(tmp_path):
    v = vault(tmp_path, {"A.md": ""})
    graph = g.build_graph(v)
    assert graph.by_path[str((v / "A.md").resolve())] == graph.names.index("A")


def test_cache_is_reused_until_the_vault_changes(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B]]", "B.md": ""})
    cache = tmp_path / "graph.json"
    first = g.load_or_build(v, cache)
    assert cache.exists()
    again = g.load_or_build(v, cache)
    assert again.fingerprint == first.fingerprint
    assert again.names == first.names

    (v / "C.md").write_text("[[A]]")
    after = g.load_or_build(v, cache)
    assert after.fingerprint != first.fingerprint
    assert "C" in after.names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.graph'`.

- [ ] **Step 3: Write the graph module**

```python
# src/griot/brain/graph.py
"""The vault's link graph.

Nodes are notes; edges are wikilinks resolved by basename, the way Obsidian
resolves them. Unresolved targets are kept as phantom nodes (paths[i] is None)
because a note you have linked but not yet written is part of the graph's
shape — but only after an artifact filter, since not every unresolved target
is a note anyone means to write.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".trash", ".obsidian", ".space", "node_modules"}
LINK = re.compile(r"\[\[([^\]|#]+)")
FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
ILLEGAL = set('\\/:*?"<>|')


@dataclass(frozen=True)
class Graph:
    names: list[str]
    paths: list[str | None]
    edges: list[tuple[int, int]]
    degree: list[int]
    by_path: dict[str, int]
    adjacency: list[list[int]]
    fingerprint: str

    @property
    def n(self) -> int:
        return len(self.names)


def strip_fences(text: str) -> str:
    """Drop fenced code blocks so `[[...]]` inside them is not a link."""
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def is_artifact(target: str) -> bool:
    """True for unresolved targets that are parse noise, not intended notes."""
    if not target or target.isdigit():
        return True
    if any(c in ILLEGAL for c in target):
        return True
    suffix = Path(target).suffix
    return bool(suffix) and suffix.lower() != ".md"


def _normalise(target: str) -> str:
    target = target.strip().split("/")[-1]
    return target[:-3] if target.lower().endswith(".md") else target


def fingerprint(vault_path: Path) -> str:
    """Cheap change detector: note count plus the newest mtime."""
    count, newest = 0, 0.0
    for path in _walk(vault_path):
        count += 1
        newest = max(newest, path.stat().st_mtime)
    return f"{count}:{newest:.0f}"


def _walk(vault_path: Path):
    for path in vault_path.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def build_graph(vault_path: Path) -> Graph:
    vault_path = Path(vault_path)
    real: dict[str, Path] = {}
    for path in _walk(vault_path):
        real.setdefault(path.stem, path)

    names = list(real)
    index = {name: i for i, name in enumerate(names)}
    paths: list[str | None] = [str(real[name].resolve()) for name in names]
    pairs: set[tuple[int, int]] = set()

    for name in list(names):
        source = index[name]
        try:
            text = real[name].read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in LINK.findall(strip_fences(text)):
            target = _normalise(raw)
            if target not in index:
                if target not in real and is_artifact(target):
                    continue
                index[target] = len(names)
                names.append(target)
                paths.append(None)
            other = index[target]
            if other != source:
                pairs.add((min(source, other), max(source, other)))

    edges = sorted(pairs)
    adjacency: list[list[int]] = [[] for _ in names]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    return Graph(
        names=names,
        paths=paths,
        edges=edges,
        degree=[len(nbrs) for nbrs in adjacency],
        by_path={p: i for i, p in enumerate(paths) if p is not None},
        adjacency=adjacency,
        fingerprint=fingerprint(vault_path),
    )


def load_or_build(vault_path: Path, cache_path: Path) -> Graph:
    """Return the cached graph when the vault is unchanged, else rebuild it."""
    current = fingerprint(Path(vault_path))
    try:
        blob = json.loads(Path(cache_path).read_text())
        if blob.get("fingerprint") == current:
            return Graph(
                names=blob["names"],
                paths=blob["paths"],
                edges=[tuple(e) for e in blob["edges"]],
                degree=blob["degree"],
                by_path=blob["by_path"],
                adjacency=blob["adjacency"],
                fingerprint=current,
            )
    except (OSError, ValueError, KeyError):
        pass
    graph = build_graph(vault_path)
    cache = Path(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "fingerprint": graph.fingerprint, "names": graph.names, "paths": graph.paths,
        "edges": [list(e) for e in graph.edges], "degree": graph.degree,
        "by_path": graph.by_path, "adjacency": graph.adjacency,
    }))
    return graph
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_graph.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Sanity-check against the real vault**

Run:

```bash
uv run python -c "
from pathlib import Path
from griot.brain import graph
g = graph.build_graph(Path.home() / 'Library/Mobile Documents/iCloud~md~obsidian/Documents/MindVault')
phantom = sum(1 for p in g.paths if p is None)
print(f'nodes={g.n} phantom={phantom} edges={len(g.edges)} maxdeg={max(g.degree)}')
"
```

Expected: roughly `nodes=1118 phantom=147 edges=2696 maxdeg=219`. The spec's measurement used no artifact filter, so a slightly *lower* phantom count is correct and expected — investigate only if phantom is above 147 or nodes fall below ~1000.

- [ ] **Step 6: Commit**

```bash
git add src/griot/brain/graph.py tests/test_brain_graph.py
git commit -m "brain: build the vault link graph with phantom nodes"
```

---

### Task 3: Force simulation

**Files:**
- Create: `src/griot/brain/sim.py`
- Test: `tests/test_brain_sim.py`

**Interfaces:**
- Consumes: `graph.Graph`.
- Produces: `Sim(graph: Graph, size: tuple[int, int], seed: int = 0)` with attribute `pos: np.ndarray` shape `(n, 2)` float32, methods `step(dt: float = 0.1) -> None`, `impulse(node: int, strength: float) -> None`, and `kinetic_energy() -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_sim.py
"""The force layout. Its contract is that it never converges and never blows up."""
import numpy as np

from griot.brain import graph as g
from griot.brain.sim import Sim


def ring(n: int) -> g.Graph:
    names = [f"N{i}" for i in range(n)]
    edges = sorted({(min(i, (i + 1) % n), max(i, (i + 1) % n)) for i in range(n)})
    adjacency = [[] for _ in range(n)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    return g.Graph(names=names, paths=[None] * n, edges=edges,
                   degree=[len(x) for x in adjacency], by_path={},
                   adjacency=adjacency, fingerprint="test")


def test_same_seed_gives_identical_motion():
    a, b = Sim(ring(40), (900, 560), seed=7), Sim(ring(40), (900, 560), seed=7)
    for _ in range(20):
        a.step()
        b.step()
    assert np.array_equal(a.pos, b.pos)


def test_positions_stay_finite():
    sim = Sim(ring(120), (900, 560), seed=1)
    for _ in range(300):
        sim.step()
    assert np.isfinite(sim.pos).all(), "no NaN or inf after a long run"


def test_positions_stay_inside_the_frame():
    sim = Sim(ring(120), (900, 560), seed=1)
    for _ in range(300):
        sim.step()
    assert sim.pos[:, 0].min() >= 0 and sim.pos[:, 0].max() <= 900
    assert sim.pos[:, 1].min() >= 0 and sim.pos[:, 1].max() <= 560


def test_it_never_settles():
    """The temperature floor is the whole reason the graph keeps floating."""
    sim = Sim(ring(120), (900, 560), seed=1)
    for _ in range(500):
        sim.step()
    assert sim.kinetic_energy() > 0.0


def test_hubs_move_less_than_leaves():
    """Mass scales with sqrt(degree) so a hub is not flung across the frame."""
    n = 60
    names = [f"N{i}" for i in range(n)]
    edges = sorted((0, i) for i in range(1, n))          # node 0 is the hub
    adjacency = [[] for _ in range(n)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    graph = g.Graph(names=names, paths=[None] * n, edges=edges,
                    degree=[len(x) for x in adjacency], by_path={},
                    adjacency=adjacency, fingerprint="test")
    sim = Sim(graph, (900, 560), seed=3)
    start = sim.pos.copy()
    for _ in range(60):
        sim.step()
    moved = np.linalg.norm(sim.pos - start, axis=1)
    assert moved[0] < np.median(moved[1:])


def test_impulse_moves_the_targeted_node():
    sim = Sim(ring(40), (900, 560), seed=5)
    quiet = Sim(ring(40), (900, 560), seed=5)
    sim.impulse(3, 40.0)
    sim.step()
    quiet.step()
    assert not np.allclose(sim.pos[3], quiet.pos[3])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_sim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.sim'`.

- [ ] **Step 3: Write the simulation**

```python
# src/griot/brain/sim.py
"""Force-directed layout, recomputed every frame.

Repulsion is short-range against a spatial grid rather than all pairs: the
3x3 neighbourhood costs ~5ms for this vault against ~27ms for the naive
O(n^2), and cell-local repulsion alone clumps at cell boundaries. The
temperature floor is not decoration — without it the layout converges within
a few hundred frames and freezes, which is the opposite of the brief.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .graph import Graph

CELL = 60.0
REPULSION = 60.0
SPRING = 0.02
REST_LENGTH = 40.0
CENTERING = 0.01
TEMPERATURE = 0.4
DAMPING = 0.85
MAX_SPEED = 40.0


class Sim:
    def __init__(self, graph: Graph, size: tuple[int, int], seed: int = 0) -> None:
        self.graph = graph
        self.size = size
        self.rng = np.random.default_rng(seed)
        n = graph.n
        self.pos = (self.rng.random((n, 2)) * size).astype(np.float32)
        self.vel = np.zeros((n, 2), np.float32)
        self.inv_mass = (1.0 / np.sqrt(np.maximum(graph.degree, 1), dtype=np.float32)
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

    def step(self, dt: float = 0.1) -> None:
        force = self._repel()

        if self.ea.size:
            span = self.pos[self.eb] - self.pos[self.ea]
            length = np.linalg.norm(span, axis=1, keepdims=True) + 1e-6
            pull = span * (SPRING * (length - REST_LENGTH) / length)
            np.add.at(force, self.ea, pull)
            np.add.at(force, self.eb, -pull)

        force -= (self.pos - self.pos.mean(0)) * CENTERING
        force += self.rng.normal(0.0, TEMPERATURE, self.pos.shape)

        self.vel = (self.vel + force * self.inv_mass[:, None] * dt) * DAMPING
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_sim.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Check the frame budget on the real graph**

Run:

```bash
uv run python -c "
import time
from pathlib import Path
from griot.brain import graph
from griot.brain.sim import Sim
g = graph.build_graph(Path.home() / 'Library/Mobile Documents/iCloud~md~obsidian/Documents/MindVault')
s = Sim(g, (900, 560), seed=1)
for _ in range(10): s.step()
t = time.perf_counter()
for _ in range(30): s.step()
print(f'{(time.perf_counter()-t)/30*1000:.1f} ms/step over {g.n} nodes')
"
```

Expected: under 10 ms. The spec budgets 5.3 ms for repulsion plus ~2 ms for the rest; anything above 15 ms means the grid is degenerate (all nodes in one cell) and `CELL` needs revisiting.

- [ ] **Step 6: Commit**

```bash
git add src/griot/brain/sim.py tests/test_brain_sim.py
git commit -m "brain: force simulation with grid repulsion and a temperature floor"
```

---

### Task 4: Pulse model

**Files:**
- Create: `src/griot/brain/pulse.py`
- Test: `tests/test_brain_pulse.py`

**Interfaces:**
- Consumes: `graph.Graph`.
- Produces: `READ: str`, `WRITE: str`, `HOP_AMPLITUDE: tuple[float, ...]`, and `Pulses(graph: Graph, hops: int = 3)` with `energy: np.ndarray` shape `(n,)` float32, `kind_of: np.ndarray` shape `(n,)`, methods `hit(node: int, kind: str) -> None`, `advance(dt: float) -> None`, `electrons() -> list[tuple[int, float, float]]` returning `(edge_index, t, brightness)`, and property `active: bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_pulse.py
"""Energy, the hop wave, and the electrons riding the edges."""
import pytest

from griot.brain import graph as g
from griot.brain.pulse import HOP_AMPLITUDE, READ, WRITE, Pulses


def chain(n: int) -> g.Graph:
    names = [f"N{i}" for i in range(n)]
    edges = [(i, i + 1) for i in range(n - 1)]
    adjacency = [[] for _ in range(n)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    return g.Graph(names=names, paths=[None] * n, edges=edges,
                   degree=[len(x) for x in adjacency], by_path={},
                   adjacency=adjacency, fingerprint="test")


def test_a_write_puts_full_energy_on_the_hit_node():
    p = Pulses(chain(5))
    p.hit(0, WRITE)
    assert p.energy[0] == pytest.approx(1.0)


def test_the_wave_reaches_neighbours_at_declining_amplitude():
    p = Pulses(chain(5))
    p.hit(0, WRITE)
    for _ in range(30):                      # 0.3s at dt=0.01 covers 2 hops
        p.advance(0.01)
    assert p.energy[1] > p.energy[2] > p.energy[3]
    assert p.energy[1] <= HOP_AMPLITUDE[1]


def test_the_wave_dies_at_the_hop_limit():
    p = Pulses(chain(8), hops=3)
    p.hit(0, WRITE)
    for _ in range(200):
        p.advance(0.01)
    assert p.energy[4] == pytest.approx(0.0), "hop 4 is beyond the limit"


def test_a_read_is_the_lighter_event():
    write, read = Pulses(chain(5)), Pulses(chain(5))
    write.hit(0, WRITE)
    read.hit(0, READ)
    assert read.energy[0] < write.energy[0]
    for _ in range(80):
        write.advance(0.01)
        read.advance(0.01)
    assert read.energy[0] < write.energy[0], "reads also decay faster"


def test_energy_decays_to_quiet():
    p = Pulses(chain(5))
    p.hit(0, WRITE)
    for _ in range(600):
        p.advance(0.01)
    assert not p.active
    assert p.energy.max() < 0.01


def test_electrons_ride_every_edge_and_wrap():
    p = Pulses(chain(4))
    first = {e: t for e, t, _ in p.electrons()}
    assert len(p.electrons()) == 2 * len(p.graph.edges), "two electrons per edge"
    for _ in range(50):
        p.advance(0.05)
    for _, t, _ in p.electrons():
        assert 0.0 <= t <= 1.0, "t stays normalised as electrons wrap"
    assert any(t != first.get(e) for e, t, _ in p.electrons())


def test_electrons_speed_up_near_an_energised_node():
    quiet, hot = Pulses(chain(4)), Pulses(chain(4))
    hot.hit(0, WRITE)
    quiet.advance(0.05)
    hot.advance(0.05)
    quiet_t = [t for e, t, _ in quiet.electrons() if e == 0]
    hot_t = [t for e, t, _ in hot.electrons() if e == 0]
    assert max(hot_t) > max(quiet_t)


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        Pulses(chain(3)).hit(0, "delete")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_pulse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.pulse'`.

- [ ] **Step 3: Write the pulse module**

```python
# src/griot/brain/pulse.py
"""Node energy and the electrons riding the edges.

A hit blooms the node and sends a wave outward, weakening at each hop and
dying at the limit — so writing a hub lights up a cluster and writing an
orphan barely flickers, which is how the vault's structure becomes visible
through activity. Reads are the lighter event, mirroring the asymmetry
sound.py already established for the drive.
"""
from __future__ import annotations

import numpy as np

from .graph import Graph

READ, WRITE = "read", "write"

HOP_AMPLITUDE = (1.0, 0.55, 0.30)
HOP_DELAY = 0.12          # seconds per hop
ELECTRONS_PER_EDGE = 2
AMBIENT_SPEED = 0.08      # fraction of an edge per second at rest
BOOST_SPEED = 0.9
QUIET = 0.01

KINDS = {
    WRITE: {"scale": 1.0, "decay": 1.4, "hops": 3},
    READ: {"scale": 0.6, "decay": 0.5, "hops": 2},
}


class Pulses:
    def __init__(self, graph: Graph, hops: int = 3) -> None:
        self.graph = graph
        self.hops = hops
        self.energy = np.zeros(graph.n, np.float32)
        self.decay = np.full(graph.n, KINDS[WRITE]["decay"], np.float32)
        self.kind_of = np.array([WRITE] * graph.n, dtype=object)
        self._pending: list[tuple[float, int, float, str]] = []   # (delay, node, amp, kind)
        self._clock = 0.0
        count = len(graph.edges) * ELECTRONS_PER_EDGE
        self._edge_of = np.repeat(np.arange(len(graph.edges)), ELECTRONS_PER_EDGE)
        self._t = (np.tile(np.arange(ELECTRONS_PER_EDGE) / ELECTRONS_PER_EDGE,
                           len(graph.edges)).astype(np.float32)
                   if count else np.zeros(0, np.float32))

    @property
    def active(self) -> bool:
        return bool(self.energy.max(initial=0.0) > QUIET) or bool(self._pending)

    def hit(self, node: int, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"kind: expected {READ!r} or {WRITE!r}, got {kind!r}")
        spec = KINDS[kind]
        limit = min(self.hops, spec["hops"])
        seen = {node}
        frontier = [node]
        for hop in range(limit):
            amplitude = HOP_AMPLITUDE[min(hop, len(HOP_AMPLITUDE) - 1)] * spec["scale"]
            for target in frontier:
                self._pending.append(
                    (self._clock + hop * HOP_DELAY, target, amplitude, kind))
            nxt = []
            for current in frontier:
                for other in self.graph.adjacency[current]:
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break

    def advance(self, dt: float) -> None:
        self._clock += dt
        due = [p for p in self._pending if p[0] <= self._clock]
        if due:
            self._pending = [p for p in self._pending if p[0] > self._clock]
            for _, node, amplitude, kind in due:
                self.energy[node] = max(float(self.energy[node]), amplitude)
                self.decay[node] = KINDS[kind]["decay"]
                self.kind_of[node] = kind

        self.energy *= np.exp(-dt / self.decay).astype(np.float32)
        self.energy[self.energy < QUIET / 10] = 0.0

        if self._t.size:
            self._t = (self._t + self._edge_speed() * dt) % 1.0

    def _edge_speed(self) -> np.ndarray:
        if not self.graph.edges:
            return np.zeros(0, np.float32)
        e = np.asarray(self.graph.edges, np.int32)
        hot = np.maximum(self.energy[e[:, 0]], self.energy[e[:, 1]])
        return (AMBIENT_SPEED + BOOST_SPEED * hot)[self._edge_of]

    def electrons(self) -> list[tuple[int, float, float]]:
        if not self._t.size:
            return []
        e = np.asarray(self.graph.edges, np.int32)
        hot = np.maximum(self.energy[e[:, 0]], self.energy[e[:, 1]])[self._edge_of]
        return [(int(edge), float(t), float(b))
                for edge, t, b in zip(self._edge_of, self._t, hot)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_pulse.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/griot/brain/pulse.py tests/test_brain_pulse.py
git commit -m "brain: node energy, the hop wave, and edge electrons"
```

---

### Task 5: Frame renderer

**Files:**
- Create: `src/griot/brain/render.py`
- Test: `tests/test_brain_render.py`

**Interfaces:**
- Consumes: `graph.Graph`, `sim.Sim`, `pulse.Pulses`, `theme.PALETTE`.
- Produces: `frame(graph: Graph, sim: Sim, pulses: Pulses, palette: dict[str, str], size: tuple[int, int]) -> bytes` returning PNG bytes, and `blend(a: str, b: str, t: float) -> tuple[int, int, int]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_render.py
"""Frames are PNG bytes in theme colours. Phantom nodes read as hollow."""
import io

from PIL import Image

from griot import theme
from griot.brain import graph as g
from griot.brain.pulse import WRITE, Pulses
from griot.brain.render import blend, frame
from griot.brain.sim import Sim

SIZE = (200, 120)


def two_nodes(phantom_second: bool) -> g.Graph:
    return g.Graph(names=["A", "B"], paths=["/tmp/A.md", None if phantom_second else "/tmp/B.md"],
                   edges=[(0, 1)], degree=[1, 1], by_path={"/tmp/A.md": 0},
                   adjacency=[[1], [0]], fingerprint="test")


def render(graph, pulses=None):
    sim = Sim(graph, SIZE, seed=2)
    return frame(graph, sim, pulses or Pulses(graph), theme.PALETTE, SIZE)


def test_a_frame_is_a_png_of_the_requested_size():
    data = render(two_nodes(False))
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG"
    assert img.size == SIZE


def test_frames_are_not_blank():
    img = Image.open(io.BytesIO(render(two_nodes(False)))).convert("RGB")
    assert len(img.getcolors(maxcolors=100000)) > 1, "something was drawn"


def test_a_pulse_changes_the_frame():
    graph = two_nodes(False)
    quiet = render(graph)
    pulses = Pulses(graph)
    pulses.hit(0, WRITE)
    assert render(graph, pulses) != quiet


def test_phantom_nodes_render_differently_from_real_ones():
    assert render(two_nodes(True)) != render(two_nodes(False))


def test_no_hex_literals_in_the_module():
    """Colours come from theme tokens; the module must not carry its own."""
    import re
    from pathlib import Path
    source = (Path(__file__).parents[1] / "src/griot/brain/render.py").read_text()
    assert not re.search(r"#[0-9A-Fa-f]{6}", source)


def test_blend_interpolates_between_two_tokens():
    assert blend("#000000", "#FFFFFF", 0.0) == (0, 0, 0)
    assert blend("#000000", "#FFFFFF", 1.0) == (255, 255, 255)
    assert blend("#000000", "#FFFFFF", 0.5) == (127, 127, 127)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.render'`.

- [ ] **Step 3: Write the renderer**

```python
# src/griot/brain/render.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_render.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/griot/brain/render.py tests/test_brain_render.py
git commit -m "brain: render frames in theme colours, phantoms hollow"
```

---

### Task 6: kitty background client

**Files:**
- Create: `src/griot/brain/kitty.py`
- Test: `tests/test_brain_kitty.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `discover_socket(override: str = "") -> str | None`, `KittyBackground(address: str)` with `send_png(data: bytes) -> None`, `clear() -> None`, `focused() -> bool`, `close() -> None`, and module constant `CHUNK = 2048`.

The wire format was captured from `kitten @` on kitty 0.48.2: a chunked stream of `\x1bP@kitty-cmd{json}\x1b\\` messages, `stream: true` on the first, a shared `stream_id`, ~2 KB of base64 per chunk, and a final message with no `data` key to close.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_kitty.py
"""The kitty remote-control client, against a fake socket that records the wire."""
import json
import os
import socket
import threading

import pytest

from griot.brain import kitty


@pytest.fixture
def fake_kitty(tmp_path):
    """A unix socket that records every kitty-cmd message it receives."""
    address = str(tmp_path / "sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(address)
    server.listen(1)
    received: list[dict] = []

    def serve():
        conn, _ = server.accept()
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\x1b\\" in buf:
                head, buf = buf.split(b"\x1b\\", 1)
                _, _, body = head.partition(b"\x1bP@kitty-cmd")
                if body:
                    received.append(json.loads(body))
                    if json.loads(body).get("cmd") == "ls":
                        conn.sendall(b'\x1bP@kitty-cmd{"ok":true,"data":'
                                     b'"[{\\"is_focused\\":true}]"}\x1b\\')
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield address, received
    server.close()


def test_discover_prefers_an_explicit_override(monkeypatch):
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/from/env")
    assert kitty.discover_socket("unix:/from/config") == "/from/config"


def test_discover_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/from/env")
    assert kitty.discover_socket("") == "/from/env"


def test_discover_returns_none_when_there_is_no_kitty(monkeypatch):
    monkeypatch.delenv("KITTY_LISTEN_ON", raising=False)
    assert kitty.discover_socket("") is None


def test_send_png_streams_chunks_and_closes_the_stream(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.send_png(os.urandom(5000))
    client.close()
    assert received[0]["cmd"] == "set-background-image"
    assert received[0]["stream"] is True
    assert all(m["stream_id"] == received[0]["stream_id"] for m in received)
    assert "data" not in received[-1]["payload"], "final message closes the stream"
    assert len(received) > 3, "5000 bytes must span several chunks"


def test_every_chunk_is_within_the_size_limit(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.send_png(os.urandom(9000))
    client.close()
    assert all(len(m["payload"].get("data", "")) <= kitty.CHUNK for m in received)


def test_clear_removes_the_background(fake_kitty):
    address, received = fake_kitty
    client = kitty.KittyBackground(address)
    client.clear()
    client.close()
    assert received[-1]["payload"]["data"] == "none"


def test_focused_reads_the_reply(fake_kitty):
    address, _ = fake_kitty
    client = kitty.KittyBackground(address)
    assert client.focused() is True
    client.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_kitty.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.kitty'`.

- [ ] **Step 3: Write the client**

```python
# src/griot/brain/kitty.py
"""Push frames into kitty's window background over remote control.

kitty draws background_image *below* cell backgrounds, which is why this works
under a full-screen TUI: Claude Code sets an explicit background on ~11 cells
of a 120x40 screen, so the image shows through nearly the whole pane. The
graphics protocol is deliberately not used — under tmux it renders via unicode
placeholders that live in real cells, and Claude Code's next repaint destroys
them.

Requires `allow_remote_control socket-only` plus `listen_on` in kitty.conf.
Plain `allow_remote_control yes` makes kitty reject listen_on outright.
"""
from __future__ import annotations

import base64
import json
import os
import select
import socket
import uuid

CHUNK = 2048
VERSION = [0, 26, 0]
LAYOUT = "scaled"


def discover_socket(override: str = "") -> str | None:
    """Config override wins, then KITTY_LISTEN_ON, else there is no kitty."""
    address = override or os.environ.get("KITTY_LISTEN_ON", "")
    if not address:
        return None
    return address[len("unix:"):] if address.startswith("unix:") else address


class KittyBackground:
    def __init__(self, address: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(address)

    def _send(self, payload: dict) -> None:
        self.sock.sendall(b"\x1bP@kitty-cmd" + json.dumps(payload).encode() + b"\x1b\\")

    def send_png(self, data: bytes) -> None:
        encoded = base64.b64encode(data).decode()
        stream_id = uuid.uuid4().hex
        first = True
        for i in range(0, len(encoded), CHUNK):
            message = {"cmd": "set-background-image", "version": VERSION,
                       "stream_id": stream_id,
                       "payload": {"data": encoded[i:i + CHUNK], "layout": LAYOUT}}
            if first:
                message["stream"] = True
                first = False
            self._send(message)
        self._send({"cmd": "set-background-image", "version": VERSION,
                    "stream_id": stream_id, "payload": {"layout": LAYOUT}})

    def clear(self) -> None:
        """Drop the background image so a dead animator leaves no frozen frame."""
        self._send({"cmd": "set-background-image", "version": VERSION,
                    "payload": {"data": "none", "layout": LAYOUT}})

    def focused(self) -> bool:
        """True when the kitty window has focus. Unreadable replies mean yes."""
        self._send({"cmd": "ls", "version": VERSION, "payload": {}})
        ready, _, _ = select.select([self.sock], [], [], 0.5)
        if not ready:
            return True
        raw = self.sock.recv(1 << 16)
        _, _, body = raw.partition(b"\x1bP@kitty-cmd")
        body = body.split(b"\x1b\\", 1)[0]
        try:
            reply = json.loads(body)
            data = reply.get("data")
            windows = json.loads(data) if isinstance(data, str) else data
            return any(_any_focused(w) for w in windows)
        except (ValueError, TypeError, AttributeError):
            return True

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _any_focused(node) -> bool:
    if isinstance(node, dict):
        if node.get("is_focused"):
            return True
        return any(_any_focused(v) for v in node.values())
    if isinstance(node, list):
        return any(_any_focused(v) for v in node)
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_kitty.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/griot/brain/kitty.py tests/test_brain_kitty.py
git commit -m "brain: kitty remote-control background client"
```

---

### Task 7: Event spool reader

**Files:**
- Create: `src/griot/brain/events.py`
- Test: `tests/test_brain_events.py`

**Interfaces:**
- Consumes: `graph.Graph` (for `by_path`).
- Produces: `Event` (frozen dataclass: `ts: float`, `kind: str`, `path: str`), and `Spool(path: Path, max_bytes: int = 65536)` with `read_new() -> list[Event]` and `resolve(events: list[Event], graph: Graph) -> list[tuple[int, str]]` as a module function.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_events.py
"""Tailing the hook's spool without losing or replaying events."""
from griot.brain import graph as g
from griot.brain.events import Spool, resolve


def spool_file(tmp_path, *lines):
    p = tmp_path / "events"
    p.write_text("".join(line + "\n" for line in lines))
    return p


def test_reads_new_lines_only_once(tmp_path):
    p = spool_file(tmp_path, "1700000000 write /vault/A.md")
    s = Spool(p)
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]
    assert s.read_new() == [], "already-read lines are not replayed"

    with p.open("a") as f:
        f.write("1700000001 read /vault/B.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/B.md"]


def test_parses_timestamp_and_kind(tmp_path):
    s = Spool(spool_file(tmp_path, "1700000000.5 read /vault/A.md"))
    event = s.read_new()[0]
    assert event.ts == 1700000000.5
    assert event.kind == "read"


def test_paths_containing_spaces_survive(tmp_path):
    s = Spool(spool_file(tmp_path, "1700000000 write /vault/My Note.md"))
    assert s.read_new()[0].path == "/vault/My Note.md"


def test_malformed_lines_are_skipped(tmp_path):
    s = Spool(spool_file(tmp_path, "garbage", "1700000000 write /vault/A.md",
                         "1700000001 explode /vault/B.md"))
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]


def test_a_missing_spool_is_not_an_error(tmp_path):
    assert Spool(tmp_path / "nope").read_new() == []


def test_rotation_past_the_limit_resets_the_offset(tmp_path):
    p = spool_file(tmp_path, "1700000000 write /vault/A.md")
    s = Spool(p, max_bytes=32)
    s.read_new()
    with p.open("a") as f:
        f.write("1700000001 write /vault/" + "B" * 60 + ".md\n")
    s.read_new()
    assert p.stat().st_size == 0, "spool is truncated once it passes max_bytes"
    with p.open("a") as f:
        f.write("1700000002 write /vault/C.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/C.md"], "no re-read after rotation"


def test_truncation_by_someone_else_is_handled(tmp_path):
    p = spool_file(tmp_path, "1700000000 write /vault/A.md")
    s = Spool(p)
    s.read_new()
    p.write_text("1700000009 write /vault/Z.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/Z.md"]


def test_resolve_maps_paths_to_node_indices(tmp_path):
    graph = g.Graph(names=["A"], paths=["/vault/A.md"], edges=[], degree=[0],
                    by_path={"/vault/A.md": 0}, adjacency=[[]], fingerprint="t")
    s = Spool(spool_file(tmp_path, "1700000000 write /vault/A.md",
                         "1700000001 read /vault/Unknown.md"))
    assert resolve(s.read_new(), graph) == [(0, "write")], "unknown paths are dropped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.events'`.

- [ ] **Step 3: Write the spool reader**

```python
# src/griot/brain/events.py
"""Tail the hook's append-only spool.

A plain file with an offset, not a FIFO: a FIFO with no reader blocks its
writer, and the writer here runs on every one of Claude's tool calls. A
stalled hook would stall Claude.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .graph import Graph

KINDS = {"read", "write"}


@dataclass(frozen=True)
class Event:
    ts: float
    kind: str
    path: str


class Spool:
    def __init__(self, path: Path, max_bytes: int = 65536) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.offset = 0

    def read_new(self) -> list[Event]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:            # someone truncated it under us
            self.offset = 0
        events: list[Event] = []
        try:
            with self.path.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(self.offset)
                for line in f:
                    if not line.endswith("\n"):
                        break             # a partial write; pick it up next tick
                    self.offset += len(line.encode("utf-8"))
                    event = _parse(line)
                    if event is not None:
                        events.append(event)
        except OSError:
            return events
        if self.offset >= self.max_bytes:
            self._rotate()
        return events

    def _rotate(self) -> None:
        try:
            with self.path.open("r+") as f:
                f.truncate(0)
            self.offset = 0
        except OSError:
            pass


def _parse(line: str) -> Event | None:
    parts = line.rstrip("\n").split(" ", 2)
    if len(parts) != 3:
        return None
    raw_ts, kind, path = parts
    if kind not in KINDS or not path:
        return None
    try:
        return Event(float(raw_ts), kind, path)
    except ValueError:
        return None


def resolve(events: list[Event], graph: Graph) -> list[tuple[int, str]]:
    """Map spool events onto node indices, dropping paths outside the vault."""
    hits: list[tuple[int, str]] = []
    for event in events:
        node = graph.by_path.get(event.path)
        if node is None:
            node = graph.by_path.get(os.path.realpath(event.path))
        if node is not None:
            hits.append((node, event.kind))
    return hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_events.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/griot/brain/events.py tests/test_brain_events.py
git commit -m "brain: tail the event spool with offset tracking and rotation"
```

---

### Task 8: Hook writes the spool

**Files:**
- Modify: `bin/griot-disk`
- Test: `tests/test_hook.py`

**Interfaces:**
- Consumes: `settings.write_params()` output (`enabled`, `spool`).
- Produces: spool lines `"<epoch> <read|write> <abs path>\n"`.

**The care point:** the hook currently returns early when the drive is disabled or muted. The spool write must happen **before** those gates, or the brain goes dark whenever you mute the drive. Two separate concerns currently share one early-exit path.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_hook.py

@pytest.fixture
def brain(cache):
    """A brain params file next to the sound one, with the spool enabled."""
    root, _ = cache
    d = root / "griot" / "brain"
    d.mkdir(parents=True)
    (d / "params").write_text(f"enabled=1\nspool={d / 'events'}\n")
    return d


def test_a_write_is_spooled_with_its_path(cache, brain):
    run(cache, "write", {"tool_input": {"file_path": "/vault/A.md"}})
    line = (brain / "events").read_text().strip()
    ts, kind, path = line.split(" ", 2)
    assert float(ts) > 0
    assert kind == "write"
    assert path == "/vault/A.md"


def test_a_read_is_spooled(cache, brain):
    run(cache, "read", {"tool_input": {"file_path": "/vault/B.md"}})
    assert " read /vault/B.md" in (brain / "events").read_text()


def test_paths_with_spaces_are_spooled_whole(cache, brain):
    run(cache, "write", {"tool_input": {"file_path": "/vault/My Note.md"}})
    assert (brain / "events").read_text().strip().endswith(" /vault/My Note.md")


def test_the_spool_is_written_even_when_the_drive_is_muted(cache, brain):
    """The regression the reordering invites: muting the drive must not
    blind the brain. Two separate features, two separate gates."""
    root, sound_dir = cache
    (sound_dir / "muted").touch()
    run(cache, "write", {"tool_input": {"file_path": "/vault/A.md"}})
    assert "/vault/A.md" in (brain / "events").read_text()


def test_the_spool_is_written_even_when_sound_is_disabled(cache, brain):
    root, sound_dir = cache
    (sound_dir / "params").write_text("enabled=0\nclicks=0\nvolume=0.000\n"
                                      "one_shot_volume=0.000\nversion=v2\n")
    run(cache, "write", {"tool_input": {"file_path": "/vault/A.md"}})
    assert "/vault/A.md" in (brain / "events").read_text()


def test_nothing_is_spooled_when_the_brain_is_disabled(cache, brain):
    (brain / "params").write_text(f"enabled=0\nspool={brain / 'events'}\n")
    run(cache, "write", {"tool_input": {"file_path": "/vault/A.md"}})
    assert not (brain / "events").exists()


def test_a_payload_without_a_file_path_spools_nothing(cache, brain):
    """Bash-tool writes carry no file_path — the drive still clicks, the brain
    stays still. A deliberate gap, not a bug."""
    run(cache, "auto", {"tool_input": {"command": "echo hi > /tmp/x"}})
    assert not (brain / "events").exists()


def test_the_hook_still_works_with_no_brain_params(cache):
    assert run(cache, "write", {"tool_input": {"file_path": "/vault/A.md"}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hook.py -v`
Expected: FAIL — the spool file is never created.

- [ ] **Step 3: Restructure the hook**

In `bin/griot-disk`, insert the brain block **immediately after** `kind="${1:-}"` / `[ -n "$kind" ] || exit 0` and **before** the sound params are sourced. Move the sound gating so it no longer guards the spool. The head of the script becomes:

```sh
set -u

DIR="${XDG_CACHE_HOME:-$HOME/.cache}/griot/sound"
PARAMS="$DIR/params"
BRAIN_PARAMS="${XDG_CACHE_HOME:-$HOME/.cache}/griot/brain/params"

kind="${1:-}"
[ -n "$kind" ] || exit 0

# Read stdin once: both the brain (which wants the path) and `auto` (which
# classifies a bash command) need it, and a pipe can only be drained once.
payload=""
if [ "$kind" = "auto" ] || [ -f "$BRAIN_PARAMS" ]; then
    payload=$(cat 2>/dev/null || true)
fi

if [ "$kind" = "auto" ]; then
    # Write markers win: a command that both cats and redirects is a write.
    # `2>/dev/null` and `>&` are not file writes, so they are excluded.
    if printf '%s' "$payload" | grep -Eq \
        '(>>|[^0-9&]>[^&]|\btee\b|\bsed -i\b|\bmv\b|\bcp\b|\brm\b|\bmkdir\b|\btouch\b|\bdd\b|<<|git (commit|add|checkout|switch|merge|rebase|reset|stash|apply|push|mv|rm|clone|init|tag))'
    then
        kind=write
    else
        kind=read
    fi
fi

case "$kind" in
    read|write) ;;
    *) exit 0 ;;
esac

# --- brain spool -------------------------------------------------------
# Deliberately ahead of every sound gate: muting the drive must not blind
# the brain. Bash-tool calls carry no file_path and so spool nothing.
if [ -f "$BRAIN_PARAMS" ]; then
    brain_enabled=$(sed -n 's/^enabled=//p' "$BRAIN_PARAMS")
    brain_spool=$(sed -n 's/^spool=//p' "$BRAIN_PARAMS")
    if [ "${brain_enabled:-0}" = "1" ] && [ -n "${brain_spool:-}" ]; then
        file_path=$(printf '%s' "$payload" \
            | grep -o '"file_path":"[^"]*"' | head -1 \
            | sed 's/.*"file_path":"//; s/"$//')
        if [ -n "$file_path" ]; then
            mkdir -p "$(dirname "$brain_spool")"
            printf '%s %s %s\n' "$(date +%s)" "$kind" "$file_path" >> "$brain_spool"
        fi
    fi
fi

# --- drive sound -------------------------------------------------------
# No params = griot has never installed an engine, so there is no drive to hear.
[ -f "$PARAMS" ] || exit 0
# shellcheck disable=SC1090
. "$PARAMS"

[ "${enabled:-0}" = "1" ] || exit 0
[ "${clicks:-0}" = "1" ] || exit 0
[ -e "$DIR/muted" ] && exit 0
command -v afplay >/dev/null 2>&1 || exit 0
```

Delete the now-duplicated `auto` classification block and the old `kind="${1:-}"` lines further down; everything from `# $$ stands in for $RANDOM` onward is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hook.py -v`
Expected: PASS — the new tests plus every pre-existing hook test, which must not regress.

- [ ] **Step 5: Verify the hook is still fast**

It runs on every tool call, so measure it:

```bash
time (for i in $(seq 50); do echo '{"tool_input":{"file_path":"/vault/A.md"}}' \
  | GRIOT_DISK_DRYRUN=1 bin/griot-disk write >/dev/null; done)
```

Expected: well under 2 s for 50 invocations (~40 ms each, dominated by process startup). If it is slower, the `sed`/`grep` chain is the place to look.

- [ ] **Step 6: Commit**

```bash
git add bin/griot-disk tests/test_hook.py
git commit -m "hook: spool read/write paths for the brain, ahead of the sound gates"
```

---

### Task 9: The animator process

**Files:**
- Create: `src/griot/brain/app.py`
- Test: `tests/test_brain_app.py`
- Modify: `pyproject.toml` (already added `griot-brain` in Task 1 — verify it resolves)

**Interfaces:**
- Consumes: everything above.
- Produces: `Brain(config, brain_cfg, address)` with `tick() -> None` and `fps: float`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_app.py
"""The animator's clock and lifecycle. No real kitty is involved."""
import pytest

from griot.brain import graph as g
from griot.brain.app import Brain
from griot.brain.settings import resolve


class FakeKitty:
    def __init__(self):
        self.frames, self.cleared, self.is_focused = [], 0, True

    def send_png(self, data):
        self.frames.append(data)

    def clear(self):
        self.cleared += 1

    def focused(self):
        return self.is_focused

    def close(self):
        pass


def tiny_graph(tmp_path):
    p = tmp_path / "A.md"
    p.write_text("x")
    return g.Graph(names=["A"], paths=[str(p)], edges=[], degree=[0],
                   by_path={str(p): 0}, adjacency=[[]], fingerprint="t")


def brain(tmp_path, **overrides):
    cfg = resolve({"enabled": True, "size": [80, 60], **overrides})
    b = Brain(graph=tiny_graph(tmp_path), cfg=cfg, client=FakeKitty(),
              spool_path=tmp_path / "events")
    return b


def test_it_idles_at_the_idle_rate(tmp_path):
    b = brain(tmp_path)
    b.tick()
    assert b.fps == b.cfg["fps_idle"]


def test_a_hit_raises_the_frame_rate(tmp_path):
    b = brain(tmp_path)
    (tmp_path / "events").write_text(
        f"1 write {b.graph.paths[0]}\n")
    b.tick()
    assert b.fps == b.cfg["fps_active"]


def test_the_rate_falls_back_after_the_active_window(tmp_path):
    b = brain(tmp_path, active_window=0.0)
    (tmp_path / "events").write_text(f"1 write {b.graph.paths[0]}\n")
    b.tick()
    b.tick()
    assert b.fps == b.cfg["fps_idle"]


def test_a_later_hit_pushes_the_deadline_out_rather_than_stacking(tmp_path):
    b = brain(tmp_path, active_window=10.0)
    (tmp_path / "events").write_text(f"1 write {b.graph.paths[0]}\n")
    b.tick()
    first = b.active_until
    with (tmp_path / "events").open("a") as f:
        f.write(f"2 read {b.graph.paths[0]}\n")
    b.tick()
    assert b.active_until > first


def test_no_frame_is_sent_while_unfocused(tmp_path):
    b = brain(tmp_path)
    b.client.is_focused = False
    b.tick()
    assert b.client.frames == []


def test_frames_resume_when_focus_returns(tmp_path):
    b = brain(tmp_path)
    b.client.is_focused = False
    b.tick()
    b.client.is_focused = True
    b._focus_checked = 0.0        # focus is only re-polled once a second
    b.tick()
    assert len(b.client.frames) == 1


def test_shutdown_clears_the_background(tmp_path):
    b = brain(tmp_path)
    b.shutdown()
    assert b.client.cleared == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'griot.brain.app'`.

- [ ] **Step 3: Write the app**

```python
# src/griot/brain/app.py
"""griot-brain — the animator process.

Detached, with its own lifecycle: it must not block a pane's event loop and
must be able to die without taking a pane with it. Every failure path logs
once and exits 0, because a background animation is never worth breaking the
workstation over.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from griot import config as config_module
from griot import theme

from . import graph as graph_module
from . import kitty, settings
from .events import Spool, resolve as resolve_events
from .pulse import Pulses
from .render import frame
from .sim import Sim

FOCUS_POLL_SECONDS = 1.0


class Brain:
    def __init__(self, graph, cfg, client, spool_path) -> None:
        self.graph = graph
        self.cfg = cfg
        self.client = client
        self.spool = Spool(Path(spool_path))
        self.sim = Sim(graph, cfg["size"], seed=0)
        self.pulses = Pulses(graph, hops=cfg["hops"])
        self.active_until = 0.0
        self.fps = float(cfg["fps_idle"])
        self._focused = True
        self._focus_checked = 0.0

    def _refresh_focus(self, now: float) -> None:
        if now - self._focus_checked >= FOCUS_POLL_SECONDS:
            self._focus_checked = now
            self._focused = self.client.focused()

    def tick(self) -> None:
        now = time.monotonic()
        for node, kind in resolve_events(self.spool.read_new(), self.graph):
            self.pulses.hit(node, kind)
            if kind == "write":
                self.sim.impulse(node, 30.0)
            self.active_until = now + self.cfg["active_window"]

        self.fps = float(self.cfg["fps_active"] if now < self.active_until
                         else self.cfg["fps_idle"])
        dt = 1.0 / self.fps

        self._refresh_focus(now)
        if not self._focused:
            return

        self.sim.step(dt)
        self.pulses.advance(dt)
        self.client.send_png(
            frame(self.graph, self.sim, self.pulses, theme.PALETTE, self.cfg["size"]))

    def run(self) -> None:
        while True:
            started = time.monotonic()
            self.tick()
            time.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - started)))

    def shutdown(self) -> None:
        try:
            self.client.clear()
        finally:
            self.client.close()


def _fail(message: str) -> int:
    print(f"griot-brain: {message}", file=sys.stderr)
    return 0        # never break the workstation over a background animation


# The spec lists "numpy missing" as a degradation case. It cannot arise here:
# numpy is a declared dependency, so `uv run griot-brain` either has it or
# fails to launch at all — and the launcher discards that failure. There is
# nothing to catch at runtime.


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    conf = config_module.load_config()
    theme.activate_from_config(conf)
    try:
        cfg = settings.resolve(conf.brain)
    except ValueError as e:
        return _fail(f"config: {e}")
    if not cfg["enabled"]:
        return 0

    address = kitty.discover_socket(cfg["socket"])
    if address is None:
        return _fail("no kitty socket; set listen_on in kitty.conf "
                     "with allow_remote_control socket-only")
    try:
        client = kitty.KittyBackground(address)
    except OSError as e:
        return _fail(f"cannot reach kitty at {address}: {e}")

    try:
        graph = graph_module.load_or_build(conf.vault_path, settings.GRAPH_CACHE)
    except OSError as e:
        client.close()
        return _fail(f"cannot read the vault at {conf.vault_path}: {e}")

    settings.write_params(cfg)
    brain = Brain(graph, cfg, client, settings.SPOOL_FILE)

    if "--selftest" in argv:
        for _ in range(3):
            brain.tick()
        brain.shutdown()
        print(f"griot-brain: ok — {graph.n} nodes, {len(graph.edges)} edges")
        return 0

    settings.PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.PID_FILE.write_text(str(os.getpid()))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        brain.run()
    except (OSError, BrokenPipeError) as e:
        return _fail(f"kitty went away: {e}")
    finally:
        brain.shutdown()
        settings.PID_FILE.unlink(missing_ok=True)
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_app.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pre-existing tests still pass alongside the new ones.

- [ ] **Step 6: Commit**

```bash
git add src/griot/brain/app.py tests/test_brain_app.py
git commit -m "brain: the animator process, adaptive clock and lifecycle"
```

---

### Task 10: Launcher wiring and documentation

**Files:**
- Modify: `bin/griot`
- Modify: `README.md`
- Test: manual (this task wires processes together; the units are covered above)

**Interfaces:**
- Consumes: `griot-brain` console script, `settings.PID_FILE`.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Start the brain from the launcher**

In `bin/griot`, after the line that sends `griot-status` to pane 2 (`tmux send-keys -t "$SESSION:main.2" ...`), add:

```sh
# The brain is a detached animator, not a pane: it draws into kitty's window
# background. It exits 0 by itself when disabled or when there is no kitty.
(uv run --project "$HERE" griot-brain >/dev/null 2>&1 &) || true
```

- [ ] **Step 2: Stop it on restart**

In the `griot restart` teardown block, beside the two `tmux kill-server` calls, add:

```sh
BRAIN_PID_FILE="${XDG_CACHE_HOME:-$HOME/.cache}/griot/brain/pid"
[ -f "$BRAIN_PID_FILE" ] && kill "$(cat "$BRAIN_PID_FILE")" 2>/dev/null
rm -f "$BRAIN_PID_FILE"
```

- [ ] **Step 3: Verify the wiring by hand**

```bash
uv run griot-brain --selftest
```

With `[brain].enabled = false` (the default), expected: silent, exit 0.
With `enabled = true` outside kitty, expected: `griot-brain: no kitty socket; …`, exit 0.
With `enabled = true` inside kitty configured per the README, expected:
`griot-brain: ok — 1118 nodes, 2696 edges` and three frames visibly drawn behind the pane.

- [ ] **Step 4: Document it in the README**

Add a `### Brain background` subsection under the center-pane section:

````markdown
### Brain background (kitty only)

The vault's link graph, live behind the center pane: nodes floating, electrons
riding the connections, and a bloom on whatever note Claude is reading or
writing. Off by default.

It works because kitty draws its window background image *below* cell
backgrounds, and Claude Code paints an explicit background on only ~11 cells of
a full screen — so the graph shows through nearly the whole pane, while the
tasks and status panes (which do paint every cell) mask it automatically.

**Requires kitty.** Ghostty renders the same image but cannot animate it, and
kitty's graphics protocol is not usable here — under tmux it draws through
unicode placeholders that occupy real cells, which Claude Code's next repaint
destroys.

In `kitty.conf`:

```
allow_remote_control     socket-only
listen_on                unix:/tmp/kitty-griot
background_image_layout  scaled
background_tint          0.85
```

`allow_remote_control yes` is *not* sufficient — kitty rejects `listen_on`
under it. `background_tint` is the dial if the graph ever fights the text.

Then in `~/.config/griot/config.toml`:

```toml
[brain]
enabled = true
```

Check it with `uv run griot-brain --selftest`.
````

Also add a row to the requirements table:

```markdown
| `kitty` | the brain background (optional) | `brew install --cask kitty` |
```

- [ ] **Step 5: Full verification**

```bash
uv run pytest -q
uv run griot-brain --selftest
griot restart
```

Expected: suite green; selftest reports the node and edge counts; the workstation rebuilds with the brain running behind the center pane.

- [ ] **Step 6: Commit**

```bash
git add bin/griot README.md
git commit -m "brain: launch with the workstation, and document the kitty setup"
```

---

## Verification checklist

Run before handing back:

- [ ] `uv run pytest -q` — full suite green, no pre-existing test regressed
- [ ] `uv run griot-brain --selftest` inside kitty — reports node/edge counts, frames appear
- [ ] Mute the drive (`touch ~/.cache/griot/sound/muted`), touch a note, confirm the brain still pulses
- [ ] Set `[brain].enabled = false`, run `griot restart`, confirm no `griot-brain` process and a clean background
- [ ] Kill `griot-brain` with `SIGTERM` and confirm the background image is cleared, not frozen
- [ ] Watch CPU during an active burst — expect roughly half a core total, per the spec's budget
