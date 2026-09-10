"""The widget: a timer, a spool, and a frame. No terminal required."""
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
