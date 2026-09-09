"""griot-brain — the animator process.

Detached, with its own lifecycle: it must not block a pane's event loop and
must be able to die without taking a pane with it. Every failure path logs
once and exits 0, because a background animation is never worth breaking the
workstation over.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from griot import config as config_module
from griot import theme

from . import graph as graph_module
from . import kitty, settings
from .events import Spool, resolve as resolve_events
from .pulse import Pulses
from .render import frame
from .sim import Sim

FOCUS_POLL_SECONDS = 1.0

# Damping in Sim.step() is applied once per call, not scaled by dt — so a
# larger dt (a lower fps) moves the graph further per call without a
# compensating increase in damping. Measured on the real 986-node graph with
# dt = 1/fps: 8.60 px/sec of drift at idle (3fps) against 2.14 px/sec active
# (15fps) — four times faster while idle, the opposite of "idle drifts
# calmly, an active burst quickens". A fixed step makes fps control how
# OFTEN the world advances, not how far.
SIM_STEP = 1.0 / 15.0   # fixed: fps controls how OFTEN we step, not how far

WRITE_IMPULSE = 30.0


class Brain:
    def __init__(self, graph, cfg, client, spool_path) -> None:
        self.graph = graph
        self.cfg = cfg
        self.client = client
        self.spool = Spool(Path(spool_path))
        self.sim = Sim(graph, cfg["size"], seed=0)
        self.pulses = Pulses(graph, hops=cfg["hops"])
        self.active_until = 0.0
        self.fps = float(cfg["fps_idle"])
        self._focused = True
        self._focus_checked = 0.0

    def _refresh_focus(self, now: float) -> None:
        if now - self._focus_checked >= FOCUS_POLL_SECONDS:
            self._focus_checked = now
            self._focused = self.client.focused()

    def tick(self) -> None:
        now = time.monotonic()
        self._refresh_focus(now)
        for node, kind in resolve_events(self.spool.read_new(), self.graph):
            self.pulses.hit(node, kind)
            if kind == "write" and self._focused:
                self.sim.impulse(node, WRITE_IMPULSE)
            self.active_until = now + self.cfg["active_window"]

        self.fps = float(self.cfg["fps_active"] if now < self.active_until
                         else self.cfg["fps_idle"])

        if not self._focused:
            # Keep draining the pulse queue — it is the only thing that clears
            # _pending, and without it an unfocused hour blooms all at once on
            # return. Skip the simulation and the frame; those are the cost.
            self.pulses.advance(SIM_STEP)
            return

        self.sim.step(SIM_STEP)
        self.pulses.advance(SIM_STEP)
        self.client.send_png(
            frame(self.graph, self.sim, self.pulses, theme.PALETTE, self.cfg["size"]))

    def run(self) -> None:
        while True:
            started = time.monotonic()
            self.tick()
            time.sleep(max(0.0, 1.0 / self.fps - (time.monotonic() - started)))

    def shutdown(self) -> None:
        try:
            self.client.clear()
        except OSError:
            pass        # kitty already gone — there is no background left to clear,
                        # and a traceback out of the exit path helps nobody
        finally:
            self.client.close()


def _fail(message: str) -> int:
    print(f"griot-brain: {message}", file=sys.stderr)
    return 0        # never break the workstation over a background animation


# The spec lists "numpy missing" as a degradation case. It cannot arise here:
# numpy is a declared dependency, so `uv run griot-brain` either has it or
# fails to launch at all — and the launcher discards that failure. There is
# nothing to catch at runtime.


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    conf = config_module.load_config()
    theme.activate_from_config(conf)
    try:
        cfg = settings.resolve(conf.brain)
    except ValueError as e:
        return _fail(f"config: {e}")
    settings.write_params(cfg)
    if not cfg["enabled"]:
        return 0

    address = kitty.discover_socket(cfg["socket"])
    if address is None:
        return _fail("no kitty socket; set listen_on in kitty.conf "
                     "with allow_remote_control socket-only")
    try:
        client = kitty.KittyBackground(address)
    except OSError as e:
        return _fail(f"cannot reach kitty at {address}: {e}")

    try:
        graph = graph_module.load_or_build(conf.vault_path, settings.GRAPH_CACHE)
    except OSError as e:
        client.close()
        return _fail(f"cannot read the vault at {conf.vault_path}: {e}")

    if graph.n == 0:
        client.close()
        return _fail(f"no notes found under {conf.vault_path} — check vault_path")

    brain = Brain(graph, cfg, client, settings.SPOOL_FILE)

    if "--selftest" in argv:
        try:
            for _ in range(3):
                brain.tick()
            brain.shutdown()
        except OSError as e:
            return _fail(f"selftest failed: {e}")
        print(f"griot-brain: ok — {graph.n} nodes, {len(graph.edges)} edges")
        return 0

    settings.PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.PID_FILE.write_text(str(os.getpid()))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        brain.run()
    except OSError as e:
        return _fail(f"kitty went away: {e}")
    finally:
        brain.shutdown()
        settings.PID_FILE.unlink(missing_ok=True)
    return 0
