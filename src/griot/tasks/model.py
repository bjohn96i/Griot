"""Parse vault task notes: frontmatter -> TaskNote. Never raises."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

_TICKET = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def jira_urls(field: str | None, base_url: str) -> list[str]:
    """Normalize a Jira frontmatter value into browsable URL(s).

    Handles the shapes that appear in the vault: a full URL (used as-is),
    bare ticket ids like 'PROJ-4927, PROJ-4937' (each built onto base_url),
    and 'n/a'/empty (nothing to open)."""
    if not field:
        return []
    f = field.strip()
    if f.lower() in ("n/a", "none", "-", ""):
        return []
    if f.startswith("http://") or f.startswith("https://"):
        return [f]
    return [f"{base_url.rstrip('/')}/{tid}" for tid in _TICKET.findall(f)]


@dataclass(frozen=True)
class TaskNote:
    path: Path
    title: str
    status: str
    priority: int
    progress_date: date | None
    jira: str | None = None
    parse_error: bool = False


def split_frontmatter(text: str) -> tuple[list[str], list[str]] | None:
    """Return (lines between --- fences, all lines keepends) or None."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return [ln.rstrip("\n") for ln in lines[1:i]], lines
    return None


def _to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip().strip('"'))
        except ValueError:
            return None
    return None


def parse_task(path: Path) -> TaskNote:
    title = path.stem
    error = TaskNote(path, title, "?", 3, None, parse_error=True)
    try:
        split = split_frontmatter(path.read_text())
        if split is None:
            return error
        fm_lines, _ = split
        meta = yaml.safe_load("\n".join(fm_lines)) or {}
        if not isinstance(meta, dict):
            return error
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return error
    try:
        priority = int(meta.get("Priority", 3))
    except (TypeError, ValueError):
        priority = 3
    progress = _to_date(meta.get("Last Progress")) or _to_date(
        meta.get("creation date")
    )
    jira = meta.get("Jira")
    return TaskNote(
        path=path,
        title=title,
        status=str(meta.get("Status", "?")),
        priority=min(max(priority, 1), 5),
        progress_date=progress,
        jira=str(jira) if jira else None,
    )
