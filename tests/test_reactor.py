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
