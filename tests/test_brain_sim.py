"""The force layout. Its contract is that it never converges and never blows up."""
import pytest
import numpy as np

from griot.brain import graph as g
from griot.brain import sim as sim_module
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
    """Smoke test: the simulation does not crash or converge to NaN after a long run."""
    sim = Sim(ring(120), (900, 560), seed=1)
    for _ in range(500):
        sim.step()
    assert sim.kinetic_energy() > 0.0


def test_the_jitter_is_what_keeps_the_graph_drifting(monkeypatch):
    """Kinetic energy is the wrong observable — residual spring energy swamps
    the jitter for the first ~1500 frames. Mean per-node path length after
    convergence is what actually distinguishes floating from frozen."""
    def drift(temperature: float) -> float:
        monkeypatch.setattr(sim_module, "TEMPERATURE", temperature)
        sim = Sim(ring(120), (900, 560), seed=1)
        for _ in range(3000):
            sim.step()
        previous, total = sim.pos.copy(), 0.0
        for _ in range(150):
            sim.step()
            total += float(np.linalg.norm(sim.pos - previous, axis=1).mean())
            previous = sim.pos.copy()
        return total / 150

    shipped = sim_module.TEMPERATURE
    hot, cold = drift(shipped), drift(0.0)
    assert hot > cold * 4, (
        f"the shipped TEMPERATURE={shipped} is not driving the drift: "
        f"hot={hot:.4f} cold={cold:.4f}")


def test_hubs_move_less_than_leaves():
    """Mass scales with degree (not sqrt) to keep hubs stationary.
    sqrt(degree) was measured to fail this property; 1/degree is required."""
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


def test_impulse_pushes_a_nodes_neighbours_outward():
    node = 3
    shoved = Sim(ring(40), (900, 560), seed=5)
    quiet = Sim(ring(40), (900, 560), seed=5)
    shoved.impulse(node, 40.0)
    shoved.step()
    quiet.step()

    def spread(sim):
        nbrs = sim.graph.adjacency[node]
        return float(np.linalg.norm(sim.pos[nbrs] - sim.pos[node], axis=1).mean())

    assert spread(shoved) > spread(quiet), \
        "a write must push its neighbours outward, not just jog the node"


def test_drift_speed_does_not_depend_on_the_frame_rate():
    """Raising the frame rate must draw the same motion more smoothly, not run
    the world faster. Damping and jitter are both applied per step, so before
    this was fixed the graph drifted 8.83 px/sec at 30fps against 4.49 at 15 —
    twice the speed, which reads on screen as shimmer rather than smoothness.
    """
    def drift(fps: int) -> float:
        dt = 1.0 / fps
        sim = Sim(ring(120), (900, 560), seed=1)
        for _ in range(int(2.0 / dt)):        # two settling seconds
            sim.step(dt)
        previous, total = sim.pos.copy(), 0.0
        for _ in range(fps):                  # one second of frames
            sim.step(dt)
            total += float(np.linalg.norm(sim.pos - previous, axis=1).mean())
            previous = sim.pos.copy()
        return total

    slow, fast = drift(10), drift(30)
    assert fast == pytest.approx(slow, rel=0.35), \
        f"per-second drift must not scale with fps: 10fps={slow:.2f} 30fps={fast:.2f}"
