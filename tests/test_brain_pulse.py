"""Energy, the hop wave, and the electrons riding the edges."""
import pytest

from griot.brain import graph as g
from griot.brain.pulse import (ELECTRONS_PER_EDGE, HOP_AMPLITUDE, KINDS, READ,
                               SPARK_SPEED,
                               WRITE, Pulses)


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
    """Hops are carried by sparks now, so this needs real travel time: at
    SPARK_SPEED edges per second a hop takes 1/SPARK_SPEED seconds."""
    p = Pulses(chain(5))
    p.hit(0, WRITE)
    for _ in range(int(3.5 / SPARK_SPEED / 0.01)):
        p.advance(0.01)
    assert p.energy[0] > p.energy[1] > p.energy[2] > p.energy[3]
    assert p.energy[1] <= HOP_AMPLITUDE[1]


def test_neighbours_do_not_all_light_at_once():
    """The point of spark-carried hops: a hub's neighbours fire in sequence as
    each spark lands, not simultaneously on a shared timer."""
    star = 12
    names = [f"N{i}" for i in range(star)]
    edges = [(0, i) for i in range(1, star)]
    adjacency = [[] for _ in range(star)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    graph = g.Graph(names=names, paths=[None] * star, edges=edges,
                    degree=[len(x) for x in adjacency], by_path={},
                    adjacency=adjacency, fingerprint="test")
    p = Pulses(graph, hops=3)
    p.hit(0, WRITE)
    assert p.sparks(), "a hit must put sparks on the wire"
    for _ in range(10):
        p.advance(0.01)
    assert float(p.energy[1:].max()) == 0.0, \
        "no neighbour may light before a spark has had time to reach it"


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
    for _ in range(900):            # 9s — a write's 1.4s decay needs the room
        p.advance(0.01)
    assert not p.active
    assert p.energy.max() < 0.01


def test_electrons_ride_every_edge_and_wrap():
    p = Pulses(chain(4))
    first = {e: t for e, t, _ in p.electrons()}
    assert len(p.electrons()) == ELECTRONS_PER_EDGE * len(p.graph.edges), \
        "one entry per electron per edge"
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


def test_a_read_after_a_write_does_not_steal_its_identity():
    """Energy merges with max(), but a weaker later event must not also win
    decay/kind — else write-then-read (an ordinary Claude sequence) gives the
    write's amplitude but the read's 0.5s decay and colour instead of the
    write's 1.4s and colour."""
    p = Pulses(chain(5))
    p.hit(0, WRITE)
    p.hit(0, READ)
    assert p.energy[0] == pytest.approx(1.0), "the stronger amplitude still wins"
    assert p.decay[0] == pytest.approx(KINDS[WRITE]["decay"])
    assert p.kind_of[0] == WRITE, "the weaker read must not steal the write's colour"


def test_a_weaker_arriving_spark_does_not_steal_a_stronger_ones_identity():
    """Two sparks landing on the same node in the same tick. The stronger must
    keep its decay and kind even if the weaker is applied after it."""
    p = Pulses(chain(3))
    node = 1
    edge = 0
    p._sparks = [
        [edge, node, 1.0, 1.0, WRITE, 1],   # stronger, processed first
        [edge, node, 1.0, 0.3, READ, 1],    # weaker, processed second
    ]
    p.advance(0.0)
    assert p.energy[node] == pytest.approx(1.0)
    assert p.decay[node] == pytest.approx(KINDS[WRITE]["decay"])
    assert p.kind_of[node] == WRITE


