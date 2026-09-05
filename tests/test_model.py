from datetime import date

from griot.tasks.model import TaskNote, parse_task, split_frontmatter

REAL_SHAPE = """---
Status: In Progress
Team: QA
Type: Quick
tags:
  - task
creation date: 2026-09-01
Last Progress: 2026-09-04
---

# Continue the API cache test suite

Body with **markdown**, emoji 🥇, and a dataview block.
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_parse_real_shape(tmp_path):
    p = _write(tmp_path, "Continue the API cache test suite.md", REAL_SHAPE)
    t = parse_task(p)
    assert t.title == "Continue the API cache test suite"
    assert t.status == "In Progress"
    assert t.priority == 3  # missing Priority -> default 3
    assert t.progress_date == date(2026, 9, 4)
    assert not t.parse_error


def test_priority_field_read(tmp_path):
    text = REAL_SHAPE.replace("Team: QA", "Team: QA\nPriority: 1")
    t = parse_task(_write(tmp_path, "a.md", text))
    assert t.priority == 1


def test_fallback_to_creation_date(tmp_path):
    text = REAL_SHAPE.replace("Last Progress: 2026-09-04\n", "")
    t = parse_task(_write(tmp_path, "b.md", text))
    assert t.progress_date == date(2026, 9, 1)


def test_missing_both_dates(tmp_path):
    t = parse_task(_write(tmp_path, "c.md", "---\nStatus: To Do\n---\nbody\n"))
    assert t.progress_date is None


def test_string_dates_parse(tmp_path):
    text = REAL_SHAPE.replace(
        "Last Progress: 2026-09-04", 'Last Progress: "2026-09-04"'
    )
    t = parse_task(_write(tmp_path, "d.md", text))
    assert t.progress_date == date(2026, 9, 4)


def test_garbage_yaml_sets_parse_error(tmp_path):
    t = parse_task(_write(tmp_path, "e.md", "---\n: : :\nnot yaml [\n---\nbody\n"))
    assert t.parse_error
    assert t.priority == 3


def test_no_frontmatter(tmp_path):
    t = parse_task(_write(tmp_path, "f.md", "# Just a heading\n"))
    assert t.parse_error


def test_split_frontmatter_roundtrip():
    fm, all_lines = split_frontmatter(REAL_SHAPE)
    assert fm[0] == "Status: In Progress"
    assert "".join(all_lines) == REAL_SHAPE


def test_invalid_utf8_sets_parse_error(tmp_path):
    p = tmp_path / "g.md"
    p.write_bytes(b"---\nStatus: To Do\n---\n\xff\xfe garbage")
    t = parse_task(p)
    assert t.parse_error
    assert t.priority == 3


def test_parse_jira_field(tmp_path):
    text = REAL_SHAPE.replace(
        "Team: QA", "Team: QA\nJira: https://your-org.atlassian.net/browse/PROJ-4914")
    t = parse_task(_write(tmp_path, "j.md", text))
    assert t.jira == "https://your-org.atlassian.net/browse/PROJ-4914"


def test_jira_absent_is_none(tmp_path):
    t = parse_task(_write(tmp_path, "k.md", REAL_SHAPE))
    assert t.jira is None


def test_jira_urls_normalization():
    from griot.tasks.model import jira_urls
    base = "https://your-org.atlassian.net/browse"
    # already a URL -> as-is
    assert jira_urls("https://x.atlassian.net/browse/PROJ-1", base) == \
        ["https://x.atlassian.net/browse/PROJ-1"]
    # bare comma-separated ticket IDs -> built URLs, one per ticket
    assert jira_urls("PROJ-4927, PROJ-4937", base) == [
        f"{base}/PROJ-4927", f"{base}/PROJ-4937"]
    # n/a / empty / None -> nothing
    assert jira_urls("n/a", base) == []
    assert jira_urls("", base) == []
    assert jira_urls(None, base) == []
