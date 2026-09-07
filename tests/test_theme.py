import re

import pytest

from griot import theme

TOKENS = {"bg", "panel", "chrome", "chrome_text", "border", "outline", "select",
          "text", "muted", "accent", "accent_bright", "secondary", "ok", "err"}


def test_three_named_themes_exist():
    assert set(theme.THEMES) == {"vibranium-night", "vaporwave-mono", "dataterm"}


@pytest.mark.parametrize("name", ["vibranium-night", "vaporwave-mono", "dataterm"])
def test_every_theme_has_every_token_as_hex(name):
    colors = theme.THEMES[name]["colors"]
    assert set(colors) == TOKENS
    for v in colors.values():
        assert re.fullmatch(r"#[0-9A-F]{6}", v), v


def test_the_two_dark_themes_are_untouched_by_the_dataterm_restyle():
    """select/outline came out of `border`, chrome out of `panel`. For these two
    the new tokens equal what they were carved from, so nothing shifts."""
    for name in ("vibranium-night", "vaporwave-mono"):
        c = theme.THEMES[name]["colors"]
        assert c["bg"] == "#000000"
        assert c["select"] == c["border"], name
        assert c["outline"] == c["border"], name
        assert c["chrome"] == c["panel"], name


def test_dataterm_puts_khaki_in_the_chrome_and_black_in_the_seams():
    c = theme.THEMES["dataterm"]["colors"]
    assert c["chrome"] == "#877254"    # case plastic: title strip, detail bars
    assert c["outline"] == "#877254"   # the frame around a card
    assert c["select"] == "#877254"    # inverse-video selection band
    assert c["border"] == "#000000"    # the seams between panes
    assert c["bg"] == "#140F08"        # lit screen
    # .panel is every status widget, so `panel` carries body text: not the khaki.
    assert c["panel"] == "#1E1710"
    assert c["panel"] != c["chrome"], "khaki must not become a reading surface"
    assert c["select"] != c["border"], "black selection band would be invisible"
    assert c["outline"] != c["border"], "black card frames would be invisible"


def _contrast(a: str, b: str) -> float:
    def lin(c: int) -> float:
        f = c / 255
        return f / 12.92 if f <= 0.04045 else ((f + 0.055) / 1.055) ** 2.4

    def lum(h: str) -> float:
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


TEXT_TIERS = ("text", "muted", "accent", "accent_bright", "secondary", "ok", "err")


@pytest.mark.parametrize("name", ["vibranium-night", "vaporwave-mono", "dataterm"])
def test_every_text_tier_clears_aa_on_the_pane_background(name):
    """The tier below body text is what a mid-tone bg kills. Guard it."""
    c = theme.THEMES[name]["colors"]
    for tok in TEXT_TIERS:
        ratio = _contrast(c["bg"], c[tok])
        assert ratio >= 4.5, f"{name}.{tok} {c[tok]} on bg {c['bg']} = {ratio:.2f}:1"


def test_dataterm_card_fill_carries_text_too():
    """`.panel` is every status widget, so `panel` is a reading surface."""
    c = theme.THEMES["dataterm"]["colors"]
    for tok in TEXT_TIERS:
        ratio = _contrast(c["panel"], c[tok])
        assert ratio >= 4.5, f"dataterm.{tok} on panel {c['panel']} = {ratio:.2f}:1"


def test_vaporwave_muted_on_panel_is_a_known_pre_existing_near_miss():
    """Documented, not fixed — out of scope for the dataterm restyle.

    #7A7684 on #101012 is 4.30:1, just under AA. Nudging `muted` two steps
    lighter would clear it; that is a change to a theme nobody asked about.
    """
    c = theme.THEMES["vaporwave-mono"]["colors"]
    assert 4.2 <= _contrast(c["panel"], c["muted"]) < 4.5


@pytest.mark.parametrize("name", ["vibranium-night", "vaporwave-mono", "dataterm"])
def test_chrome_text_is_legible_on_chrome_in_every_theme(name):
    """The whole reason the token exists: chrome is near-black in two themes and
    a mid-tone khaki in the third, so the foreground goes opposite ways."""
    c = theme.THEMES[name]["colors"]
    ratio = _contrast(c["chrome"], c["chrome_text"])
    assert ratio >= 4.5, f"{name}: {c['chrome_text']} on {c['chrome']} = {ratio:.2f}:1"


def test_chrome_text_matches_body_text_where_chrome_is_just_the_panel():
    """Carved out of $text; unchanged for the two themes that never needed it."""
    for quiet in ("vibranium-night", "vaporwave-mono"):
        c = theme.THEMES[quiet]["colors"]
        assert c["chrome_text"] == c["text"], quiet
    dark = theme.THEMES["dataterm"]["colors"]
    assert dark["chrome_text"] != dark["text"], "amber on khaki is 2.51:1"


def test_chrome_carries_bold_labels_at_aa_large():
    """Khaki holds bold labels at AA-large, and frames a card visibly."""
    c = theme.THEMES["dataterm"]["colors"]
    assert _contrast(c["chrome"], c["bg"]) >= 3.0
    assert _contrast(c["chrome"], "#000000") >= 3.0   # black label on the strip
    assert _contrast(c["outline"], c["panel"]) >= 3.0  # frame reads against the card


def test_default_is_vibranium_night_unchanged():
    assert theme.ACTIVE == "vibranium-night"
    assert theme.PALETTE["bg"] == "#000000"
    assert theme.PALETTE["panel"] == "#0D1526"
    assert theme.PALETTE["accent"] == "#E3B341"
    assert theme.ACCENT == "#E3B341"
    assert theme.ERR == "#E05561"


def test_vaporwave_and_dataterm_signature_colors():
    assert theme.THEMES["vaporwave-mono"]["colors"]["accent"] == "#FF71CE"
    assert theme.THEMES["dataterm"]["colors"]["accent"] == "#FFD07A"
    assert theme.THEMES["dataterm"]["colors"]["text"] == "#FFB000"


def test_activate_switches_module_constants_and_restores():
    theme.activate("dataterm")
    try:
        assert theme.ACTIVE == "dataterm"
        assert theme.ACCENT == "#FFD07A" and theme.PALETTE["accent"] == "#FFD07A"
        assert theme.SECONDARY == "#E06A2C"
    finally:
        theme.activate("vibranium-night")
    assert theme.ACCENT == "#E3B341"


def test_activate_applies_color_overrides():
    theme.activate("vaporwave-mono", overrides={"accent": "#ff00aa"})
    try:
        assert theme.ACCENT == "#FF00AA"  # normalised to upper-case
        assert theme.TEXT == "#D8D4E0"    # untouched keys keep the theme value
    finally:
        theme.activate("vibranium-night")


def test_activate_rejects_unknown_theme_and_bad_override():
    with pytest.raises(ValueError, match="unknown theme"):
        theme.activate("neon-toaster")
    with pytest.raises(ValueError, match="accent"):
        theme.activate("dataterm", overrides={"accent": "pink"})
    assert theme.ACTIVE == "vibranium-night"  # failed activate leaves state alone


def test_title_case_per_theme():
    assert theme.title("Network") == "Network"           # vibranium: untouched
    theme.activate("dataterm")
    try:
        assert theme.title("Network") == "NETWORK"       # dataterm: upper
    finally:
        theme.activate("vibranium-night")


def test_css_variables_cover_every_token():
    vars_ = theme.css_variables()
    assert set(vars_) == TOKENS
    assert vars_["accent"] == theme.ACCENT


def test_selection_does_not_reuse_the_seam_colour():
    """A theme with black borders must still show a selected row."""
    css = theme.TCSS_PATH.read_text()
    for rule in ("datatable--cursor", "option-list--option-highlighted"):
        assert rule in css
    assert "$select" in css
    # `border` is now purely the tmux seam colour: consumed by bin/griot and
    # center.conf, never by the stylesheet. Cards use $outline instead.
    assert "$border" not in css
    assert "$outline" in css


def test_default_sound_per_theme():
    assert theme.THEMES["dataterm"]["sound"] == {"whir": True, "seek": True}
    for quiet in ("vibranium-night", "vaporwave-mono"):
        assert theme.THEMES[quiet]["sound"] == {"whir": False, "seek": False}


def test_default_sound_follows_the_active_theme():
    theme.activate("dataterm")
    try:
        assert theme.default_sound() == {"whir": True, "seek": True}
    finally:
        theme.activate("vibranium-night")
    assert theme.default_sound() == {"whir": False, "seek": False}


def test_tcss_uses_variables_not_hex():
    css = theme.TCSS_PATH.read_text()
    assert not re.search(r"#[0-9A-Fa-f]{6}", css), "stylesheet must not hardcode colours"
    for tok in ("bg", "panel", "chrome", "outline", "select", "text", "accent",
                "accent_bright"):
        assert f"${tok}" in css


def test_default_animation_per_theme():
    assert theme.THEMES["vibranium-night"]["animation"]["style"] == "beads"
    assert theme.THEMES["vaporwave-mono"]["animation"]["style"] == "scope"
    assert theme.THEMES["dataterm"]["animation"] == {"style": "glyphs", "glyph_set": "hex"}


def test_warp_yaml_carries_palette():
    y = theme.warp_yaml("vaporwave-mono")
    assert "name: Griot Vaporwave Mono" in y
    assert "accent: '#FF71CE'" in y
    assert "background: '#000000'" in y
    assert "foreground: '#D8D4E0'" in y
    # the 16-colour block must be present for Warp to load it
    for k in ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"):
        assert f"{k}: '#" in y


def test_render_template_substitutes_tokens_of_active_theme():
    theme.activate("vaporwave-mono")
    try:
        out = theme.render_template('status-style "bg={{bg}},fg={{muted}}" x={{accent_bright}}')
        assert out == 'status-style "bg=#000000,fg=#7A7684" x=#FFA6E1'
    finally:
        theme.activate("vibranium-night")


def test_render_template_rejects_unknown_token_and_leaves_hash_formats_alone():
    with pytest.raises(ValueError, match="unknown colour token 'neon'"):
        theme.render_template("{{neon}}")
    # tmux format strings like #[fg=...] and #I #W must pass through untouched
    assert theme.render_template("#[fg={{accent}}] #I #W") == f"#[fg={theme.ACCENT}] #I #W"


def test_shipped_templates_have_no_hex_and_render_clean(tmp_path):
    for rel in ("tmux/center.conf", "styles/glow.json"):
        src = (theme.REPO_ROOT / rel).read_text()
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", src), f"{rel} must use {{{{token}}}} placeholders"
        out = theme.render_template(src)
        assert "{{" not in out and theme.ACCENT in out


def test_write_generated_assets(tmp_path):
    paths = theme.write_generated(tmp_path)
    assert {p.name for p in paths} == {"center.conf", "glow.json"}
    for p in paths:
        assert p.exists() and "{{" not in p.read_text()


# ------------------------------------------------------- terminal ramp ------

def test_dataterm_declares_an_amber_ramp_with_no_repeated_slot():
    ramp = theme.terminal_ramp("dataterm")
    assert set(ramp) == {"normal", "bright"}
    for group in ramp.values():
        assert set(group) == set(theme.ANSI_SLOTS)
    every = [*ramp["normal"].values(), *ramp["bright"].values()]
    assert len(every) == len(set(every)), "deriving the ramp put one hex in two slots"


def _lum(h: str) -> float:
    def lin(c: int) -> float:
        f = c / 255
        return f / 12.92 if f <= 0.04045 else ((f + 0.055) / 1.055) ** 2.4
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def test_every_bright_rung_is_lighter_than_its_normal_twin():
    ramp = theme.terminal_ramp("dataterm")
    for slot in theme.ANSI_SLOTS:
        n, b = ramp["normal"][slot], ramp["bright"][slot]
        assert _lum(b) > _lum(n), f"bright {slot} {b} is not lighter than {n}"


def test_every_ramp_rung_is_legible_on_the_dataterm_background():
    """`black` is a background slot; everything else is text at some point."""
    bg = theme.THEMES["dataterm"]["colors"]["bg"]
    ramp = theme.terminal_ramp("dataterm")
    for group in ramp.values():
        for slot, hexv in group.items():
            if slot == "black":
                continue
            assert _contrast(bg, hexv) >= 4.5, f"{slot} {hexv} on {bg}"


@pytest.mark.parametrize("name", ["vibranium-night", "vaporwave-mono"])
def test_the_other_themes_keep_the_derived_ramp(name):
    c = theme.THEMES[name]["colors"]
    ramp = theme.terminal_ramp(name)
    assert ramp["normal"]["black"] == c["panel"]
    assert ramp["normal"]["white"] == c["text"]
    assert ramp["bright"]["white"] == "#FFFFFF"
    assert ramp["bright"]["yellow"] == c["accent_bright"]


def test_warp_yaml_uses_the_declared_ramp():
    y = theme.warp_yaml("dataterm")
    assert "name: Griot Dataterm" in y
    assert "background: '#140F08'" in y
    assert "foreground: '#FFB000'" in y
    assert "red: '#DE4822'" in y      # declared normal red
    assert "red: '#FF3B14'" in y      # declared bright red
    assert "#FFFFFF" not in y, "the amber ramp has no pure white"


def test_tmux_flag_honours_an_explicit_name(capsys):
    """--name used to be silently ignored by --tmux."""
    theme.main(["--tmux", "--name", "dataterm"])
    border, accent = capsys.readouterr().out.split()
    assert border == "#000000" and accent == "#FFD07A"
    theme.main(["--tmux", "--name", "vibranium-night"])
    border, accent = capsys.readouterr().out.split()
    assert border == "#1E3A5F" and accent == "#E3B341"
    theme.activate("vibranium-night")
