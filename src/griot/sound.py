"""The drive: a synthesized hard-disk whir, so the pane sounds like it is thinking.

Nothing is shipped as a binary. A 5400rpm platter is a 90 Hz fundamental, so the
whir is that sine plus three harmonics, a slow bearing wobble, and a lowpassed
air bed — written once to `~/.cache/griot/sound/` with the stdlib `wave` module.
Head seeks are short bandpassed noise bursts on a randomised rhythm.

`SAMPLE_RATE / PLATTER_HZ` is exactly 245 frames, so a whole number of
revolutions is also a whole number of frames. That is what lets the loop wrap
without a click: the tone's phase comes back to where it started, and the noise
bed — which cannot wrap on its own — is cross-faded onto its own tail.

Two playback tiers. `AVPlayer` wraps AVFoundation's `AVAudioPlayer` with
`numberOfLoops = -1`, which loops in-process and genuinely gaplessly — no
process churn, no supervisor, nothing to orphan. `AfplayPlayer` is the fallback
where PyObjC is missing: `afplay` has no loop flag, so a supervisor thread
relaunches it and you hear a few ms of silence at the seam.

Off unless `[sound] enabled` is set, and only Dataterm asks for it (see
`theme.default_sound`).
"""
from __future__ import annotations

import atexit
import math
import os
import random
import shutil
import signal
import subprocess
import threading
import time
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 22050
RPM = 5400
PLATTER_HZ = RPM / 60.0                          # 90.0
PERIOD_FRAMES = int(SAMPLE_RATE / PLATTER_HZ)    # 245, exactly

WHIR_SECONDS = 20.0
CLICK_VARIANTS = 3          # so the idle tick is not a metronome sample
SYNTH_VERSION = "v2"
CACHE_DIR = Path.home() / ".cache" / "griot" / "sound"
# Mute lives on disk, not in memory: the tasks and status panes are separate
# processes (bin/griot send-keys into two tmux panes), so an in-process flag
# would only silence half the drive. One stat per one-shot is the whole cost.
MUTE_FLAG = CACHE_DIR / "muted"

THREAD_NAME = "griot-whir"
PREP_THREAD_NAME = "griot-synth"
TICK_THREAD_NAME = "griot-tick"
SEEK_DEBOUNCE = 0.35        # a burst of state changes is one seek, not twelve
CLICK_DEBOUNCE = 0.12       # a click is short; only collapse true simultaneity
MIN_PLAY_SECONDS = 0.2      # anything shorter means afplay failed; back off

DEFAULTS: dict[str, object] = {
    "enabled": False,       # opt-in: this is a thing you choose to hear
    "volume": 0.15,
    "whir": True,
    "seek": True,
    "clicks": True,
    "click_min": 4.0,       # idle tick interval, randomised in [min, max]
    "click_max": 20.0,
}


def resolve(theme_default: dict, user: dict) -> dict:
    """Effective sound config: built-in defaults < theme default < user."""
    cfg = {**DEFAULTS, **theme_default, **user}
    try:
        vol = float(cfg["volume"])
    except (TypeError, ValueError):
        raise ValueError(f"volume: expected a number from 0.0 to 1.0, got {cfg['volume']!r}")
    if not 0.0 <= vol <= 1.0:
        raise ValueError(f"volume: expected 0.0 to 1.0, got {vol!r}")
    cfg["volume"] = vol
    for flag in ("enabled", "whir", "seek", "clicks"):
        cfg[flag] = bool(cfg[flag])
    lo, hi = float(cfg["click_min"]), float(cfg["click_max"])
    if lo <= 0 or hi < lo:
        raise ValueError(f"click_min/click_max: need 0 < min <= max, got {lo} / {hi}")
    cfg["click_min"], cfg["click_max"] = lo, hi
    return cfg


# ---------------------------------------------------------------- synthesis --

def loop_frames(seconds: float, rate: int = SAMPLE_RATE) -> int:
    """Frames for `seconds`, snapped down to a whole number of revolutions."""
    period = int(rate / PLATTER_HZ)
    revolutions = max(1, round(seconds * PLATTER_HZ))
    return revolutions * period


def _lowpass(xs: list[float], cutoff: float, rate: int) -> list[float]:
    dt = 1.0 / rate
    a = (2 * math.pi * cutoff * dt) / (1 + 2 * math.pi * cutoff * dt)
    out, y = [], 0.0
    for x in xs:
        y += a * (x - y)
        out.append(y)
    return out


def _highpass(xs: list[float], cutoff: float, rate: int) -> list[float]:
    dt = 1.0 / rate
    rc = 1.0 / (2 * math.pi * cutoff)
    a = rc / (rc + dt)
    out, prev_x, y = [], 0.0, 0.0
    for x in xs:
        y = a * (y + x - prev_x)
        prev_x = x
        out.append(y)
    return out


def _to_int16(xs: list[float], peak: float = 0.85) -> list[int]:
    loudest = max((abs(x) for x in xs), default=0.0) or 1.0
    scale = peak * 32767 / loudest
    return [max(-32768, min(32767, int(x * scale))) for x in xs]


def whir_samples(seconds: float = WHIR_SECONDS, rate: int = SAMPLE_RATE,
                 seed: int = 0) -> list[int]:
    """A seamless platter loop: hum + harmonics + bearing wobble + air."""
    n = loop_frames(seconds, rate)
    rng = random.Random(seed)

    # Tone. Phase closes exactly at n because n is a whole number of periods.
    harmonics = ((1, 1.0), (2, 0.42), (3, 0.20), (5, 0.07))
    tone = [0.0] * n
    for mult, amp in harmonics:
        w = 2 * math.pi * PLATTER_HZ * mult / rate
        for i in range(n):
            tone[i] += amp * math.sin(w * i)

    # Bearing wobble — a whole number of cycles per loop, so it wraps too.
    wobble_cycles = max(1, round(0.75 * n / rate))
    for i in range(n):
        tone[i] *= 1.0 + 0.18 * math.sin(2 * math.pi * wobble_cycles * i / n)

    # Air bed. Generated n+fade long so the head can cross-fade onto the tail:
    # noise[n] genuinely follows noise[n-1], which is what removes the seam.
    fade = min(512, n // 4)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(n + fade)]
    air = _lowpass(raw, 900.0, rate)
    bed = air[:n]
    for i in range(fade):
        t = i / fade
        bed[i] = air[i] * t + air[n + i] * (1.0 - t)

    return _to_int16([tone[i] + 0.38 * bed[i] for i in range(n)])


def seek_samples(rate: int = SAMPLE_RATE, seed: int = 0) -> list[int]:
    """Head chatter: 3-5 sharp clicks with real silence between them."""
    rng = random.Random(seed)
    tau = 0.006                     # ~6ms decay, so the gaps are genuinely quiet
    bursts = []
    cursor = 0.0
    for _ in range(rng.randint(3, 5)):
        cursor += rng.uniform(0.04, 0.10)          # gap
        length = rng.uniform(0.02, 0.05)
        bursts.append((cursor, length, rng.uniform(0.7, 1.0)))
        cursor += length
    n = int((cursor + 0.05) * rate)

    buf = [0.0] * n
    for start, length, gain in bursts:
        i0 = int(start * rate)
        for k in range(int(length * rate)):
            if i0 + k >= n:
                break
            env = math.exp(-(k / rate) / tau)
            buf[i0 + k] += gain * env * rng.uniform(-1.0, 1.0)

    voiced = _lowpass(_highpass(buf, 700.0, rate), 3800.0, rate)
    return _to_int16(voiced, peak=0.8)


def click_samples(rate: int = SAMPLE_RATE, seed: int = 0) -> list[int]:
    """One actuator thunk: a 2ms noise excitation, then two damped resonances.

    The high ring is the head arm hitting its stop; the low one is the chassis
    answering. Every variant jitters both frequencies and both decay times, so
    three cached variants never read as the same sample fired twice.
    """
    rng = random.Random(seed)
    f_ring = rng.uniform(950.0, 1350.0)
    f_thunk = rng.uniform(150.0, 220.0)
    tau_ring = rng.uniform(0.008, 0.016)
    tau_thunk = rng.uniform(0.018, 0.030)
    n = int(0.045 * rate)
    excite = max(1, int(0.002 * rate))

    buf = []
    for i in range(n):
        t = i / rate
        v = math.exp(-t / tau_ring) * math.sin(2 * math.pi * f_ring * t)
        v += 0.55 * math.exp(-t / tau_thunk) * math.sin(2 * math.pi * f_thunk * t)
        if i < excite:
            v += 1.4 * rng.uniform(-1.0, 1.0) * (1.0 - i / excite)
        buf.append(v)
    return _to_int16(_highpass(buf, 120.0, rate), peak=0.75)


# ------------------------------------------------------------------ assets --

def write_wav(path: Path | str, samples: list[int], rate: int = SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(array("h", samples).tobytes())
    return path


def ensure_assets(directory: Path | str | None = None,
                  whir_seconds: float = WHIR_SECONDS,
                  rate: int = SAMPLE_RATE) -> dict:
    """Generate any missing wav. Cheap to re-call; `clicks` is a list of variants."""
    d = Path(directory) if directory is not None else CACHE_DIR
    v = SYNTH_VERSION
    singles = {"whir": (d / f"whir-{v}.wav", lambda: whir_samples(whir_seconds, rate)),
               "seek": (d / f"seek-{v}.wav", lambda: seek_samples(rate))}
    clicks = [(d / f"click{i + 1}-{v}.wav", (lambda i=i: click_samples(rate, seed=i + 1)))
              for i in range(CLICK_VARIANTS)]
    for path, make in [*singles.values(), *clicks]:
        if not path.exists() or path.stat().st_size <= 44:
            write_wav(path, make(), rate)
    return {"whir": singles["whir"][0], "seek": singles["seek"][0],
            "clicks": [path for path, _ in clicks]}


# ---------------------------------------------------------------- playback --

class _AVHandle:
    """Keeps the AVAudioPlayer alive — drop the reference and playback stops."""

    def __init__(self, player) -> None:
        self._player = player

    def poll(self):
        return None if self._player.isPlaying() else 0

    def wait(self, timeout=None) -> None:
        if timeout:
            time.sleep(timeout)

    def stop(self) -> None:
        self._player.stop()


class AVPlayer:
    """AVFoundation. `numberOfLoops = -1` is a real gapless loop, in-process.

    Verified headless: no NSRunLoop needed, `stop()` is immediate, and there is
    no child process to orphan. This is the preferred tier.
    """

    supports_loop = True

    def __init__(self) -> None:
        self._av = None

    def _framework(self):
        if self._av is None:
            import AVFoundation
            self._av = AVFoundation
        return self._av

    def available(self) -> bool:
        try:
            self._framework()
            from Foundation import NSURL  # noqa: F401
            return True
        except Exception:
            return False

    def play(self, path: Path, volume: float, loop: bool = False):
        av = self._framework()
        from Foundation import NSURL
        url = NSURL.fileURLWithPath_(str(path))
        player, err = av.AVAudioPlayer.alloc().initWithContentsOfURL_error_(url, None)
        if player is None:
            raise OSError(f"AVAudioPlayer could not open {path}: {err}")
        player.setNumberOfLoops_(-1 if loop else 0)
        player.setVolume_(float(volume))
        player.prepareToPlay()
        if not player.play():
            raise OSError(f"AVAudioPlayer refused to play {path}")
        return _AVHandle(player)

    def kill(self, handle) -> None:
        try:
            handle.stop()
        except Exception:
            pass


class AfplayPlayer:
    """macOS `afplay`. Children get their own session so we can kill the group.

    Has no loop flag, so `loop=True` is a lie it cannot tell — the engine
    supervises the relaunch instead, and you hear the seam.
    """

    BINARY = "afplay"
    supports_loop = False

    def available(self) -> bool:
        return shutil.which(self.BINARY) is not None

    def play(self, path: Path, volume: float, loop: bool = False):
        return subprocess.Popen(
            [self.BINARY, "-v", f"{volume:.3f}", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def kill(self, proc) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass


def best_player():
    """AVFoundation if PyObjC is installed, else afplay, else a dead no-op."""
    for candidate in (AVPlayer(), AfplayPlayer()):
        if candidate.available():
            return candidate
    return AfplayPlayer()      # unavailable; the engine checks and stays silent


class SoundEngine:
    """Owns the whir thread and the seek one-shots.

    The one failure mode that actually matters is an orphaned looping `afplay`
    you cannot find, so teardown runs from `stop()`, from `atexit`, and kills
    the child's whole process group.
    """

    def __init__(self, cfg: dict, player=None, assets: dict | None = None,
                 ticker: bool = True, mute_flag: Path | None = None) -> None:
        self.cfg = dict(cfg)
        self._player = player if player is not None else best_player()
        self._assets = dict(assets) if assets else None
        self._ticks = ticker      # only one pane should own the idle ticker
        self._mute_flag = Path(mute_flag) if mute_flag is not None else MUTE_FLAG
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None   # afplay supervisor only
        self._ticker: threading.Thread | None = None
        self._proc = None
        self._loop_handle = None                       # AVAudioPlayer, looping itself
        self._oneshots: list = []
        self._last_seek = 0.0
        self._last_click = 0.0
        self._rng = random.Random()
        self._lock = threading.RLock()
        self._assets_lock = threading.Lock()
        self._at_exit = False

    # -- state ----------------------------------------------------------------
    @property
    def volume(self) -> float:
        return float(self.cfg["volume"])

    @property
    def muted(self) -> bool:
        """Read through to the flag file, so the other pane's `m` is honoured."""
        try:
            return self._mute_flag.exists()
        except OSError:
            return False

    def set_muted(self, value: bool) -> bool:
        try:
            if value:
                self._mute_flag.parent.mkdir(parents=True, exist_ok=True)
                self._mute_flag.touch()
            else:
                self._mute_flag.unlink(missing_ok=True)
        except OSError:
            pass
        return self.muted

    @property
    def running(self) -> bool:
        """True while the whir is audible, whichever tier is playing it."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            handle = self._loop_handle
        return handle is not None and handle.poll() is None

    @property
    def gapless(self) -> bool:
        return bool(getattr(self._player, "supports_loop", False))

    def _live(self) -> bool:
        return (bool(self.cfg["enabled"]) and not self.muted
                and self._player.available())

    def _paths(self) -> dict[str, Path]:
        """Synthesis is ~0.4s the first time ever, so only threads call this."""
        with self._assets_lock:
            if self._assets is None:
                self._assets = ensure_assets()
            return self._assets

    # -- ambient whir ---------------------------------------------------------
    def start(self) -> None:
        if not self._live():
            return
        if self.running:
            return
        self._stop.clear()
        if bool(self.cfg["whir"]):
            if self.gapless:
                # AVAudioPlayer loops itself; there is nothing to supervise.
                self._dispatch(self._begin_loop)
            else:
                with self._lock:
                    self._thread = threading.Thread(target=self._spin, name=THREAD_NAME,
                                                    daemon=True)
                    self._thread.start()   # generates the assets, then relaunches
        elif bool(self.cfg["seek"]) or bool(self.cfg["clicks"]):
            self._dispatch(self._paths)
        if bool(self.cfg["clicks"]) and self._ticks:
            with self._lock:
                if self._ticker is None or not self._ticker.is_alive():
                    self._ticker = threading.Thread(target=self._tick,
                                                    name=TICK_THREAD_NAME, daemon=True)
                    self._ticker.start()
        if not self._at_exit:
            atexit.register(self.stop)
            self._at_exit = True

    def _dispatch(self, fn) -> None:
        """Inline when the assets are ready, off-thread when synthesis is needed."""
        if self._assets is not None:
            fn()
        else:
            threading.Thread(target=fn, name=PREP_THREAD_NAME, daemon=True).start()

    def _begin_loop(self) -> None:
        try:
            paths = self._paths()
            if self._stop.is_set():
                return
            handle = self._player.play(paths["whir"], self.volume, loop=True)
            with self._lock:
                if self._stop.is_set():
                    self._kill(handle)
                    return
                self._loop_handle = handle
        except Exception:
            pass

    def _tick(self) -> None:
        """The drive ticking away to itself, on no schedule you can predict."""
        lo, hi = float(self.cfg["click_min"]), float(self.cfg["click_max"])
        while not self._stop.is_set():
            if self._stop.wait(self._rng.uniform(lo, hi)):
                return
            self.click()

    def _spin(self) -> None:
        path = self._paths()["whir"]
        fails = 0
        while not self._stop.is_set():
            began = time.monotonic()
            try:
                proc = self._player.play(path, self.volume)
            except Exception:
                fails += 1
                if fails >= 3 or self._stop.wait(0.5):
                    return
                continue
            with self._lock:
                self._proc = proc
            # Poll rather than block, so stop() gets us out within ~100ms even
            # if the child never exits on its own.
            while not self._stop.is_set():
                try:
                    proc.wait(timeout=0.1)
                except Exception:
                    pass
                if proc.poll() is not None:
                    break
            with self._lock:
                self._proc = None
            if self._stop.is_set():
                if proc.poll() is None:
                    self._kill(proc)
                return
            if time.monotonic() - began < MIN_PLAY_SECONDS:
                fails += 1
                if fails >= 3 or self._stop.wait(0.5):
                    return
            else:
                fails = 0

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc, thread, ticker = self._proc, self._thread, self._ticker
            handle, self._loop_handle = self._loop_handle, None
            self._proc = None
            self._thread = None
            self._ticker = None
            shots, self._oneshots = self._oneshots, []
        for target in [proc, handle, *shots]:
            if target is not None:
                self._kill(target)
        for t in (thread, ticker):
            if t is not None and t is not threading.current_thread():
                t.join(timeout=2.0)

    def _kill(self, proc) -> None:
        try:
            self._player.kill(proc)
        except Exception:
            pass

    # -- seek chatter ---------------------------------------------------------
    def seek(self) -> None:
        """Fire-and-forget. Called from a render path, so it swallows everything."""
        try:
            if not self._live() or not bool(self.cfg["seek"]):
                return
            now = time.monotonic()
            with self._lock:
                if now - self._last_seek < SEEK_DEBOUNCE:
                    return
                self._last_seek = now
                self._oneshots = [p for p in self._oneshots if p.poll() is None]
            paths = self._assets
            if paths is None:
                return      # still synthesizing; skip rather than block the render
            proc = self._player.play(paths["seek"], self.volume)
            with self._lock:
                self._oneshots.append(proc)
        except Exception:
            pass

    def click(self) -> None:
        """One thunk, from the idle ticker or a vault write. Same safety as seek."""
        try:
            if not self._live() or not bool(self.cfg["clicks"]):
                return
            now = time.monotonic()
            with self._lock:
                if now - self._last_click < CLICK_DEBOUNCE:
                    return
                self._last_click = now
                self._oneshots = [h for h in self._oneshots if h.poll() is None]
            paths = self._assets
            variants = (paths or {}).get("clicks") or []
            if not variants:
                return      # still synthesizing
            handle = self._player.play(self._rng.choice(variants), self.volume)
            with self._lock:
                self._oneshots.append(handle)
        except Exception:
            pass

    # -- mute -----------------------------------------------------------------
    def toggle_mute(self) -> bool:
        now_muted = self.set_muted(not self.muted)
        if now_muted:
            self.stop()
        else:
            self._stop.clear()
            self.start()
        return now_muted


# -------------------------------------------------------- module singleton --
# The animation hook calls `sound.seek()` unconditionally; with nothing
# installed that is a no-op, which is what keeps the widget tests silent.

_ENGINE: SoundEngine | None = None


def engine() -> SoundEngine | None:
    return _ENGINE


def install(cfg: dict, **kwargs) -> SoundEngine:
    global _ENGINE
    shutdown()
    _ENGINE = SoundEngine(cfg, **kwargs)
    _ENGINE.start()
    return _ENGINE


def shutdown() -> None:
    global _ENGINE
    eng, _ENGINE = _ENGINE, None
    if eng is not None:
        eng.stop()


def seek() -> None:
    eng = _ENGINE
    if eng is not None:
        eng.seek()


def click() -> None:
    eng = _ENGINE
    if eng is not None:
        eng.click()


def muted() -> bool:
    """The shared state, engine or not — the footer renders from this."""
    eng = _ENGINE
    if eng is not None:
        return eng.muted
    try:
        return MUTE_FLAG.exists()
    except OSError:
        return False


def toggle_mute() -> bool:
    eng = _ENGINE
    return eng.toggle_mute() if eng is not None else False
