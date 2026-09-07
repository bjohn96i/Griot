import math

import pytest

from griot.status import animation as anim

# Levels: 0 dim, 1 muted, 2 accent, 3 bright. Frames are lists of rows; each
# row is a list of (char, level) cells. Pure functions, so they are testable.


def _chars(frame):
    return ["".join(c for c, _ in row) for row in frame]


def test_registry_has_four_styles():
    assert set(anim.STYLES) == {"beads", "scope", "bars", "glyphs"}


def test_resolve_merges_theme_default_under_user_config():
    cfg = anim.resolve({"style": "scope", "speed": 0.1}, {"height": 3})
    assert cfg["style"] == "scope" and cfg["speed"] == 0.1 and cfg["height"] == 3
    cfg = anim.resolve({"style": "scope"}, {"style": "bars"})
    assert cfg["style"] == "bars"  # user wins


def test_resolve_rejects_unknown_style():
    with pytest.raises(ValueError, match="unknown animation style"):
        anim.resolve({"style": "beads"}, {"style": "lasers"})


# --- beads: unchanged behaviour, new shape ---

def test_beads_frame_matches_legacy_pulse():
    frame = anim.beads_frame(tick=0, width=17, height=1)
    assert len(frame) == 1
    row = frame[0]
    assert len(row) == 17
    assert row[0] == ("●", 3)          # peak
    assert row[2][0] == "◉" and row[4][0] == "◎"
    assert row[1] == (" ", 0)          # spacer between beads


# --- scope: moving sine drawn in braille ---

def _braille_dots(ch):
    """Return set of (col, row) lit dots for a braille char."""
    bits = ord(ch) - 0x2800
    table = {0x01: (0, 0), 0x02: (0, 1), 0x04: (0, 2), 0x40: (0, 3),
             0x08: (1, 0), 0x10: (1, 1), 0x20: (1, 2), 0x80: (1, 3)}
    return {pos for bit, pos in table.items() if bits & bit}


def test_scope_frame_is_braille_of_requested_size():
    frame = anim.scope_frame(tick=0, width=24, height=2, wavelength=12, amplitude=1.0)
    assert len(frame) == 2 and all(len(r) == 24 for r in frame)
    for row in frame:
        for ch, _ in row:
            assert 0x2800 <= ord(ch) <= 0x28FF


def test_scope_lights_exactly_one_dot_per_subcolumn():
    frame = anim.scope_frame(tick=0, width=24, height=2, wavelength=12, amplitude=1.0,
                             trail=False)
    for x in range(24):
        for sub in (0, 1):
            lit = 0
            for r in range(2):
                lit += sum(1 for (c, _) in _braille_dots(frame[r][x][0]) if c == sub)
            assert lit == 1, f"subcolumn {x}.{sub} lit {lit} dots"


def test_scope_sine_moves_with_tick():
    a = _chars(anim.scope_frame(tick=0, width=24, height=2, wavelength=12, trail=False))
    b = _chars(anim.scope_frame(tick=3, width=24, height=2, wavelength=12, trail=False))
    assert a != b
    # one full wavelength of phase later the frame repeats (12 cells = 24 subcolumns)
    c = _chars(anim.scope_frame(tick=24, width=24, height=2, wavelength=12, trail=False))
    assert a == c


def test_scope_trail_adds_muted_cells_and_excite_brightens():
    plain = anim.scope_frame(tick=5, width=24, height=2, wavelength=12, trail=False)
    trail = anim.scope_frame(tick=5, width=24, height=2, wavelength=12, trail=True)
    assert all(lvl in (0, 2) for row in plain for _, lvl in row)
    assert any(lvl == 1 for row in trail for _, lvl in row)
    hot = anim.scope_frame(tick=5, width=24, height=2, wavelength=12, excited=True)
    assert any(lvl == 3 for row in hot for _, lvl in row)


# --- bars: sine across spaced bars ---

def test_bars_layout_respects_width_and_gap():
    frame = anim.bars_frame(tick=0, width=16, height=2, bar_width=1, gap=1, wavelength=8)
    rows = _chars(frame)
    assert len(rows) == 2 and all(len(r) == 16 for r in rows)
    for r in rows:
        assert all(r[i] == " " for i in range(1, 16, 2)), "gap columns must be blank"


def test_bars_heights_follow_a_sine():
    frame = anim.bars_frame(tick=0, width=16, height=2, bar_width=1, gap=1, wavelength=8,
                            amplitude=1.0)
    heights = anim.bar_heights(tick=0, bars=8, wavelength=8, amplitude=1.0, levels=16)
    assert len(heights) == 8
    assert max(heights) == 16 and min(heights) == 0
    # bottom row of the tallest bar is a full block; shortest bar is empty
    tallest = heights.index(16)
    shortest = heights.index(0)
    assert frame[1][tallest * 2][0] == "█"
    assert frame[1][shortest * 2][0] == " "


def test_bars_peak_is_bright_and_wave_moves():
    frame = anim.bars_frame(tick=0, width=16, height=2, bar_width=1, gap=1, wavelength=8)
    assert any(lvl == 3 for row in frame for _, lvl in row)
    h0 = anim.bar_heights(tick=0, bars=8, wavelength=8, amplitude=1.0, levels=16)
    h1 = anim.bar_heights(tick=1, bars=8, wavelength=8, amplitude=1.0, levels=16)
    assert h0 != h1


# --- glyphs: cyberspace data stream ---

def test_glyph_sets():
    assert set(anim.GLYPH_SETS) == {"katakana", "blocks", "hex", "mixed"}
    assert set(anim.GLYPH_SETS["hex"]) == set("0123456789ABCDEF")
    for s in ("katakana", "blocks", "hex"):
        assert set(anim.GLYPH_SETS[s]) <= set(anim.GLYPH_SETS["mixed"])


def test_glyph_stream_is_deterministic_and_mutates_slowly():
    s0 = anim.GlyphStream(width=40, height=2, glyph_set="hex", mutation_rate=0.1, seed=7)
    s1 = anim.GlyphStream(width=40, height=2, glyph_set="hex", mutation_rate=0.1, seed=7)
    a = s0.step(); b = s1.step()
    assert a == b                                   # same seed, same stream
    before = "".join("".join(r) for r in s0.cells)
    s0.step()
    after = "".join("".join(r) for r in s0.cells)
    changed = sum(1 for x, y in zip(before, after) if x != y)
    assert 0 < changed < 40                          # some cells mutate, not all
    assert set(after) <= set("0123456789ABCDEF")


def test_glyph_packets_travel_and_excite_adds_traffic():
    s = anim.GlyphStream(width=40, height=1, glyph_set="hex", packets=1, packet_length=5,
                         seed=1)
    f0 = s.frame(tick=0); f5 = s.frame(tick=5)
    heads0 = [i for i, (_, l) in enumerate(f0[0]) if l == 3]
    heads5 = [i for i, (_, l) in enumerate(f5[0]) if l == 3]
    assert len(heads0) == 1 and len(heads5) == 1 and heads0 != heads5
    assert sum(1 for _, l in f0[0] if l == 2) == 4  # packet body behind the head
    hot = s.frame(tick=9, excited=True)
    cool = s.frame(tick=9, excited=False)
    assert sum(1 for _, l in hot[0] if l >= 2) > sum(1 for _, l in cool[0] if l >= 2)


# --- render: levels map onto the active theme ---

def test_render_maps_levels_to_theme_styles():
    from griot import theme
    text = anim.render([[("a", 0), ("b", 1), ("c", 2), ("d", 3)]])
    styles = " ".join(str(span.style).lower() for span in text.spans)
    for c in (theme.ACCENT, theme.ACCENT_BRIGHT, theme.MUTED):
        assert c.lower() in styles
    assert text.plain == "abcd"
