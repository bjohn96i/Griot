"""The widget: a timer, a spool, and a frame. No terminal required."""
import math

import pytest

from griot.brain import settings
from griot.brain.graph import Graph
from griot.brain.pulse import WRITE
from griot.status.reactor_widget import BIRTH_AMPLITUDE, Reactor


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


# --- births -----------------------------------------------------------------

def born(w, *names) -> list[str]:
    """Create notes in the widget's vault; return their graph keys."""
    notes = w.watcher.vault_path / "Notes"
    keys = []
    for name in names:
        note = notes / f"{name}.md"
        note.write_text(f"a brand new note, {name}")
        keys.append(str(note.resolve()))
    return keys


def rotated(graph, by: int = 1):
    """The same vault, with every node index moved along by `by`.

    A real rescan reshuffles indices whenever a note is added or removed,
    but the walk order that decides how far is the filesystem's, so a test
    that hopes for a shift may not get one. This produces the shift on
    purpose, which is the only way to tell a carry-by-path from a
    carry-by-index.
    """
    n = graph.n
    to = [(i + by) % n for i in range(n)]
    names: list = [None] * n
    paths: list = [None] * n
    for i in range(n):
        names[to[i]] = graph.names[i]
        paths[to[i]] = graph.paths[i]
    edges = sorted({(min(to[a], to[b]), max(to[a], to[b])) for a, b in graph.edges})
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    return Graph(names=names, paths=paths, edges=edges,
                 degree=[len(x) for x in adjacency],
                 by_path={p: i for i, p in enumerate(paths) if p},
                 adjacency=adjacency, fingerprint="rotated")


def test_every_note_born_in_one_rescan_is_lit(tmp_path):
    """A turn that writes three notes produces three births out of a single
    poll. The rebuild used to sit inside the loop over them, so each birth
    threw away the Pulses the previous one had just written into and only
    the last of the three ever animated."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    keys = born(w, "born-a", "born-b", "born-c")

    w.tick(now=6.0)                        # past the 5s rescan interval

    lit = [float(w.pulses.energy[w.watcher.graph.by_path[k]]) for k in keys]
    assert len(lit) == 3
    assert all(e >= BIRTH_AMPLITUDE for e in lit), \
        f"every note born in the same rescan should ignite, got {lit}"


def test_a_birth_does_not_extinguish_the_energy_already_on_the_vault(tmp_path):
    """A write's cascade and some other note's birth overlap by design — the
    rescan lands up to five seconds after the hook event that started it."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    w.watcher.interval = 0.0               # rescan next tick, no wall-clock wait

    node = next(iter(w.watcher.graph.by_path.values()))
    path = w.watcher.graph.paths[node]
    w.pulses.hit(node, WRITE)
    before = float(w.pulses.energy[node])
    assert before > 0.9

    born(w, "newcomer")
    w.tick(now=0.1)

    after = float(w.pulses.energy[w.watcher.graph.by_path[path]])
    assert after > 0.9 * before, \
        f"the written note should keep burning across the rebuild: {before} -> {after}"


def test_a_birth_does_not_cancel_the_cascade_still_in_flight(tmp_path):
    """Carrying node energy alone is not enough: the sparks are the cascade,
    so dropping them keeps whatever has already lit while silently killing
    every hop still to come."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    w.watcher.interval = 0.0

    hub = max(range(w.watcher.graph.n), key=lambda i: w.watcher.graph.degree[i])
    w.pulses.hit(hub, WRITE)
    flying = len(w.pulses._sparks)
    assert flying > 0, "the fixture has to actually produce a cascade"

    born(w, "newcomer")
    w.tick(now=0.1)                        # 0.1 edges at SPARK_SPEED: none arrive

    assert len(w.pulses._sparks) == flying, \
        "a birth must not cancel the sparks a write already sent"


def test_the_rebuild_carries_state_by_path_not_by_index(tmp_path):
    """Indices move whenever the graph is rebuilt, so carrying by index
    smears a note's energy onto whichever unrelated note inherited its
    slot."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    was_graph, was_pulses = w.watcher.graph, w.pulses

    node = next(iter(was_graph.by_path.values()))
    path = was_graph.paths[node]
    was_pulses.hit(node, WRITE)
    edge_paths = {tuple(sorted((was_graph.paths[a], was_graph.paths[b])))
                  for a, b, *_ in ((*was_graph.edges[s[0]], ) for s in was_pulses._sparks)}
    assert edge_paths, "the fixture has to actually produce a cascade"

    w.watcher.graph = rotated(was_graph)   # same notes, every index moved
    assert w.watcher.graph.by_path[path] != node
    w._rebuild(was_graph, was_pulses)

    fresh = w.watcher.graph
    assert float(w.pulses.energy[fresh.by_path[path]]) > 0.9, \
        "the energy has to follow the note, not the index it used to have"
    assert float(w.pulses.energy.argmax()) == fresh.by_path[path]
    assert {tuple(sorted((fresh.paths[a], fresh.paths[b])))
            for a, b, *_ in ((*fresh.edges[s[0]], ) for s in w.pulses._sparks)} == edge_paths, \
        "a carried spark has to keep riding the same two notes"


# --- the core reacts --------------------------------------------------------

def test_a_read_charges_the_core_and_sends_an_arc_inward(tmp_path):
    """The core is the vault. Before this it ran on a free-running sine and
    reacted to nothing, so a write to an unlinked note lit one dot for
    0.46s and the reactor never acknowledged it."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    assert w._core == 0.0, "the reactor opens quiet"

    target = next(iter(w.watcher.graph.by_path))
    (tmp_path / "events").write_text(f"1 read {target}\n")
    w.tick(now=0.1)

    assert w._core > 0.0, "an event has to reach the core"
    node = w.watcher.graph.by_path[target]
    assert [i for i, _ in w._feeds] == [node], "and draw an arc in from that note"


def test_a_write_gives_the_core_more_than_a_read_does(tmp_path):
    """The read/write asymmetry the drive established, carried into the
    core: a write is the heavier event."""
    reader = widget(tmp_path / "r")
    writer = widget(tmp_path / "w")
    for w, kind in ((reader, "read"), (writer, "write")):
        w.tick(now=0.0)
        target = next(iter(w.watcher.graph.by_path))
        (w.spool.path).write_text(f"1 {kind} {target}\n")
        # a known note, so swallows_write() cannot eat the write
        w.tick(now=0.1)
    assert writer._core > reader._core > 0.0


def test_the_core_cools_back_down_when_nothing_is_happening(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    target = next(iter(w.watcher.graph.by_path))
    (tmp_path / "events").write_text(f"1 read {target}\n")
    w.tick(now=0.1)
    charged = w._core

    for i in range(2, 60):
        w.tick(now=i * 0.1)
    assert w._core < charged * 0.05, \
        f"the core has to fade, not latch on: {charged} -> {w._core}"
    assert w._feeds == [], "and its feed arcs have to expire"


def test_an_idle_twinkle_never_touches_the_core(tmp_path):
    """Twinkles set node energy directly rather than going through hit(), so
    the interior must stay dark at rest — an arc across the disc always
    means something is really happening."""
    w = widget(tmp_path)
    for i in range(40):
        w.tick(now=i * 0.1)
    assert float(w.pulses.energy.max()) > 0.0, "the fixture has to be twinkling"
    assert w._core == 0.0
    assert w._feeds == []


def test_a_birth_charges_the_core_hardest(tmp_path):
    """A new note is the event the whole widget exists for."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    born(w, "newcomer")
    w.tick(now=6.0)
    assert w._core == 1.0
    assert len(w._feeds) == 1


def test_the_rendered_core_grows_while_the_vault_is_busy(tmp_path):
    """The end of the chain: charge really does reach the frame."""
    w = widget(tmp_path)
    w.tick(now=0.0)

    def core_cells():
        """Cells lit inside the housing. Measured on the rendered text, so
        this fails unless the charge survives every step from the spool to
        the glyphs. r<5 saturates at 8 cells in both states and cannot tell
        them apart; the housing itself starts at r=9."""
        frame = w.last_frame.plain.split("\n")
        return sum(1 for row, line in enumerate(frame)
                   for col, ch in enumerate(line)
                   if ch != " " and math.hypot(col * 2 + 1 - 43, row * 4 + 1.5 - 44) < 8)

    target = next(iter(w.watcher.graph.by_path))
    (tmp_path / "events").write_text(f"1 write {target}\n")
    w.tick(now=0.05)
    busy = core_cells()
    for i in range(1, 200):
        w.tick(now=0.05 + i * 0.1)
    assert w._core == 0.0
    assert busy > core_cells() * 1.25, \
        f"the core must be visibly larger while working: {busy} vs {core_cells()}"


# --- the rescan is off the event loop ---------------------------------------

def test_the_rescan_is_handed_to_a_worker_rather_than_run_inline(tmp_path):
    """A full vault walk is 60ms against an 83ms frame at 12fps, so running
    it on the event loop stalled the whole status app — not just the
    reactor — every five seconds for the entire session."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    dispatched = []
    w._dispatch_scan = lambda: (dispatched.append(1), True)[1]

    key = born(w, "newcomer")[0]
    w.tick(now=6.0)

    assert dispatched == [1], "the rescan has to go out to a worker"
    assert key not in w.watcher.graph.by_path, \
        "and tick() must not have walked the vault itself while waiting"


def test_only_one_rescan_is_in_flight_at_a_time(tmp_path):
    w = widget(tmp_path)
    w.tick(now=0.0)
    dispatched = []
    w._dispatch_scan = lambda: (dispatched.append(1), True)[1]   # never answers
    for i in range(6, 40):
        w.tick(now=float(i))
    assert dispatched == [1], "a slow scan must not pile up behind itself"


def test_the_worker_body_touches_nothing_before_handing_the_graph_back(tmp_path):
    """Everything the worker does runs off the event loop, so the graph swap
    itself has to happen on the way back in — otherwise a frame can be drawn
    from two different graphs at once."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    before = w.watcher.graph
    handed = []
    w._marshal = lambda fn, *args: handed.append((fn, args))

    key = born(w, "newcomer")[0]
    w._scan_in_thread()

    assert w.watcher.graph is before, "the worker must not swap the graph itself"
    (fn, (fresh,)) = handed[0]
    assert w.pulses.graph is not fresh, "nor rebuild the pulses off the event loop"
    assert fn == w._adopt
    assert key in fresh.by_path, "but it must have found the new note"

    fn(fresh)                                  # ...as the event loop then would
    assert w.watcher.graph is fresh
    assert float(w.pulses.energy[fresh.by_path[key]]) >= BIRTH_AMPLITUDE


def test_a_deleted_note_realigns_the_graph_the_rings_and_the_pulses(tmp_path):
    """Deletions and renames produce no births, so the rebuild used to be
    skipped for them — leaving self.rings and self.pulses sized and ordered
    for a vault that no longer existed."""
    w = widget(tmp_path)
    w.tick(now=0.0)
    notes = w.watcher.vault_path / "Notes"
    (notes / "loner.md").write_text("nothing links here")
    w.tick(now=6.0)                            # a birth: n goes up by one
    assert w.pulses.graph is w.watcher.graph

    (notes / "loner.md").unlink()
    w.tick(now=12.0)                           # a death: no births at all

    assert len(w.rings) == w.watcher.graph.n
    assert w.pulses.energy.shape[0] == w.watcher.graph.n
    assert w.pulses.graph is w.watcher.graph, \
        "the pulses must be rebuilt against the graph actually being drawn"


def test_the_config_dials_reach_the_pulses(tmp_path):
    """speed/spread are config, so they have to survive the trip from the
    resolved dict into the object that actually uses them."""
    from griot.brain.pulse import SPARK_FIRST_FANOUT, SPARK_SPEED
    w = widget(tmp_path, speed=0.5, spread=0.5)
    assert w.pulses.speed == pytest.approx(SPARK_SPEED * 0.5)
    assert w.pulses.first_fanout == round(SPARK_FIRST_FANOUT * 0.5)


def test_a_rescan_does_not_reset_the_dials_to_default(tmp_path):
    """The rebuild constructs a fresh Pulses. If it forgets the dials, the
    reactor silently reverts to stock speed the first time a note is created
    — which is exactly when you are watching it."""
    from griot.brain.pulse import SPARK_FIRST_FANOUT, SPARK_SPEED
    w = widget(tmp_path, speed=0.5, spread=0.5)
    born(w, "fresh-note")
    w.tick(now=100.0)
    assert w.pulses.speed == pytest.approx(SPARK_SPEED * 0.5)
    assert w.pulses.first_fanout == round(SPARK_FIRST_FANOUT * 0.5)
