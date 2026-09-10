"""Tailing the hook's spool without losing or replaying events."""
from pathlib import Path

from griot.brain import graph as g
from griot.brain.events import Spool, resolve


def spool_file(tmp_path, *lines):
    """Create the spool with `lines` already in it, as BACKLOG.

    A Spool seeds its offset to the file's size when it is constructed, so
    anything written here is history the reader deliberately skips. Tests
    that want lines actually read must `append()` them after the Spool
    exists — which is also what really happens: the hook appends while the
    reactor is watching.
    """
    p = tmp_path / "events"
    p.write_text("".join(line + "\n" for line in lines))
    return p


def append(path, *lines):
    with Path(path).open("a") as f:
        f.write("".join(line + "\n" for line in lines))
    return Path(path)


def test_a_pre_existing_backlog_is_not_replayed_at_launch(tmp_path):
    """The hook keeps spooling after the status app exits, so at the next
    launch the file is a whole stale session. Replaying it lit most of the
    vault on frame one; the reactor must open quiet."""
    p = spool_file(tmp_path, *[f"170000000{i} write /vault/Old{i}.md" for i in range(9)])
    s = Spool(p)
    assert s.read_new() == [], "a spool written before launch is history, not news"

    append(p, "1700000009 read /vault/New.md")
    assert [e.path for e in s.read_new()] == ["/vault/New.md"], \
        "but anything appended after launch is a live event"


def test_a_spool_that_does_not_exist_yet_starts_from_zero(tmp_path):
    """Seeding the offset from the file size has to tolerate the common case
    of the hook not having created the spool yet."""
    p = tmp_path / "events"
    s = Spool(p)
    assert s.offset == 0
    assert s.read_new() == []
    append(p, "1700000000 write /vault/A.md")
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]


def test_reads_new_lines_only_once(tmp_path):
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "1700000000 write /vault/A.md")
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]
    assert s.read_new() == [], "already-read lines are not replayed"

    append(p, "1700000001 read /vault/B.md")
    assert [e.path for e in s.read_new()] == ["/vault/B.md"]


def test_parses_timestamp_and_kind(tmp_path):
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "1700000000.5 read /vault/A.md")
    event = s.read_new()[0]
    assert event.ts == 1700000000.5
    assert event.kind == "read"


def test_paths_containing_spaces_survive(tmp_path):
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "1700000000 write /vault/My Note.md")
    assert s.read_new()[0].path == "/vault/My Note.md"


def test_malformed_lines_are_skipped(tmp_path):
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "garbage", "1700000000 write /vault/A.md",
           "1700000001 explode /vault/B.md")
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]


def test_a_torn_final_line_is_held_back_until_the_rest_arrives(tmp_path):
    """The hook's `printf` is one write, but a reader can still catch the
    file between the bytes landing. Consuming a line with no newline would
    both emit a truncated path AND advance the offset past it, so the real
    line is lost when the remainder lands."""
    p = spool_file(tmp_path)
    s = Spool(p)
    with p.open("a") as f:
        f.write("1700000000 write /vault/Half")       # no newline yet
    assert s.read_new() == [], "an unterminated line is not an event yet"

    with p.open("a") as f:
        f.write(" Written Note.md\n")                 # the rest of it
    assert [e.path for e in s.read_new()] == ["/vault/Half Written Note.md"], \
        "the completed line must arrive whole, not as two fragments"


def test_a_missing_spool_is_not_an_error(tmp_path):
    assert Spool(tmp_path / "nope").read_new() == []


def test_rotation_past_the_limit_resets_the_offset(tmp_path):
    p = spool_file(tmp_path)
    s = Spool(p, max_bytes=32)
    append(p, "1700000000 write /vault/A.md")
    s.read_new()
    append(p, "1700000001 write /vault/" + "B" * 60 + ".md")
    s.read_new()
    assert p.stat().st_size == 0, "spool is truncated once it passes max_bytes"
    append(p, "1700000002 write /vault/C.md")
    assert [e.path for e in s.read_new()] == ["/vault/C.md"], "no re-read after rotation"


def test_a_stale_backlog_is_reclaimed_rather_than_left_to_grow(tmp_path):
    """Nothing rotates the spool except a reader, so a session's worth of
    hook writes is still sitting there at the next launch. Seeding the
    offset to the file size means the first read is already past max_bytes,
    so the backlog is truncated on frame one instead of being read through
    first."""
    p = spool_file(tmp_path, *[f"17000000{i:02d} write /vault/Old{i}.md" for i in range(40)])
    assert p.stat().st_size > 64
    s = Spool(p, max_bytes=64)
    assert s.read_new() == []
    assert p.stat().st_size == 0, "the stale backlog is reclaimed, not replayed"


def test_rotation_is_skipped_when_a_write_lands_mid_cycle(tmp_path):
    """The hook appends on every Claude tool call. Truncating the whole file
    after our read would silently destroy whatever arrived in between."""
    p = spool_file(tmp_path)
    s = Spool(p, max_bytes=32)
    append(p, "1700000000 write /vault/" + "A" * 60 + ".md")
    assert len(s.read_new()) == 1

    append(p, "1700000001 write /vault/RACE.md")      # the hook, racing us

    s._rotate()
    assert [e.path for e in s.read_new()] == ["/vault/RACE.md"], \
        "an event appended before the rotate must survive it"


def test_truncation_by_someone_else_is_handled(tmp_path):
    """Detection is by size, so the replacement has to be shorter — a
    same-length rewrite is invisible to an offset-tracking reader."""
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "1700000000 write /vault/A Considerably Longer Name.md")
    assert len(s.read_new()) == 1
    p.write_text("1700000009 write /vault/Z.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/Z.md"]


def test_resolve_maps_paths_to_node_indices(tmp_path):
    graph = g.Graph(names=["A"], paths=["/vault/A.md"], edges=[], degree=[0],
                    by_path={"/vault/A.md": 0}, adjacency=[[]], fingerprint="t")
    p = spool_file(tmp_path)
    s = Spool(p)
    append(p, "1700000000 write /vault/A.md", "1700000001 read /vault/Unknown.md")
    assert resolve(s.read_new(), graph) == [(0, "write")], "unknown paths are dropped"
