"""Tailing the hook's spool without losing or replaying events."""
from griot.brain import graph as g
from griot.brain.events import Spool, resolve


def spool_file(tmp_path, *lines):
    p = tmp_path / "events"
    p.write_text("".join(line + "\n" for line in lines))
    return p


def test_reads_new_lines_only_once(tmp_path):
    p = spool_file(tmp_path, "1700000000 write /vault/A.md")
    s = Spool(p)
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]
    assert s.read_new() == [], "already-read lines are not replayed"

    with p.open("a") as f:
        f.write("1700000001 read /vault/B.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/B.md"]


def test_parses_timestamp_and_kind(tmp_path):
    s = Spool(spool_file(tmp_path, "1700000000.5 read /vault/A.md"))
    event = s.read_new()[0]
    assert event.ts == 1700000000.5
    assert event.kind == "read"


def test_paths_containing_spaces_survive(tmp_path):
    s = Spool(spool_file(tmp_path, "1700000000 write /vault/My Note.md"))
    assert s.read_new()[0].path == "/vault/My Note.md"


def test_malformed_lines_are_skipped(tmp_path):
    s = Spool(spool_file(tmp_path, "garbage", "1700000000 write /vault/A.md",
                         "1700000001 explode /vault/B.md"))
    assert [e.path for e in s.read_new()] == ["/vault/A.md"]


def test_a_missing_spool_is_not_an_error(tmp_path):
    assert Spool(tmp_path / "nope").read_new() == []


def test_rotation_past_the_limit_resets_the_offset(tmp_path):
    p = spool_file(tmp_path, "1700000000 write /vault/A.md")
    s = Spool(p, max_bytes=32)
    s.read_new()
    with p.open("a") as f:
        f.write("1700000001 write /vault/" + "B" * 60 + ".md\n")
    s.read_new()
    assert p.stat().st_size == 0, "spool is truncated once it passes max_bytes"
    with p.open("a") as f:
        f.write("1700000002 write /vault/C.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/C.md"], "no re-read after rotation"


def test_rotation_is_skipped_when_a_write_lands_mid_cycle(tmp_path):
    """The hook appends on every Claude tool call. Truncating the whole file
    after our read would silently destroy whatever arrived in between."""
    p = spool_file(tmp_path, "1700000000 write /vault/" + "A" * 60 + ".md")
    s = Spool(p, max_bytes=32)
    assert len(s.read_new()) == 1

    with p.open("a") as f:                     # the hook, racing us
        f.write("1700000001 write /vault/RACE.md\n")

    s._rotate()
    assert [e.path for e in s.read_new()] == ["/vault/RACE.md"], \
        "an event appended before the rotate must survive it"


def test_truncation_by_someone_else_is_handled(tmp_path):
    """Detection is by size, so the replacement has to be shorter — a
    same-length rewrite is invisible to an offset-tracking reader."""
    p = spool_file(tmp_path, "1700000000 write /vault/A Considerably Longer Name.md")
    s = Spool(p)
    assert len(s.read_new()) == 1
    p.write_text("1700000009 write /vault/Z.md\n")
    assert [e.path for e in s.read_new()] == ["/vault/Z.md"]


def test_resolve_maps_paths_to_node_indices(tmp_path):
    graph = g.Graph(names=["A"], paths=["/vault/A.md"], edges=[], degree=[0],
                    by_path={"/vault/A.md": 0}, adjacency=[[]], fingerprint="t")
    s = Spool(spool_file(tmp_path, "1700000000 write /vault/A.md",
                         "1700000001 read /vault/Unknown.md"))
    assert resolve(s.read_new(), graph) == [(0, "write")], "unknown paths are dropped"
