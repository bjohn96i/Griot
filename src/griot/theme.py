"""Vibranium Night palette — the single source of truth for every color in griot.

True-black background so panes blend with the terminal (and Claude Code);
panels stay dark navy for Black Panther depth.
"""
from pathlib import Path

PALETTE: dict[str, str] = {
    "bg": "#000000",
    "panel": "#0D1526",
    "border": "#1E3A5F",
    "gold": "#E3B341",
    "gold_bright": "#F0C75E",
    "text": "#C7D3E8",
    "muted": "#8FA3C7",
    "ok": "#4EC97B",
    "err": "#E05561",
}

BG = PALETTE["bg"]
PANEL = PALETTE["panel"]
BORDER = PALETTE["border"]
GOLD = PALETTE["gold"]
GOLD_BRIGHT = PALETTE["gold_bright"]
TEXT = PALETTE["text"]
MUTED = PALETTE["muted"]
OK = PALETTE["ok"]
ERR = PALETTE["err"]

TCSS_PATH = Path(__file__).parent / "griot.tcss"
