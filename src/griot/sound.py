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
# Rendered for bin/griot-disk, the Claude Code hook. The hook is plain sh so it
# never pays Python's ~170ms startup on every tool call; this file keeps
# resolve() the only place enabled/volume/gain are actually decided.
PARAMS_FILE = CACHE_DIR / "params"

THREAD_NAME = "griot-whir"
PREP_THREAD_NAME = "griot-synth"
TICK_THREAD_NAME = "griot-tick"
SEEK_DEBOUNCE = 0.35        # a burst of state changes is one seek, not twelve
CLICK_DEBOUNCE = 0.12       # a click is short; only collapse true simultaneity
WRITE_DEBOUNCE = 0.25       # a write burst is ~400ms; do not let them stack
READ_DEBOUNCE = 0.20
MIN_PLAY_SECONDS = 0.2      # anything shorter means afplay failed; back off

DEFAULTS: dict[str, object] = {
    "enabled": False,       # opt-in: this is a thing you choose to hear
    "volume": 0.15,
    "whir": True,
    "seek": True,
    "clicks": True,
    "click_min": 4.0,       # idle tick interval, randomised in [min, max]
    "click_max": 20.0,
    # One-shots are transients against a continuous bed: a click is only 0.32x
    # the whir's RMS at the same volume, so it needs lifting to be heard at all.
    "one_shot_gain": 1.8,
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
    gain = float(cfg["one_shot_gain"])
    if gain <= 0:
        raise ValueError(f"one_shot_gain: expected a positive number, got {gain!r}")
    cfg["one_shot_gain"] = gain
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


def _render_impact(buf: list[float], at: int, rate: int, rng: random.Random,
                   gain: float = 1.0, ring: tuple = (950.0, 1350.0),
                   thunk: tuple = (150.0, 220.0), tau_ring: tuple = (0.008, 0.016),
                   tau_thunk: tuple = (0.018, 0.030), thunk_level: float = 0.55,
                   length: float = 0.045, excite: float = 0.002) -> None:
    """One actuator impact, summed into `buf` at frame `at`.

    A 2ms noise excitation, then two damped resonances: the high ring is the
    head arm hitting its stop, the low one is the chassis answering. Every
    impact jitters both frequencies and both decay times, so a burst never
    sounds like one sample repeated.
    """
    f_ring = rng.uniform(*ring)
    f_thunk = rng.uniform(*thunk)
    t_ring = rng.uniform(*tau_ring)
    t_thunk = rng.uniform(*tau_thunk)
    n = int(length * rate)
    ex = max(1, int(excite * rate))
    for i in range(n):
        if at + i >= len(buf):
            break
        t = i / rate
        v = math.exp(-t / t_ring) * math.sin(2 * math.pi * f_ring * t)
        v += thunk_level * math.exp(-t / t_thunk) * math.sin(2 * math.pi * f_thunk * t)
        if i < ex:
            v += 1.4 * rng.uniform(-1.0, 1.0) * (1.0 - i / ex)
        buf[at + i] += gain * v


def click_samples(rate: int = SAMPLE_RATE, seed: int = 0) -> list[int]:
    """One lone thunk — the drive ticking to itself while idle."""
    rng = random.Random(seed)
    buf = [0.0] * int(0.045 * rate)
    _render_impact(buf, 0, rate, rng)
    return _to_int16(_highpass(buf, 120.0, rate), peak=0.75)


def write_samples(rate: int = SAMPLE_RATE, seed: int = 0) -> list[int]:
    """A write: 3-6 head impacts over ~300-500ms, then the arm settling.

    One asset rather than four scheduled one-shots — the rhythm is baked in, so
    playing a write costs a single play() call and cannot drift or stack.
    """
    rng = random.Random(seed)
    impacts = rng.randint(3, 6)
    starts, cursor = [], 0.0
    for k in range(impacts):
        cursor += rng.uniform(0.040, 0.110)
        # the arm settles: later impacts land softer
        starts.append((cursor, rng.uniform(0.70, 1.0) * (1.0 - 0.10 * k)))
    buf = [0.0] * int((cursor + 0.09) * rate)
    for start, gain in starts:
        _render_impact(buf, int(start * rate), rate, rng, gain=gain,
                       thunk_level=0.75, tau_thunk=(0.020, 0.034))
    return _to_int16(_highpass(buf, 120.0, rate), peak=0.85)


def read_samples(rate: int = SAMPLE_RATE, seed: int = 0) -> list[int]:
    """A read: 2-3 lighter, higher, shorter taps. Reads do not settle a head.

    Deliberately quieter than a write at the same volume, because on a real
    drive a read is the lighter of the two operations.
    """
    rng = random.Random(seed)
    starts, cursor = [], 0.0
    for _ in range(rng.randint(2, 3)):
        cursor += rng.uniform(0.035, 0.080)
        starts.append((cursor, rng.uniform(0.55, 0.85)))
    buf = [0.0] * int((cursor + 0.05) * rate)
    for start, gain in starts:
        _render_impact(buf, int(start * rate), rate, rng, gain=gain,
                       ring=(1300.0, 1850.0), thunk_level=0.22,
                       tau_ring=(0.005, 0.010), tau_thunk=(0.010, 0.018),
                       length=0.030)
    return _to_int16(_highpass(buf, 120.0, rate), peak=0.60)


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


def write_params(cfg: dict, path: Path | None = None) -> Path:
    """Render the resolved sound config as shell assignments for the hook."""
    target = Path(path) if path is not None else PARAMS_FILE
    gain = min(1.0, float(cfg["volume"]) * float(cfg["one_shot_gain"]))
    body = (f"enabled={1 if cfg['enabled'] else 0}\n"
            f"clicks={1 if cfg['clicks'] else 0}\n"
            f"volume={float(cfg['volume']):.3f}\n"
            f"one_shot_volume={gain:.3f}\n"
            f"version={SYNTH_VERSION}\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return target


def ensure_assets(directory: Path | str | None = None,
                  whir_seconds: float = WHIR_SECONDS,
                  rate: int = SAMPLE_RATE) -> dict:
    """Generate any missing wav. Cheap to re-call; `clicks` is a list of variants."""
    d = Path(directory) if directory is not None else CACHE_DIR
    v = SYNTH_VERSION
    singles = {"whir": (d / f"whir-{v}.wav", lambda: whir_samples(whir_seconds, rate)),
               "seek": (d / f"seek-{v}.wav", lambda: seek_samples(rate))}
    families = {"clicks": ("click", click_samples), "writes": ("write", write_samples),
                "reads": ("read", read_samples)}
    variants: dict[str, list] = {}
    for key, (stem, maker) in families.items():
        variants[key] = [(d / f"{stem}{i + 1}-{v}.wav",
                          (lambda i=i, m=maker: m(rate, seed=i + 1)))
                         for i in range(CLICK_VARIANTS)]
    everything = [*singles.values(), *(pair for group in variants.values() for pair in group)]
    for path, make in everything:
        if not path.exists() or path.stat().st_size <= 44:
            write_wav(path, make(), rate)
    out = {"whir": singles["whir"][0], "seek": singles["seek"][0]}
    for key, group in variants.items():
        out[key] = [path for path, _ in group]
    return out


# ---------------------------------------------------------------- playback --

class _AVHandle:
    """One AVAudioPlayer, retriggered rather than recreated.

    An AVAudioPlayer holds its file open for its whole lifetime, and nothing
    reachable from Python shortens that: dropping the reference, calling stop(),
    and draining an autorelease pool were all measured to leave the descriptor
    open. So the players are cached and rewound instead — see AVPlayer.
    """

    def __init__(self, player) -> None:
        self._player = player

    def poll(self):
        return None if self._player.isPlaying() else 0

    def wait(self, timeout=None) -> None:
        if timeout:
            time.sleep(timeout)

    def retrigger(self, volume: float) -> None:
        self._player.setVolume_(float(volume))
        self._player.setCurrentTime_(0.0)
        if not self._player.play():
            raise OSError("AVAudioPlayer refused to play")

    def stop(self) -> None:
        self._player.stop()


class AVPlayer:
    """AVFoundation. `numberOfLoops = -1` is a real gapless loop, in-process.

    Verified headless: no NSRunLoop needed, `stop()` is immediate, and there is
    no child process to orphan. This is the preferred tier.

    One player is cached per (asset, loop) pair and rewound on each play, because
    a player created per one-shot leaks its file descriptor — the idle ticker
    alone leaked ~10/minute, which would exhaust the pane's limit within the
    hour. Cached, the open descriptors are bounded by the number of assets.
    """

    supports_loop = True

    def __init__(self) -> None:
        self._av = None
        self._cache: dict[tuple[str, bool], _AVHandle] = {}
        self._cache_lock = threading.Lock()

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

    def _load(self, path: Path, loop: bool) -> _AVHandle:
        av = self._framework()
        from Foundation import NSURL
        url = NSURL.fileURLWithPath_(str(path))
        player, err = av.AVAudioPlayer.alloc().initWithContentsOfURL_error_(url, None)
        if player is None:
            raise OSError(f"AVAudioPlayer could not open {path}: {err}")
        player.setNumberOfLoops_(-1 if loop else 0)
        player.prepareToPlay()
        return _AVHandle(player)

    def play(self, path: Path, volume: float, loop: bool = False):
        key = (str(path), bool(loop))
        with self._cache_lock:
            handle = self._cache.get(key)
            if handle is None:
                handle = self._load(path, loop)
                self._cache[key] = handle
        handle.retrigger(volume)
        return handle

    def kill(self, handle) -> None:
        # Stopped, not discarded: the cache keeps it for the next retrigger.
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
        self._last: dict[str, float] = {}      # per-sound debounce clocks
        self._rng = random.Random()
        self._lock = threading.RLock()
        self._assets_lock = threading.Lock()
        self._at_exit = False

    # -- state ----------------------------------------------------------------
    @property
    def volume(self) -> float:
        return float(self.cfg["volume"])

    @property
    def one_shot_volume(self) -> float:
        """Transients need lifting to be heard over the continuous whir."""
        return min(1.0, self.volume * float(self.cfg["one_shot_gain"]))

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
    # name -> (config flag, asset key, debounce seconds)
    ONE_SHOTS = {
        "seek": ("seek", "seek", SEEK_DEBOUNCE),
        "click": ("clicks", "clicks", CLICK_DEBOUNCE),
        "write": ("clicks", "writes", WRITE_DEBOUNCE),
        "read": ("clicks", "reads", READ_DEBOUNCE),
    }

    def _one_shot(self, name: str) -> None:
        """Fire-and-forget. Called from render paths, so it swallows everything."""
        try:
            flag, asset, debounce = self.ONE_SHOTS[name]
            if not self._live() or not bool(self.cfg[flag]):
                return
            now = time.monotonic()
            with self._lock:
                if now - self._last.get(name, 0.0) < debounce:
                    return
                self._last[name] = now
                self._oneshots = [h for h in self._oneshots if h.poll() is None]
            target = (self._assets or {}).get(asset)
            if isinstance(target, list):
                target = self._rng.choice(target) if target else None
            if target is None:
                return      # still synthesizing; skip rather than block the caller
            handle = self._player.play(target, self.one_shot_volume)
            with self._lock:
                # A cached player returns the same handle each time; only the
                # afplay tier hands back a fresh child worth tracking.
                if not any(h is handle for h in self._oneshots):
                    self._oneshots.append(handle)
        except Exception:
            pass

    def seek(self) -> None:
        """Head chatter — a status flipped."""
        self._one_shot("seek")

    def click(self) -> None:
        """One lone thunk — the idle ticker."""
        self._one_shot("click")

    def disk_write(self) -> None:
        """A burst — the vault was actually written to."""
        self._one_shot("write")

    def disk_read(self) -> None:
        """Lighter taps — the vault was actually read."""
        self._one_shot("read")

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
    try:
        write_params(cfg)      # so the Claude Code hook agrees with this config
    except OSError:
        pass
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


def disk_write() -> None:
    eng = _ENGINE
    if eng is not None:
        eng.disk_write()


def disk_read() -> None:
    eng = _ENGINE
    if eng is not None:
        eng.disk_read()


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
