"""Scan the vault tasks directory into sorted TaskNotes."""
from datetime import date
from pathlib import Path

from griot.tasks.heat import sort_key
from griot.tasks.model import TaskNote, parse_task


def scan(tasks_dir: Path, today: date) -> list[TaskNote]:
    if not tasks_dir.is_dir():
        return []
    notes = [parse_task(p) for p in sorted(tasks_dir.glob("*.md"))]
    return sorted(notes, key=lambda n: (n.parse_error, sort_key(n, today)))


def dir_signature(tasks_dir: Path) -> tuple:
    if not tasks_dir.is_dir():
        return ()
    return tuple(
        (p.name, p.stat().st_mtime_ns) for p in sorted(tasks_dir.glob("*.md"))
    )
