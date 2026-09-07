"""Themes — the single source of truth for every colour in griot.

Three named palettes share one token vocabulary. `activate()` swaps the
module-level constants (BG, ACCENT, ...) that widgets read at render time,
and `css_variables()` feeds the same values into the Textual stylesheet as
`$bg`, `$accent`, ... so griot.tcss never carries a hex literal.

Vibranium and Vaporwave sit on true black so the panes blend into the terminal
and Claude; Dataterm deliberately does not — it is a lit amber screen in a khaki
case, so its `bg` is warm brown and its `border` is black.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Five surface roles the stylesheet used to collapse onto two tokens. Dataterm is
# the first theme that needs them apart: it wants black seams between panes but a
# *visible* frame around a card, and khaki bars but a dark reading surface.
#   bg      the pane background — the lit screen
#   panel   card fill (.panel is every status widget, so this carries body text)
#   chrome  filled bars: pane title strip, detail title, pane/detail footer
#   chrome_text  text ON chrome. Its own role because chrome is near-black in
#           two themes and a mid-tone khaki in the third, so the foreground has
#           to go the opposite direction. Inheriting $text left Dataterm at 2.51:1.
#   border  the seams between panes (tmux pane-border-style)
#   outline the frame drawn around a card
#   select  the highlighted row
TOKENS = ("bg", "panel", "chrome", "chrome_text", "border", "outline", "select",
          "text", "muted", "accent", "accent_bright", "secondary", "ok", "err")

THEMES: dict[str, dict] = {
    "vibranium-night": {
        "title": "Vibranium Night",
        "title_case": "none",
        "colors": {
            "bg": "#000000", "panel": "#0D1526", "chrome": "#0D1526",
            "chrome_text": "#C7D3E8",
            "border": "#1E3A5F", "outline": "#1E3A5F", "select": "#1E3A5F",
            "text": "#C7D3E8", "muted": "#8FA3C7",
            "accent": "#E3B341", "accent_bright": "#F0C75E", "secondary": "#4EC97B",
            "ok": "#4EC97B", "err": "#E05561",
        },
        "animation": {"style": "beads"},
        "sound": {"whir": False, "seek": False},
    },
    "vaporwave-mono": {
        "title": "Vaporwave Mono",
        "title_case": "none",
        "colors": {
            "bg": "#000000", "panel": "#101012", "chrome": "#101012",
            "chrome_text": "#D8D4E0",
            "border": "#2A2A30", "outline": "#2A2A30", "select": "#2A2A30",
            "text": "#D8D4E0", "muted": "#7A7684",
            "accent": "#FF71CE", "accent_bright": "#FFA6E1", "secondary": "#01CDFE",
            "ok": "#05FFA1", "err": "#FF3864",
        },
        "animation": {"style": "scope", "height": 2},
        "sound": {"whir": False, "seek": False},
    },
    # An amber-phosphor screen set into beige case plastic. The khaki #877254 caps
    # out at 4.6:1 against both black and white, so it is chrome and framing only —
    # body text sits on `panel`, a barely-lifted brown, at 9.7:1. `ok` stays in the
    # amber family so `err` owns the one hue break and genuinely jumps off the pane.
    "dataterm": {
        "title": "Dataterm",
        "title_case": "upper",
        "colors": {
            "bg": "#140F08", "panel": "#1E1710", "chrome": "#877254",
            # #877254 tops out at 4.57:1 and only pure black gets there.
            "chrome_text": "#000000",
            "border": "#000000", "outline": "#877254", "select": "#877254",
            "text": "#FFB000", "muted": "#C9922F",
            "accent": "#FFD07A", "accent_bright": "#FFF3D0", "secondary": "#E06A2C",
            "ok": "#FFCF6B", "err": "#FF3B14",
        },
        "animation": {"style": "glyphs", "glyph_set": "hex"},
        "sound": {"whir": True, "seek": True},
        # A single-phosphor monitor could not show green or blue, so the whole
        # ANSI ramp is amber: eight dim rungs, eight bright ones, no slot
        # repeated. Every rung except `black` (a background slot) clears 4.5:1
        # on this theme's bg, and every bright rung is lighter than its twin.
        "terminal": {
            "normal": {"black": "#1E1710", "red": "#DE4822", "green": "#B8862E",
                       "yellow": "#C9922F", "blue": "#9A7940", "magenta": "#D07A2A",
                       "cyan": "#A8842E", "white": "#FFB000"},
            "bright": {"black": "#877254", "red": "#FF3B14", "green": "#FFCF6B",
                       "yellow": "#FFD07A", "blue": "#DBA847", "magenta": "#FF8A3C",
                       "cyan": "#FFC24A", "white": "#FFF3D0"},
        },
    },
}

DEFAULT_THEME = "vibranium-night"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# --- active state (module constants read by widgets at render time) ---
ACTIVE: str = DEFAULT_THEME
PALETTE: dict[str, str] = dict(THEMES[DEFAULT_THEME]["colors"])
TITLE_CASE: str = "none"
BG = PANEL = CHROME = CHROME_TEXT = BORDER = OUTLINE = SELECT = TEXT = MUTED = \
    ACCENT = ACCENT_BRIGHT = SECONDARY = OK = ERR = ""

TCSS_PATH = Path(__file__).parent / "griot.tcss"
REPO_ROOT = Path(__file__).resolve().parents[2]
# Files outside Textual that carry theme colours as {{token}} placeholders.
# `write_generated()` renders them for the active theme; the launcher and
# griot-view read the rendered copies from REPO_ROOT/generated/.
TEMPLATES = {"tmux/center.conf": "center.conf", "styles/glow.json": "glow.json"}
GENERATED_DIR = REPO_ROOT / "generated"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _apply(name: str, colors: dict[str, str], title_case: str) -> None:
    g = globals()
    g["ACTIVE"] = name
    g["PALETTE"] = dict(colors)
    g["TITLE_CASE"] = title_case
    for tok in TOKENS:
        g[tok.upper()] = colors[tok]


def activate(name: str, overrides: dict[str, str] | None = None) -> None:
    """Make `name` the active theme, with optional per-token colour overrides.

    Validates everything before touching state, so a bad config leaves the
    previous theme in place.
    """
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}; choose from {', '.join(THEMES)}")
    colors = dict(THEMES[name]["colors"])
    for tok, val in (overrides or {}).items():
        if tok not in TOKENS:
            raise ValueError(f"unknown colour token {tok!r}; choose from {', '.join(TOKENS)}")
        if not isinstance(val, str) or not _HEX.match(val):
            raise ValueError(f"{tok}: expected a hex colour like #FF71CE, got {val!r}")
        colors[tok] = val.upper()
    _apply(name, colors, THEMES[name]["title_case"])


def activate_from_config(config) -> None:
    activate(config.theme_name, config.theme_colors)


def default_animation(name: str | None = None) -> dict:
    return dict(THEMES[name or ACTIVE]["animation"])


def default_sound(name: str | None = None) -> dict:
    """Which sounds a theme wants. Only Dataterm asks for the drive."""
    return dict(THEMES[name or ACTIVE]["sound"])


def title(text: str) -> str:
    """Panel titles honour the theme's typography (dataterm shouts)."""
    return text.upper() if TITLE_CASE == "upper" else text


def css_variables() -> dict[str, str]:
    return dict(PALETTE)


def render_template(text: str) -> str:
    """Replace {{token}} placeholders with the active palette's colours."""
    def sub(m: re.Match) -> str:
        tok = m.group(1)
        if tok not in PALETTE:
            raise ValueError(f"unknown colour token {tok!r} in template")
        return PALETTE[tok]
    return _PLACEHOLDER.sub(sub, text)


def write_generated(out_dir: Path | None = None) -> list[Path]:
    """Render every template for the active theme into out_dir; return the paths."""
    out_dir = out_dir or GENERATED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, name in TEMPLATES.items():
        target = out_dir / name
        target.write_text(render_template((REPO_ROOT / rel).read_text()))
        written.append(target)
    return written


ANSI_SLOTS = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")


def terminal_ramp(name: str) -> dict[str, dict[str, str]]:
    """The 16 ANSI colours for a theme.

    A theme may declare its own `terminal` ramp; Dataterm does, because deriving
    one from the palette put the same hex in two slots. Everything else gets the
    derived mapping it has always had.
    """
    t = THEMES[name]
    if "terminal" in t:
        return {k: dict(v) for k, v in t["terminal"].items()}
    c = t["colors"]
    return {
        "normal": {"black": c["panel"], "red": c["err"], "green": c["ok"],
                   "yellow": c["accent"], "blue": c["muted"], "magenta": c["accent"],
                   "cyan": c["secondary"], "white": c["text"]},
        "bright": {"black": c["select"], "red": c["err"], "green": c["ok"],
                   "yellow": c["accent_bright"], "blue": c["text"],
                   "magenta": c["accent_bright"], "cyan": c["secondary"],
                   "white": "#FFFFFF"},
    }


def warp_yaml(name: str) -> str:
    """A Warp terminal theme file matching the palette, so the chrome agrees."""
    t = THEMES[name]
    c = t["colors"]
    ramp = terminal_ramp(name)
    normal, bright = ramp["normal"], ramp["bright"]
    lines = [f"name: Griot {t['title']}", f"accent: '{c['accent']}'",
             f"background: '{c['bg']}'", f"foreground: '{c['text']}'",
             "details: darker", "terminal_colors:", "  normal:"]
    lines += [f"    {k}: '{v}'" for k, v in normal.items()]
    lines.append("  bright:")
    lines += [f"    {k}: '{v}'" for k, v in bright.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """griot-theme: print tmux colours, or write a Warp theme file."""
    from griot.config import load_config

    p = argparse.ArgumentParser(prog="griot-theme")
    p.add_argument("--tmux", action="store_true", help="print border and accent for tmux")
    p.add_argument("--warp", action="store_true", help="print the Warp theme yaml")
    p.add_argument("--write", action="store_true", help="with --warp: write to ~/.warp/themes")
    p.add_argument("--generate", action="store_true",
                   help="render tmux/glow assets for the active theme; print the directory")
    p.add_argument("--name", help="theme name (default: the configured one)")
    a = p.parse_args(argv)
    cfg = load_config()
    activate_from_config(cfg)
    name = a.name or cfg.theme_name
    if name != cfg.theme_name:
        activate(name, cfg.theme_colors)   # --name used to be ignored by --tmux
    if a.tmux:
        print(BORDER)
        print(ACCENT)
        return 0
    if a.generate:
        write_generated()
        print(GENERATED_DIR)
        return 0
    if a.warp:
        y = warp_yaml(name)
        if a.write:
            out = Path.home() / ".warp" / "themes" / f"griot-{name}.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(y)
            print(out)
        else:
            sys.stdout.write(y)
        return 0
    print(f"{ACTIVE}  ({', '.join(THEMES)})")
    return 0


activate(DEFAULT_THEME)

if __name__ == "__main__":
    raise SystemExit(main())
