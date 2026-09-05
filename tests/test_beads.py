from griot.status.beads import bead_intensities, render_beads


def test_pulse_starts_at_left():
    ints = bead_intensities(0, n=9)
    assert ints[0] == 4 and ints[1] == 3 and ints[2] == 2 and ints[3] == 1
    assert ints[5:] == [0, 0, 0, 0]


def test_pulse_travels():
    assert bead_intensities(3, n=9)[3] == 4


def test_pulse_bounces_back():
    # period = 2n-2 = 16; tick 8 is the right edge, tick 9 comes back to 7
    assert bead_intensities(8, n=9)[8] == 4
    assert bead_intensities(9, n=9)[7] == 4


def test_period_wraps():
    assert bead_intensities(16, n=9) == bead_intensities(0, n=9)


def test_render_length():
    out = render_beads(0, n=9)
    assert len(out) == 17  # 9 glyphs + 8 spaces
    assert "●" in out
