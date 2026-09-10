"""The braille dot canvas: 2x4 dots per cell, one colour per cell."""
import pytest
from rich.text import Text

from griot.brain.braille import Canvas


def test_dot_resolution_is_two_by_four_per_cell():
    c = Canvas(10, 5)
    assert (c.width, c.height) == (20, 20)


def test_a_plotted_dot_lights_exactly_one_cell():
    c = Canvas(4, 2)
    c.plot(0, 0, 1)
    text = c.render(["", "#FF0000"])
    assert text.plain[0] == "⠁", "top-left dot is braille bit 1"
    assert text.plain[1] == " ", "neighbouring cells stay blank"


def test_all_eight_dots_in_a_cell_fill_it():
    c = Canvas(1, 1)
    for x in range(2):
        for y in range(4):
            c.plot(x, y, 1)
    assert c.render(["", "#FF0000"]).plain[0] == "⣿", "every bit set"


def test_a_cell_takes_the_brightest_level_plotted_in_it():
    c = Canvas(1, 1)
    c.plot(0, 0, 1)
    c.plot(1, 0, 3)
    text = c.render(["", "#111111", "#222222", "#333333"])
    assert str(text.spans[0].style).lower().endswith("333333"), \
        "colour is per cell, so the cell must take the brighter of the two"


def test_a_dimmer_dot_landing_afterwards_does_not_take_the_cell():
    """The ascending case above cannot tell "brightest wins" from "last
    wins" — plotting 1 then 3 gives 3 either way, and mutating the guard to
    `if level >= 0` leaves it green. Only the descending order discriminates.

    It matters concretely: scene() plots arcs at level 3 and then the notes
    at level 1, so a last-wins canvas would let resting notes punch holes
    through a travelling arc."""
    c = Canvas(1, 1)
    c.plot(0, 0, 3)
    c.plot(1, 0, 1)
    text = c.render(["", "#111111", "#222222", "#333333"])
    assert str(text.spans[0].style).lower().endswith("333333"), \
        "a level-1 dot must not dim a cell an arc already claimed at level 3"


def test_dots_outside_the_canvas_are_dropped_not_wrapped():
    c = Canvas(2, 1)
    for x, y in ((-1, 0), (0, -1), (99, 0), (0, 99)):
        c.plot(x, y, 1)
    assert c.render(["", "#FF0000"]).plain.strip() == "", "nothing should be drawn"


def test_level_zero_draws_nothing():
    c = Canvas(2, 1)
    c.plot(0, 0, 0)
    assert c.render(["", "#FF0000"]).plain.strip() == ""


def test_render_returns_one_line_per_row():
    c = Canvas(6, 3)
    assert len(c.render(["", "#FF0000"]).plain.split("\n")) == 3


def test_clear_resets_the_canvas():
    c = Canvas(2, 1)
    c.plot(0, 0, 2)
    c.clear()
    assert c.render(["", "#111111", "#222222"]).plain.strip() == ""
