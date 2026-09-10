"""[brain] configuration, cache paths, and the params file the hook reads.

The hook is plain sh and must not parse TOML, so `write_params()` renders the
resolved config as shell assignments — the same contract `sound.write_params()`
uses, and for the same reason: `resolve()` stays the only place enablement is
decided.
"""
from __future__ import annotations

import os
from pathlib import Path

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "griot" / "brain"
SPOOL_FILE = CACHE_DIR / "events"
PARAMS_FILE = CACHE_DIR / "params"
PID_FILE = CACHE_DIR / "pid"
GRAPH_CACHE = CACHE_DIR / "graph.json"

DEFAULTS: dict[str, object] = {
    "enabled": False,
    "fps": 12,
    "hops": 5,
}


def resolve(user: dict) -> dict:
    """Effective brain config: built-in defaults < user. Validates before returning."""
    cfg = {**DEFAULTS, **user}
    cfg["enabled"] = bool(cfg["enabled"])

    for key in ("fps", "hops"):
        try:
            value = int(cfg[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key}: expected a positive integer, got {cfg[key]!r}")
        if value < 1:
            raise ValueError(f"{key}: expected a positive integer, got {value!r}")
        cfg[key] = value
    return cfg


def write_params(cfg: dict, path: Path | None = None) -> Path:
    """Render the resolved config as shell assignments for bin/griot-disk.

    `enabled` is rendered as `brain_enabled` — not `enabled` — so sourcing
    this file cannot collide with the sound params' own `enabled`. `spool`
    is single-quoted so a HOME containing a space does not break the source.
    """
    target = Path(path) if path is not None else PARAMS_FILE
    body = (f"brain_enabled={1 if cfg['enabled'] else 0}\n"
            f"spool='{SPOOL_FILE}'\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return target
