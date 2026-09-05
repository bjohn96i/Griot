from datetime import date
from pathlib import Path

import pytest

from griot.tasks.heat import heat, heat_bar, mismatch, sort_key
from griot.tasks.model import TaskNote

TODAY = date(2026, 9, 5)


def test_heat_today_is_full():
    assert heat(TODAY, TODAY) == 1.0


def test_heat_half_life_four_days():
    assert heat(date(2026, 9, 1), TODAY) == pytest.approx(0.5)


def test_heat_two_weeks_is_ember():
    assert heat(date(2026, 8, 22), TODAY) == pytest.approx(0.5 ** 3.5)


def test_heat_none_is_cold():
    assert heat(None, TODAY) == 0.0


def test_heat_future_date_clamps_to_full():
    assert heat(date(2026, 9, 9), TODAY) == 1.0


def test_mismatch_neglected():
    assert mismatch(1, 0.1) == "neglected"
    assert mismatch(2, 0.19) == "neglected"
    assert mismatch(2, 0.2) is None
    assert mismatch(3, 0.1) is None


def test_mismatch_distraction():
    assert mismatch(4, 0.71) == "distraction"
    assert mismatch(5, 0.9) == "distraction"
    assert mismatch(4, 0.7) is None
    assert mismatch(3, 0.9) is None


def _note(priority, progress):
    return TaskNote(Path("x.md"), "x", "To Do", priority, progress)


def test_sort_priority_then_heat_desc():
    hot_p2 = _note(2, TODAY)
    cold_p2 = _note(2, date(2026, 8, 1))
    p1 = _note(1, None)
    notes = sorted([cold_p2, hot_p2, p1], key=lambda n: sort_key(n, TODAY))
    assert notes == [p1, hot_p2, cold_p2]


def test_heat_bar():
    assert heat_bar(1.0) == "█████"
    assert heat_bar(0.0) == "·····"
    assert heat_bar(0.5) in ("██···", "███··")
    assert len(heat_bar(0.33)) == 5


def test_is_do_or_die():
    from griot.tasks.heat import is_do_or_die
    old = _note(2, date(2026, 7, 1))       # ~2 months stale, open
    fresh = _note(2, date(2026, 9, 4))     # 1 day old
    noprog = TaskNote(Path("z.md"), "z", "To Do", 3, None)
    assert is_do_or_die(old, TODAY) is True
    assert is_do_or_die(fresh, TODAY) is False
    assert is_do_or_die(noprog, TODAY) is True
    done = TaskNote(Path("d.md"), "d", "Done", 3, date(2026, 1, 1))
    assert is_do_or_die(done, TODAY) is False   # completed never do-or-die
