"""The drive: synthesis is pure maths, playback is a mocked-out subprocess.

Nothing here ever spawns afplay — every engine test injects a fake player.
"""
import math
import threading
import time
import wave

import pytest

from griot import sound


# ------------------------------------------------------------- synthesis ----

def _goertzel(samples, freq, rate):
    """Magnitude of one frequency bin, so we can assert the platter tone."""
    n = len(samples)
    k = 2 * math.cos(2 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + k * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(s1 * s1 + s2 * s2 - k * s1 * s2) / n


def _rms(samples):
    return math.sqrt(sum(float(s) * s for s in samples) / max(1, len(samples)))


def test_loop_frames_snap_to_whole_platter_revolutions():
    # 22050 / 90 Hz is exactly 245 frames, so a whole number of revolutions is
    # also a whole number of frames — that is what lets the loop wrap cleanly.
    assert sound.SAMPLE_RATE % sound.PLATTER_HZ == 0
    for seconds in (1.0, 3.7, 4.0, 20.0):
        n = sound.loop_frames(seconds)
        assert n % sound.PERIOD_FRAMES == 0, seconds
        assert abs(n / sound.SAMPLE_RATE - seconds) < 1 / sound.PLATTER_HZ


def test_whir_has_the_requested_length_and_stays_inside_int16():
    s = sound.whir_samples(seconds=1.0)
    assert len(s) == sound.loop_frames(1.0)
    assert all(isinstance(x, int) for x in s[:64])
    assert max(s) <= 32767 and min(s) >= -32768
    assert max(abs(x) for x in s) > 8000, "should actually be audible"


def test_whir_is_deterministic_for_a_given_seed():
    assert sound.whir_samples(seconds=0.5, seed=7) == sound.whir_samples(seconds=0.5, seed=7)
    assert sound.whir_samples(seconds=0.5, seed=7) != sound.whir_samples(seconds=0.5, seed=8)


def test_whir_wraps_without_a_click_at_the_loop_point():
    """Tone phase wraps exactly; the noise bed is cross-faded to match."""
    s = sound.whir_samples(seconds=1.0)
    peak = max(abs(x) for x in s)
    seam = abs(s[-1] - s[0])
    # an interior sample-to-sample step, for scale
    interior = max(abs(s[i + 1] - s[i]) for i in range(1000, 2000))
    assert seam < 0.10 * peak, f"seam step {seam} vs peak {peak}"
    assert seam <= interior * 4, f"seam {seam} is an outlier vs interior {interior}"


def test_whir_is_dominated_by_the_platter_fundamental():
    s = sound.whir_samples(seconds=1.0)
    at_90 = _goertzel(s, sound.PLATTER_HZ, sound.SAMPLE_RATE)
    at_180 = _goertzel(s, sound.PLATTER_HZ * 2, sound.SAMPLE_RATE)
    at_5k = _goertzel(s, 5000.0, sound.SAMPLE_RATE)
    assert at_90 > at_180 > at_5k
    assert at_90 > 20 * at_5k, "a hard drive is not white noise"


def test_whir_wobbles_so_it_does_not_sound_like_a_test_tone():
    s = sound.whir_samples(seconds=4.0)
    chunk = len(s) // 8
    levels = [_rms(s[i * chunk:(i + 1) * chunk]) for i in range(8)]
    spread = (max(levels) - min(levels)) / max(levels)
    assert 0.02 < spread < 0.6, f"bearing rumble should breathe, got {spread:.3f}"


def test_seek_is_short_and_bursty_rather_than_continuous():
    s = sound.seek_samples(seed=3)
    seconds = len(s) / sound.SAMPLE_RATE
    assert 0.15 < seconds < 1.0, seconds
    assert max(abs(x) for x in s) > 4000
    windows = 24
    step = len(s) // windows
    levels = [_rms(s[i * step:(i + 1) * step]) for i in range(windows)]
    loud = max(levels)
    quiet = [lv for lv in levels if lv < 0.15 * loud]
    assert len(quiet) >= 3, "head seeks are discrete clicks, not a buzz"


def test_seek_is_deterministic_and_varies_by_seed():
    assert sound.seek_samples(seed=1) == sound.seek_samples(seed=1)
    assert sound.seek_samples(seed=1) != sound.seek_samples(seed=2)


# ----------------------------------------------------------------- assets ----

def test_write_wav_produces_a_real_mono_16_bit_file(tmp_path):
    s = sound.whir_samples(seconds=0.5)
    p = sound.write_wav(tmp_path / "w.wav", s)
    with wave.open(str(p), "rb") as f:
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2
        assert f.getframerate() == sound.SAMPLE_RATE
        assert f.getnframes() == len(s)


def test_ensure_assets_writes_both_and_is_idempotent(tmp_path):
    a = sound.ensure_assets(tmp_path, whir_seconds=0.5)
    assert set(a) == {"whir", "seek", "clicks"}
    assert len(a["clicks"]) == sound.CLICK_VARIANTS
    everything = [a["whir"], a["seek"], *a["clicks"]]
    assert all(p.exists() and p.stat().st_size > 44 for p in everything)
    stamps = {p: p.stat().st_mtime_ns for p in everything}
    again = sound.ensure_assets(tmp_path, whir_seconds=0.5)
    assert again == a
    assert {p: p.stat().st_mtime_ns for p in everything} == stamps, "regenerated needlessly"


def test_ensure_assets_regenerates_a_missing_file(tmp_path):
    a = sound.ensure_assets(tmp_path, whir_seconds=0.5)
    a["seek"].unlink()
    again = sound.ensure_assets(tmp_path, whir_seconds=0.5)
    assert again["seek"].exists()


# ------------------------------------------------------------------ config ----

def test_resolve_layers_defaults_then_theme_then_user():
    cfg = sound.resolve({"whir": True, "seek": True}, {})
    assert cfg["enabled"] is False, "sound is opt-in"
    assert cfg["whir"] is True and cfg["seek"] is True
    cfg = sound.resolve({"whir": True, "seek": True}, {"enabled": True, "whir": False})
    assert cfg["enabled"] is True and cfg["whir"] is False and cfg["seek"] is True


def test_resolve_rejects_a_volume_outside_the_afplay_range():
    with pytest.raises(ValueError, match="volume"):
        sound.resolve({}, {"volume": 4.0})
    with pytest.raises(ValueError, match="volume"):
        sound.resolve({}, {"volume": -0.1})


# ------------------------------------------------------------------ engine ----

class FakeProc:
    def __init__(self):
        self._done = threading.Event()
        self.killed = False

    def wait(self, timeout=None):
        self._done.wait(timeout)

    def poll(self):
        return 0 if self._done.is_set() else None

    def finish(self):
        self._done.set()


class FakePlayer:
    def __init__(self, ok=True, explode=False):
        self.ok = ok
        self.explode = explode
        self.calls = []
        self.procs = []
        self._lock = threading.Lock()

    def available(self):
        return self.ok

    def play(self, path, volume, loop=False):
        if self.explode:
            raise OSError("no audio device")
        with self._lock:
            self.calls.append((path.name, volume, loop))
        p = FakeProc()
        self.procs.append(p)
        return p

    def kill(self, proc):
        proc.killed = True
        proc.finish()

    def names(self):
        with self._lock:
            return [c[0] for c in self.calls]

    def loops(self):
        with self._lock:
            return [c[2] for c in self.calls]


class FakeLoopPlayer(FakePlayer):
    """Stands in for AVPlayer: loops natively, so no supervisor is needed."""

    supports_loop = True


def _assets(tmp_path):
    return {"whir": tmp_path / "whir.wav", "seek": tmp_path / "seek.wav",
            "clicks": [tmp_path / f"click{i}.wav" for i in (1, 2, 3)]}


def _wait(predicate, timeout=2.0):
    deadline = threading.Event()
    step = 0.005
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        deadline.wait(step)
        waited += step
    return False


def _engine(tmp_path, player, **over):
    # clicks off by default in these fixtures: the idle ticker would otherwise
    # race every assertion about what the player was asked to play. mute_flag is
    # redirected into tmp_path so a failing test can never leave the real drive
    # muted at ~/.cache/griot/sound/muted.
    cfg = sound.resolve({"whir": True, "seek": True},
                        {"enabled": True, "clicks": False, **over})
    return sound.SoundEngine(cfg, player=player, assets=_assets(tmp_path),
                             mute_flag=tmp_path / "muted")


def test_disabled_engine_never_touches_the_player(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, enabled=False)
    eng.start()
    eng.seek()
    try:
        assert pl.calls == []
        assert eng.running is False
    finally:
        eng.stop()


def test_engine_is_a_no_op_when_afplay_is_missing(tmp_path):
    pl = FakePlayer(ok=False)
    eng = _engine(tmp_path, pl)
    eng.start()
    eng.seek()
    try:
        assert pl.calls == []
        assert eng.running is False
    finally:
        eng.stop()


def test_start_plays_the_whir_and_relaunches_it_when_it_ends(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, volume=0.2)
    eng.start()
    try:
        assert _wait(lambda: pl.names() == ["whir.wav"]), pl.names()
        assert pl.calls[0][1] == 0.2
        pl.procs[0].finish()          # afplay reached the end of the file
        assert _wait(lambda: len(pl.names()) == 2), pl.names()
        assert pl.names() == ["whir.wav", "whir.wav"]
    finally:
        eng.stop()


def test_stop_kills_the_player_and_joins_the_thread(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl)
    eng.start()
    assert _wait(lambda: len(pl.procs) == 1)
    eng.stop()
    assert pl.procs[0].killed, "a looping afplay must never be orphaned"
    assert eng.running is False
    assert not any(t.name == sound.THREAD_NAME and t.is_alive()
                   for t in threading.enumerate())


def test_stop_is_safe_to_call_twice_and_without_a_start(tmp_path):
    eng = _engine(tmp_path, FakePlayer())
    eng.stop()
    eng.start()
    eng.stop()
    eng.stop()
    assert eng.running is False


def test_whir_false_starts_nothing_but_seek_still_works(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False)
    eng.start()
    try:
        eng.seek()
        assert _wait(lambda: pl.names() == ["seek.wav"]), pl.names()
    finally:
        eng.stop()


def test_seek_false_stays_silent_on_state_change(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False, seek=False)
    eng.start()
    try:
        eng.seek()
        assert pl.calls == []
    finally:
        eng.stop()


def test_seek_debounces_so_a_burst_of_changes_does_not_stack(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False)
    eng.start()
    try:
        for _ in range(12):
            eng.seek()
        assert _wait(lambda: pl.names() == ["seek.wav"])
        assert pl.names() == ["seek.wav"], "12 changes in a row is one seek"
    finally:
        eng.stop()


def test_seek_never_raises_into_the_render_path(tmp_path):
    eng = _engine(tmp_path, FakePlayer(explode=True), whir=False)
    eng.start()
    try:
        eng.seek()      # must not propagate OSError
    finally:
        eng.stop()


def test_toggle_mute_stops_the_whir_and_brings_it_back(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl)
    eng.start()
    try:
        assert _wait(lambda: len(pl.procs) == 1)
        assert eng.toggle_mute() is True
        assert eng.muted is True
        assert pl.procs[0].killed
        assert eng.running is False
        eng.seek()
        assert pl.names() == ["whir.wav"], "muted means silent"
        assert eng.toggle_mute() is False
        assert _wait(lambda: len(pl.procs) == 2)
        assert eng.running is True
    finally:
        eng.stop()


# ------------------------------------------------------- module singleton ----

def test_module_hooks_are_safe_with_nothing_installed():
    sound.shutdown()
    sound.seek()            # the animation hook calls this unconditionally
    assert sound.toggle_mute() is False
    assert sound.engine() is None


def test_install_and_shutdown_manage_the_singleton(tmp_path):
    pl = FakePlayer()
    cfg = sound.resolve({"whir": True, "seek": True}, {"enabled": True})
    eng = sound.install(cfg, player=pl, assets=_assets(tmp_path),
                        mute_flag=tmp_path / "muted")
    try:
        assert sound.engine() is eng
        assert _wait(lambda: len(pl.procs) == 1)
        sound.seek()
        assert _wait(lambda: "seek.wav" in pl.names())
    finally:
        sound.shutdown()
    assert sound.engine() is None
    assert pl.procs[0].killed


# ------------------------------------------------------------------ clicks ----

def test_click_is_a_short_sharp_decaying_transient():
    c = sound.click_samples(seed=1)
    seconds = len(c) / sound.SAMPLE_RATE
    assert 0.02 < seconds < 0.08, seconds
    head, tail = c[:len(c) // 6], c[-len(c) // 6:]
    assert _rms(head) > 8 * _rms(tail), "a click has to decay, not sustain"
    assert max(abs(x) for x in c) > 4000


def test_click_variants_are_distinct_and_deterministic():
    variants = [sound.click_samples(seed=i + 1) for i in range(sound.CLICK_VARIANTS)]
    assert len({tuple(v) for v in variants}) == sound.CLICK_VARIANTS
    assert variants[0] == sound.click_samples(seed=1)


def test_click_rings_lower_than_a_seek_burst_is_broadband():
    """The thunk has a resonance; that is what makes it read as one impact."""
    c = sound.click_samples(seed=1)
    at_ring = max(_goertzel(c, f, sound.SAMPLE_RATE) for f in range(900, 1400, 50))
    at_high = _goertzel(c, 8000.0, sound.SAMPLE_RATE)
    assert at_ring > 10 * at_high


def test_resolve_validates_the_idle_click_window():
    cfg = sound.resolve({}, {"click_min": 3.0, "click_max": 9.0})
    assert cfg["click_min"] == 3.0 and cfg["click_max"] == 9.0
    assert cfg["clicks"] is True
    with pytest.raises(ValueError, match="click_min"):
        sound.resolve({}, {"click_min": 9.0, "click_max": 3.0})
    with pytest.raises(ValueError, match="click_min"):
        sound.resolve({}, {"click_min": 0.0})


def test_idle_ticker_clicks_on_its_own_and_picks_among_variants(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False, seek=False, clicks=True,
                  click_min=0.02, click_max=0.05)
    eng.start()
    try:
        assert _wait(lambda: len(pl.names()) >= 4, timeout=3.0), pl.names()
        assert all(n.startswith("click") for n in pl.names()), pl.names()
        assert len(set(pl.names())) > 1, "three variants exist; use them"
    finally:
        eng.stop()


def test_ticker_stops_with_the_engine(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False, seek=False, clicks=True,
                  click_min=0.02, click_max=0.04)
    eng.start()
    assert _wait(lambda: len(pl.names()) >= 2, timeout=3.0)
    eng.stop()
    settled = len(pl.names())
    assert not _wait(lambda: len(pl.names()) > settled, timeout=0.4), "ticker leaked"
    assert not any(t.name == sound.TICK_THREAD_NAME and t.is_alive()
                   for t in threading.enumerate())


def test_clicks_false_means_no_ticker_at_all(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False, seek=False, clicks=False)
    eng.start()
    try:
        eng.click()
        assert not _wait(lambda: bool(pl.calls), timeout=0.3)
    finally:
        eng.stop()


def test_click_debounces_and_never_raises(tmp_path):
    pl = FakePlayer()
    eng = _engine(tmp_path, pl, whir=False, seek=False, clicks=True,
                  click_min=30.0, click_max=30.0)      # ticker will not fire in-test
    eng.start()
    try:
        for _ in range(8):
            eng.click()
        assert _wait(lambda: len(pl.names()) == 1), pl.names()
        assert len(pl.names()) == 1
    finally:
        eng.stop()
    boom = _engine(tmp_path, FakePlayer(explode=True), whir=False, seek=False, clicks=True,
                   click_min=30.0, click_max=30.0)
    boom.start()
    try:
        boom.click()          # must swallow OSError
    finally:
        boom.stop()


def test_module_click_is_safe_without_an_engine():
    sound.shutdown()
    sound.click()
    assert sound.engine() is None


# ------------------------------------------------------------- gapless tier ----

def test_a_loop_capable_player_needs_no_supervisor_thread(tmp_path):
    pl = FakeLoopPlayer()
    eng = _engine(tmp_path, pl)
    assert eng.gapless is True
    eng.start()
    try:
        assert pl.names() == ["whir.wav"]
        assert pl.loops() == [True], "must ask the player to loop itself"
        assert eng.running is True
        assert not any(t.name == sound.THREAD_NAME and t.is_alive()
                       for t in threading.enumerate()), "no relaunch thread on this tier"
    finally:
        eng.stop()
    assert pl.procs[0].killed
    assert eng.running is False


def test_the_afplay_tier_still_asks_for_no_loop_and_supervises(tmp_path):
    pl = FakePlayer()
    assert not hasattr(pl, "supports_loop"), \
        "a player that never declares the flag must be treated as non-looping"
    eng = _engine(tmp_path, pl)
    assert eng.gapless is False
    eng.start()
    try:
        assert _wait(lambda: pl.loops() == [False]), pl.loops()
    finally:
        eng.stop()


def test_loop_handle_is_dropped_if_stop_wins_the_race(tmp_path):
    pl = FakeLoopPlayer()
    eng = _engine(tmp_path, pl)
    eng.stop()              # pre-stopped
    eng.start()
    try:
        assert eng.running is True   # start() clears the flag, so this proceeds
    finally:
        eng.stop()
    assert eng.running is False


def test_mute_works_on_the_gapless_tier_too(tmp_path):
    pl = FakeLoopPlayer()
    eng = _engine(tmp_path, pl)
    eng.start()
    try:
        assert eng.toggle_mute() is True
        assert pl.procs[0].killed and eng.running is False
        assert eng.toggle_mute() is False
        assert eng.running is True
        assert len(pl.procs) == 2
    finally:
        eng.stop()


def test_best_player_prefers_the_gapless_tier_when_pyobjc_is_present():
    """macOS-gated dependency; on this machine it must resolve to AVPlayer."""
    av = sound.AVPlayer()
    if not av.available():
        pytest.skip("PyObjC/AVFoundation not installed")
    chosen = sound.best_player()
    assert isinstance(chosen, sound.AVPlayer)
    assert chosen.supports_loop is True
    assert sound.AfplayPlayer().supports_loop is False


def test_avplayer_really_loops_a_real_file_silently(tmp_path):
    """The whole point of the tier: numberOfLoops = -1, verified, at volume 0."""
    av = sound.AVPlayer()
    if not av.available():
        pytest.skip("PyObjC/AVFoundation not installed")
    path = sound.write_wav(tmp_path / "one-second.wav", sound.whir_samples(seconds=1.0))
    handle = av.play(path, volume=0.0, loop=True)
    try:
        assert handle.poll() is None
        prev, wraps = -1.0, 0
        for _ in range(26):
            time.sleep(0.1)
            now = handle._player.currentTime()
            if now < prev:
                wraps += 1
            prev = now
        assert wraps >= 1, "a 1s file over 2.6s must wrap"
        assert handle.poll() is None, "still playing — the loop did not end"
    finally:
        av.kill(handle)
    assert handle.poll() is not None


# -------------------------------------------------------------- mute state ----

def test_mute_is_a_flag_file_so_both_panes_agree(tmp_path):
    """tasks and status are separate processes; an in-memory bool would split."""
    flag = tmp_path / "muted"
    pl_a, pl_b = FakeLoopPlayer(), FakePlayer()
    cfg = sound.resolve({}, {"enabled": True, "whir": False, "seek": False,
                             "clicks": True, "click_min": 60.0, "click_max": 60.0})
    status = sound.SoundEngine(cfg, player=pl_a, assets=_assets(tmp_path), mute_flag=flag)
    tasks = sound.SoundEngine(cfg, player=pl_b, assets=_assets(tmp_path),
                              ticker=False, mute_flag=flag)
    try:
        assert status.muted is False and tasks.muted is False
        assert status.toggle_mute() is True          # 'm' pressed in the status pane
        assert flag.exists()
        assert tasks.muted is True, "the other process must see it"
        tasks.click()
        assert pl_b.calls == [], "a muted drive stays silent in both panes"
        assert status.toggle_mute() is False
        assert not flag.exists()
        tasks.click()
        assert _wait(lambda: pl_b.names() == ["click1.wav"] or pl_b.names() != [])
    finally:
        status.stop()
        tasks.stop()


def test_mute_survives_a_new_engine(tmp_path):
    """Persistence: mute before a restart means quiet after it."""
    flag = tmp_path / "muted"
    first = sound.SoundEngine(sound.resolve({}, {"enabled": True}), player=FakeLoopPlayer(),
                              assets=_assets(tmp_path), mute_flag=flag)
    first.set_muted(True)
    first.stop()
    pl = FakeLoopPlayer()
    restarted = sound.SoundEngine(sound.resolve({}, {"enabled": True}), player=pl,
                                  assets=_assets(tmp_path), mute_flag=flag)
    try:
        assert restarted.muted is True
        restarted.start()
        assert pl.calls == [], "started muted, so nothing plays"
        assert restarted.running is False
    finally:
        restarted.stop()


def test_ticker_can_be_disabled_for_the_second_pane(tmp_path):
    """Only one process should own the idle tick, or you get double clicking."""
    pl = FakePlayer()
    cfg = sound.resolve({}, {"enabled": True, "whir": False, "seek": False,
                             "clicks": True, "click_min": 0.02, "click_max": 0.03})
    eng = sound.SoundEngine(cfg, player=pl, assets=_assets(tmp_path), ticker=False,
                            mute_flag=tmp_path / "muted")
    eng.start()
    try:
        assert not _wait(lambda: bool(pl.calls), timeout=0.4), "ticker should be off"
        eng.click()      # explicit calls still work — that is the write path
        assert _wait(lambda: len(pl.names()) == 1)
    finally:
        eng.stop()


def test_module_muted_reads_the_flag_with_no_engine(tmp_path, monkeypatch):
    sound.shutdown()
    monkeypatch.setattr(sound, "MUTE_FLAG", tmp_path / "muted")
    assert sound.muted() is False
    (tmp_path / "muted").touch()
    assert sound.muted() is True
