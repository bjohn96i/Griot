"""Heat decay and priority-mismatch logic (spec: half-life 4 days)."""
from datetime import date

from griot.tasks.model import TaskNote

HALF_LIFE_DAYS = 4.0
DO_OR_DIE_DAYS = 30           # open with no progress this long = force progress or kill
_DONE_LIKE = {"Done", "Cancelled"}


def is_do_or_die(note: TaskNote, today: date) -> bool:
    """Open task with no progress for > DO_OR_DIE_DAYS (the standing rule).
    No progress date at all on an open task counts as do-or-die."""
    if note.parse_error or note.status in _DONE_LIKE:
        return False
    if note.progress_date is None:
        return True
    return (today - note.progress_date).days > DO_OR_DIE_DAYS


def heat(progress_date: date | None, today: date) -> float:
    if progress_date is None:
        return 0.0
    days = max((today - progress_date).days, 0)
    return 0.5 ** (days / HALF_LIFE_DAYS)


def mismatch(priority: int, heat_value: float) -> str | None:
    if priority <= 2 and heat_value < 0.2:
        return "neglected"
    if priority >= 4 and heat_value > 0.7:
        return "distraction"
    return None


def sort_key(note: TaskNote, today: date) -> tuple:
    return (note.priority, -heat(note.progress_date, today), note.title.lower())


def heat_bar(value: float, width: int = 5) -> str:
    filled = round(max(0.0, min(1.0, value)) * width)
    return "█" * filled + "·" * (width - filled)
