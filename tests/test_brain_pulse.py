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
    for _ in range(900):            # 9s — a write's 1.4s decay needs the room
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
