from datetime import date

from griot.tasks.scanner import dir_signature, scan

TODAY = date(2026, 9, 5)


def _task(dirp, name, status="To Do", priority=None, progress=None):
    fm = [f"Status: {status}"]
    if priority:
        fm.append(f"Priority: {priority}")
    if progress:
        fm.append(f"Last Progress: {progress}")
    (dirp / name).write_text("---\n" + "\n".join(fm) + "\n---\nbody\n")


def test_scan_sorted_and_excludes_subdirs(tmp_path):
    _task(tmp_path, "low.md", priority=5, progress="2026-09-05")
    _task(tmp_path, "high.md", priority=1)
    (tmp_path / "Failed Tasks").mkdir()
    _task(tmp_path / "Failed Tasks", "dead.md", priority=1)
    notes = scan(tmp_path, TODAY)
    assert [n.title for n in notes] == ["high", "low"]


def test_parse_errors_sort_last(tmp_path):
    _task(tmp_path, "good.md", priority=5)
    (tmp_path / "bad.md").write_text("no frontmatter\n")
    notes = scan(tmp_path, TODAY)
    assert [n.title for n in notes] == ["good", "bad"]
    assert notes[1].parse_error


def test_missing_dir_returns_empty(tmp_path):
    assert scan(tmp_path / "nope", TODAY) == []


def test_dir_signature_changes_on_write(tmp_path):
    _task(tmp_path, "a.md")
    sig1 = dir_signature(tmp_path)
    assert dir_signature(tmp_path) == sig1
    _task(tmp_path, "b.md")
    assert dir_signature(tmp_path) != sig1
