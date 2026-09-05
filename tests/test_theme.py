from griot import theme


def test_palette_has_all_tokens():
    assert set(theme.PALETTE) == {
        "bg", "panel", "border", "gold", "gold_bright",
        "text", "muted", "ok", "err",
    }


def test_canonical_hexes():
    assert theme.PALETTE["bg"] == "#000000"  # Vibranium Night: blend with terminal
    assert theme.PALETTE["panel"] == "#0D1526"
    assert theme.PALETTE["gold"] == "#E3B341"
    assert theme.GOLD == "#E3B341"
    assert theme.ERR == "#E05561"


def test_tcss_exists_and_uses_palette():
    css = theme.TCSS_PATH.read_text()
    assert "#000000" in css and "#E3B341" in css
    assert "#0A1428" not in css  # old navy background fully retired
