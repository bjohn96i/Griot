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
    """Seeded with a bogus rate first — __init__ already sets fps_idle, so
    without this the assertion passes whether or not tick() does its job."""
    b = brain(tmp_path)
    b.fps = 999.0
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


def test_the_simulation_advances_by_a_fixed_step_regardless_of_frame_rate(tmp_path):
    """Frame rate controls how OFTEN the world advances, not how far. With
    dt = 1/fps the graph drifted 8.60 px/sec at idle against 2.14 px/sec when
    active — four times faster while idle, the opposite of the intent."""
    b = brain(tmp_path)
    steps = []
    b.sim.step = lambda dt: steps.append(dt)
    b.tick()
    (tmp_path / "events").write_text(f"1 write {b.graph.paths[0]}\n")
    b.tick()
    assert b.fps == b.cfg["fps_active"], "second tick should be the active rate"
    assert steps == [pytest.approx(1 / 15), pytest.approx(1 / 15)], \
        "the step must not vary with the frame rate"
