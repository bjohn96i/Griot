"""New notes are their own event — the one the feature exists for."""
from griot.brain.births import BirthWatcher


def write_note(root, name, body="x"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return str(path.resolve())


def test_a_new_note_is_reported_once(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)                                   # first poll establishes the baseline
    born = write_note(vault, "B.md")
    fresh = w.poll(1.0)
    assert len(fresh) == 1
    assert w.graph.paths[fresh[0]] == born
    assert w.poll(2.0) == [], "a birth is reported once, not every poll"


def test_an_edit_to_an_existing_note_is_not_a_birth(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)
    write_note(vault, "A.md", body="changed")
    assert w.poll(1.0) == []


def test_polling_respects_the_interval(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0)
    w.poll(0.0)
    write_note(vault, "B.md")
    assert w.poll(1.0) == [], "too soon — no rescan"
    assert len(w.poll(6.0)) == 1


def test_a_write_is_swallowed_when_its_birth_is_still_coming(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    born = write_note(vault, "B.md")
    assert w.swallows_write(born, 1.0), "the birth animation is the better event"


def test_a_write_to_a_known_note_is_never_swallowed(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    known = write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    assert not w.swallows_write(known, 1.0)


def test_suppression_expires(tmp_path):
    """If the rescan somehow never sees it, the write must still get through
    rather than the event vanishing entirely."""
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=5.0, suppress=5.0)
    w.poll(0.0)
    unknown = str((vault / "ghost.md").resolve())
    assert w.swallows_write(unknown, 1.0)
    assert not w.swallows_write(unknown, 99.0)


def test_a_cache_write_failure_is_caught_by_the_handler(tmp_path):
    """load_or_build's cache write is not inside its own try/except, so an
    OSError from the write step (e.g. cache_path is a directory) propagates
    straight into poll(). poll()'s except OSError must swallow it and keep
    the previous graph, the same contract as any other rescan fault."""
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    cache_path = tmp_path / "graph.json"
    w = BirthWatcher(vault, cache_path, interval=0.0)
    w.poll(0.0)
    before = w.graph
    cache_path.unlink()
    cache_path.mkdir()                            # cache write will now raise OSError
    write_note(vault, "B.md")
    assert w.poll(1.0) == []
    assert w.graph is before, "a cache-write fault must not blank the reactor"


def test_a_vault_that_cannot_be_read_keeps_the_previous_graph(tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    write_note(vault, "A.md")
    w = BirthWatcher(vault, tmp_path / "graph.json", interval=0.0)
    w.poll(0.0)
    before = w.graph
    w.vault_path = tmp_path / "gone"
    assert w.poll(1.0) == []
    assert w.graph is before, "a failed rescan must not blank the reactor"
