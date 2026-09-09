"""The animator's clock and lifecycle. No real kitty is involved."""
import pytest

from griot import config as config_module
from griot.brain import app as app_module
from griot.brain import graph as g
from griot.brain import settings as settings_module
from griot.brain.app import Brain
from griot.brain.settings import resolve
from griot.config import Config


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


class FakeKittyClient:
    """Stand-in for kitty.KittyBackground — no real socket."""
    def __init__(self, *a, **kw):
        self.closed = False

    def close(self):
        self.closed = True

    def clear(self):
        pass

    def send_png(self, data):
        pass

    def focused(self):
        return True


def make_config(tmp_path, **brain) -> Config:
    return Config(
        vault_path=tmp_path / "vault",
        tasks_dir="Notes/Tasks",
        claude_default_dir=tmp_path,
        repos_dir=tmp_path,
        startup_prompt="",
        commands={},
        jira_base_url="",
        redis_tunnel_port=0,
        latitude=0.0,
        longitude=0.0,
        left_percent=20,
        right_percent=16,
        brain=brain,
    )


def test_a_disabled_brain_still_writes_brain_enabled_0(tmp_path, monkeypatch):
    """C2: main() used to return before write_params() ran for a disabled
    brain, so bin/griot-disk kept reading a stale brain_enabled=1 from a
    previous enabled trial and paid the spool-write cost forever."""
    params_file = tmp_path / "params"
    monkeypatch.setattr(settings_module, "PARAMS_FILE", params_file)
    monkeypatch.setattr(config_module, "load_config",
                        lambda: make_config(tmp_path, enabled=False))

    rc = app_module.main([])

    assert rc == 0
    assert params_file.exists(), "write_params must run even when disabled"
    assert "brain_enabled=0" in params_file.read_text()


def test_an_empty_graph_refuses_to_run(tmp_path, monkeypatch, capsys):
    """I5: rglob on a vault_path that yields no notes does not raise, so
    without this gate main() would proceed to animate an empty background
    forever instead of refusing to start."""
    (tmp_path / "vault").mkdir()   # exists, but has no .md files
    monkeypatch.setattr(settings_module, "PARAMS_FILE", tmp_path / "params")
    monkeypatch.setattr(settings_module, "GRAPH_CACHE", tmp_path / "graph.json")
    monkeypatch.setattr(config_module, "load_config",
                        lambda: make_config(tmp_path, enabled=True, socket="/tmp/fake"))
    monkeypatch.setattr(app_module.kitty, "discover_socket", lambda override: "fake")
    fake_client = FakeKittyClient()
    monkeypatch.setattr(app_module.kitty, "KittyBackground", lambda address: fake_client)

    rc = app_module.main(["--selftest"])

    assert rc == 0
    assert fake_client.closed is True, "must not leave the socket open"
    assert "no notes found" in capsys.readouterr().err


def test_shutdown_survives_a_dead_socket(tmp_path):
    """Killing the animator while kitty is gone must not print a traceback —
    observed live when restarting the process against a closed socket."""
    b = brain(tmp_path)

    def boom():
        raise BrokenPipeError(32, "Broken pipe")

    b.client.clear = boom
    b.shutdown()          # must not raise
