import os
import stat
from datetime import date

import pytest

from griot.tasks.writer import cycle_priority, set_field, touch

DOC = """---
Status: In Progress
Team: QA
tags:
  - task
creation date: 2026-09-01
Last Progress: 2026-09-01
---

# Title

Body with trailing spaces
and emoji 🥇 and a fence:

```dataview
TABLE Status FROM "Notes/Tasks"
```

- [ ] a task line 📅 2026-01-01
"""


def _write(tmp_path, text=DOC):
    p = tmp_path / "note.md"
    p.write_text(text)
    return p


def test_replace_preserves_every_other_byte(tmp_path):
    p = _write(tmp_path)
    touch(p, date(2026, 9, 5))
    got = p.read_text()
    expected = DOC.replace("Last Progress: 2026-09-01", "Last Progress: 2026-09-05")
    assert got == expected


def test_insert_when_field_missing(tmp_path):
    p = _write(tmp_path, DOC.replace("Last Progress: 2026-09-01\n", ""))
    touch(p, date(2026, 9, 5))
    lines = p.read_text().splitlines()
    close = lines.index("---", 1)
    assert lines[close - 1] == "Last Progress: 2026-09-05"
    # body untouched
    assert p.read_text().split("---", 2)[2] == DOC.split("---", 2)[2]


def test_does_not_touch_matching_line_in_body(tmp_path):
    tricky = DOC + "\nStatus: In Progress\n"
    p = _write(tmp_path, tricky)
    set_field(p, "Status", "Done")
    got = p.read_text()
    assert got.count("Status: Done") == 1
    assert got.endswith("Status: In Progress\n")  # body copy untouched


def test_cycle_priority_wraps(tmp_path):
    p = _write(tmp_path)
    assert cycle_priority(p, 5) == 1
    assert "Priority: 1" in p.read_text()
    assert cycle_priority(p, 1) == 2
    assert p.read_text().count("Priority:") == 1


def test_no_frontmatter_raises(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("# no frontmatter\n")
    with pytest.raises(ValueError):
        set_field(p, "Priority", "1")


def test_no_trailing_newline_preserved(tmp_path):
    text = "---\nStatus: To Do\n---\nbody without trailing newline"
    p = _write(tmp_path, text)
    set_field(p, "Status", "Done")
    assert p.read_text() == "---\nStatus: Done\n---\nbody without trailing newline"


def test_crlf_preserved(tmp_path):
    # Real CRLF case: write bytes with \r\n line endings
    text = b"---\r\nStatus: To Do\r\n---\r\nbody line\r\n"
    p = tmp_path / "note.md"
    p.write_bytes(text)
    set_field(p, "Status", "Done")
    assert p.read_bytes() == b"---\r\nStatus: Done\r\n---\r\nbody line\r\n"


def test_file_mode_preserved(tmp_path):
    p = _write(tmp_path)
    # Set mode to 0o644 before edit
    os.chmod(p, 0o644)
    original_mode = stat.S_IMODE(os.stat(p).st_mode)
    set_field(p, "Status", "Done")
    new_mode = stat.S_IMODE(os.stat(p).st_mode)
    assert new_mode == original_mode == 0o644
