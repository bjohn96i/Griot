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
    # Declared smallest-to-largest — the reverse of size order — so passing
    # requires actually ranking by size, not by the fixture's declaration order.
    graph = vault_graph({"Small": 10, "Medium": 100, "Big": 400})
    rings = ring_of(graph)
    big = rings[graph.names.index("Big-0")]
    small = rings[graph.names.index("Small-0")]
    assert big > small, "more notes means further out, where the circumference is"
    assert big == len(RING_RADII) - 1


def test_folder_is_top_level_not_immediate_parent():
    """A note nested two levels deep belongs to its top-level folder, not its
    immediate parent directory — otherwise every subfolder (Tasks, Meetings,
    People, ...) would be treated as its own folder and the rings would be
    dominated by whichever subfolder name happens to be most common."""
    names = ["Big-0", "Big-1", "Big-nested", "Small-0"]
    paths = ["/vault/Big/note0.md", "/vault/Big/note1.md",
             "/vault/Big/People/someone.md", "/vault/Small/note0.md"]
    n = len(names)
    graph = g.Graph(names=names, paths=paths, edges=[], degree=[0] * n,
                    by_path={p: i for i, p in enumerate(paths)},
                    adjacency=[[] for _ in range(n)], fingerprint="test")
    rings = ring_of(graph)
    assert rings[names.index("Big-nested")] == rings[names.index("Big-0")], \
        "a note two levels deep belongs to its top-level folder (Big), not its immediate parent (People)"


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
    c = angle_of("/vault/Tech Library/Something Else.md")
    assert a != c, "a constant angle_of would satisfy the checks above too"


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
    rings = ring_of(graph)
    pos = positions(graph, rings, centre=(43.0, 44.0), spin=0.0)
    assert len(pos) == graph.n
    assert len(set(pos)) > 1, "positions must not all collapse onto the centre"
    for (x, y), ring in zip(pos, rings):
        assert 0 <= x <= 86 and 0 <= y <= 88
        distance = math.hypot(x - 43.0, y - 44.0)
        assert distance == pytest.approx(RING_RADII[ring], abs=1e-6), \
            "a dot must sit at its ring's radius from the centre, not collapsed to it"


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


def test_the_core_is_drawn_at_the_centre():
    """The middle row alone does not discriminate: the housing ring and its
    spokes cross it too, so that assertion held even with the core deleted.
    HOUSING_RADIUS is 10 and CORE_RADIUS is 6, so the disc of radius < 5
    around the centre can only ever contain core dots."""
    from griot.brain.pulse import Pulses
    from griot.brain.reactor import LEVELS, scene
    graph = vault_graph({"A": 20})
    canvas = scene(graph, Pulses(graph), ring_of(graph), cols=43, rows=22,
                   spin=0.0, core_phase=0.0)
    # confirm the colour list covers every level scene() can emit
    canvas.render(["", "#111111", "#222222", "#333333", "#444444"])
    levels = set()
    for row in range(canvas.rows):
        for col in range(canvas.cols):
            dx, dy = col * 2 - 43, row * 4 - 44
            if (dx * dx + dy * dy) ** 0.5 < 5 and canvas._bits[row][col]:
                levels.add(canvas._level[row][col])
    assert levels, "the core disc (radius < 5 of the centre) must contain lit dots"
    assert levels == {LEVELS - 2}, \
        f"every dot within the core disc should be at the core's level, got {levels}"


def test_the_interior_is_empty_at_rest_and_busy_during_a_cascade():
    """Links are not drawn as chords: at 86x88 dots that is a grey wash. An
    arc across the disc must only ever mean something is happening.

    Compares minimum lit radius outside the housing rather than a dot count
    in a fixed band: a fixed 10-15 band mostly counts the housing spokes'
    own quantized spread (which reaches ~13.0 here, not the nominal 10-12),
    leaving only a one-dot margin between resting and firing — thin enough
    that Task 6's visual-tuning pass (ARC_STEPS, the breath factor, the spoke
    count) could flip it without the underlying behaviour changing. The
    housing/core floor is measured from the resting scene itself, not
    hardcoded, so it tracks whatever those constants are retuned to."""
    from griot.brain.braille import BITS
    from griot.brain.pulse import Pulses, WRITE
    from griot.brain.reactor import RING_RADII, scene
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

    def lit_radii(canvas):
        cx, cy = canvas.width / 2.0, canvas.height / 2.0
        for row in range(canvas.rows):
            for col in range(canvas.cols):
                bits = canvas._bits[row][col]
                if not bits:
                    continue
                for dy in range(4):
                    for dx in range(2):
                        if bits & BITS[dy][dx]:
                            x, y = col * 2 + dx, row * 4 + dy
                            yield math.hypot(x - cx, y - cy)

    def min_lit_radius(canvas, floor):
        candidates = [d for d in lit_radii(canvas) if d > floor]
        return min(candidates) if candidates else None

    rings = ring_of(graph)
    quiet = scene(graph, Pulses(graph, hops=5), rings, cols=43, rows=22,
                  spin=0.0, core_phase=0.0)
    # Nothing but the core and housing sits inside the innermost note ring
    # in a resting scene, so its furthest reach there is exactly the
    # housing's real (quantized) footprint.
    housing_ceiling = max(d for d in lit_radii(quiet) if d < RING_RADII[0])

    firing = Pulses(graph, hops=5)
    firing.positions = None
    firing.hit(0, WRITE)
    firing.advance(0.3)
    firing_canvas = scene(graph, firing, rings, cols=43, rows=22,
                          spin=0.0, core_phase=0.0)

    quiet_radius = min_lit_radius(quiet, housing_ceiling)
    firing_radius = min_lit_radius(firing_canvas, housing_ceiling)
    assert quiet_radius is not None and firing_radius is not None
    assert firing_radius < quiet_radius - 3, \
        ("a travelling cascade should reach meaningfully further inward "
         f"than the resting scene: quiet={quiet_radius:.2f}, "
         f"firing={firing_radius:.2f}")


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


def test_a_spark_between_near_antipodal_nodes_sweeps_around_the_core():
    """angle_of is a hash over hundreds of paths in a real vault, so two ring
    positions landing on almost opposite sides of the disc is common, not a
    corner case. A straight Cartesian interpolation between antipodal points
    lerps through the origin — i.e. straight through the core — no matter how
    hard it is scaled toward the centre. The arc must curve around instead.

    This drives `_draw_arc` directly on a bare canvas rather than diffing a
    full `scene()` render against a quiet one: the core disc at CORE_RADIUS *
    breath (~5.1, but its disc-fill sampling and the 2x4 braille cell grid
    round its *rendered* footprint out to ~5.8) already covers essentially
    every pixel a through-the-centre arc would touch, in both the quiet and
    the firing frame alike — so a same-cell "was this bit already lit"
    diff can never see a dot that lands where the core already is. The
    through-core failure this test exists to catch is invisible to that
    approach; only `_draw_arc`'s own output can be checked directly."""
    from griot.brain.braille import BITS, Canvas
    from griot.brain.reactor import CORE_RADIUS, _draw_arc, angle_of, positions

    # Search for a near-antipodal pair. angle_of is a deterministic hash, so
    # this search always finds the same pair — it is not a source of flakiness.
    candidates = [f"/vault/A/n{i}.md" for i in range(200)]
    angles = [angle_of(p) for p in candidates]
    best = None
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            separation = abs(angles[i] - angles[j])
            separation = min(separation, 2 * math.pi - separation)
            score = abs(separation - math.pi)
            if best is None or score < best[0]:
                best = (score, i, j, separation)
    _, i, j, separation = best
    assert separation == pytest.approx(math.pi, abs=0.01), \
        f"could not find a near-antipodal pair among the candidates; " \
        f"closest separation found was {separation}, not close to pi"

    paths = [candidates[i], candidates[j]]
    names = ["A0", "A1"]
    graph = g.Graph(names=names, paths=paths, edges=[(0, 1)], degree=[1, 1],
                    by_path={paths[0]: 0, paths[1]: 1},
                    adjacency=[[1], [0]], fingerprint="test")
    rings = ring_of(graph)
    cx, cy = 43.0, 44.0
    (ax, ay), (bx, by) = positions(graph, rings, (cx, cy), 0.0)

    canvas = Canvas(43, 22)
    _draw_arc(canvas, cx, cy, ax, ay, bx, by, head=0.5, level=3)

    for row in range(canvas.rows):
        for col in range(canvas.cols):
            bits = canvas._bits[row][col]
            if not bits:
                continue
            for dy in range(4):
                for dx in range(2):
                    if bits & BITS[dy][dx]:
                        x, y = col * 2 + dx, row * 4 + dy
                        distance = math.hypot(x - cx, y - cy)
                        assert distance >= CORE_RADIUS, \
                            ("a spark between near-antipodal nodes drew a dot "
                             f"at distance {distance:.2f} from the centre, "
                             f"inside CORE_RADIUS={CORE_RADIUS} — it went "
                             "through the core instead of around it")
