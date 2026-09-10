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
