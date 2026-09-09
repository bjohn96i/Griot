"""bin/griot-disk — the Claude Code PostToolUse hook.

griot's own panes only see their own reads and writes; when Claude edits the
vault with bash, the tasks pane never learns about it, and a read leaves no
trace to detect afterwards. This script is what closes that gap, so its
classification and its gating are worth pinning down.

Every case runs with GRIOT_DISK_DRYRUN=1 — nothing is ever played.
"""
import json
import subprocess

import pytest

from griot import sound, theme

HOOK = theme.REPO_ROOT / "bin" / "griot-disk"


@pytest.fixture
def cache(tmp_path):
    """An XDG_CACHE_HOME with a params file the hook will accept."""
    d = tmp_path / "griot" / "sound"
    d.mkdir(parents=True)
    (d / "params").write_text("enabled=1\nclicks=1\nvolume=0.150\n"
                              "one_shot_volume=0.270\nversion=v2\n")
    return tmp_path, d


def run(cache, kind, payload=None):
    root, _ = cache
    proc = subprocess.run(
        [str(HOOK), kind],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True,
        env={"HOME": str(root), "PATH": "/usr/bin:/bin",
             "XDG_CACHE_HOME": str(root), "GRIOT_DISK_DRYRUN": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_the_hook_is_executable():
    assert HOOK.exists(), HOOK
    assert HOOK.stat().st_mode & 0o111, "must be chmod +x for a hook to run it"


def test_explicit_kinds_pick_their_own_family(cache):
    assert run(cache, "read").split()[0] == "read"
    assert run(cache, "write").split()[0] == "write"


def test_it_resolves_a_versioned_asset_from_the_params_file(cache):
    kind, asset = run(cache, "write").split()
    assert kind == "write"
    assert asset.endswith("-v2.wav"), asset
    assert "/griot/sound/write" in asset


READS = [
    "cat notes.md",
    "sed -n '1,20p' file.md",
    "grep -rn foo src/",
    "ls -la",
    "head -5 x.md",
    "git status",
    "git log --oneline",
    "git diff",
    # the tricky one: 2>&1 is not a file write
    "pytest -q 2>&1 | tail -3",
    "uv run pytest tests/ -q",
]

WRITES = [
    "echo hi > out.txt",
    "cat >> log.md",
    "sed -i '' s/a/b/ f.md",
    "mv a.md b.md",
    "cp a.md b.md",
    "rm stale.md",
    "mkdir -p x/y",
    "touch new.md",
    "tee out.txt",
    "git commit -m x",
    "git add -A",
]


@pytest.mark.parametrize("cmd", READS)
def test_auto_classifies_reads(cache, cmd):
    out = run(cache, "auto", {"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert out.split()[0] == "read", f"{cmd!r} -> {out}"


@pytest.mark.parametrize("cmd", WRITES)
def test_auto_classifies_writes(cache, cmd):
    out = run(cache, "auto", {"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert out.split()[0] == "write", f"{cmd!r} -> {out}"


def test_a_heredoc_is_a_write(cache):
    out = run(cache, "auto", {"tool_name": "Bash",
                              "tool_input": {"command": "cat <<'EOF' > f.md\nx\nEOF"}})
    assert out.split()[0] == "write"


# ------------------------------------------------------------------ gating ----

def silent(root, kind="read", payload=None):
    proc = subprocess.run(
        [str(HOOK), kind],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True,
        env={"HOME": str(root), "PATH": "/usr/bin:/bin",
             "XDG_CACHE_HOME": str(root), "GRIOT_DISK_DRYRUN": "1"},
    )
    return proc.returncode, proc.stdout.strip()


def test_no_params_means_no_drive(tmp_path):
    """griot has never installed an engine, so there is nothing to hear."""
    assert silent(tmp_path) == (0, "")


def test_the_mute_flag_silences_the_hook_too(cache):
    root, d = cache
    (d / "muted").touch()
    assert silent(root) == (0, ""), "m in the status pane must reach this process"
    (d / "muted").unlink()
    assert silent(root)[1] != ""


def test_enabled_false_silences_the_hook(cache):
    root, d = cache
    (d / "params").write_text("enabled=0\nclicks=1\nvolume=0.1\n"
                              "one_shot_volume=0.2\nversion=v2\n")
    assert silent(root) == (0, "")


def test_clicks_false_silences_the_hook(cache):
    root, d = cache
    (d / "params").write_text("enabled=1\nclicks=0\nvolume=0.1\n"
                              "one_shot_volume=0.2\nversion=v2\n")
    assert silent(root) == (0, "")


def test_an_unknown_kind_is_a_no_op(cache):
    root, _ = cache
    assert silent(root, kind="sideways") == (0, "")


# ------------------------------------------------------------------ params ----

def test_write_params_renders_what_the_hook_sources(tmp_path):
    cfg = sound.resolve({}, {"enabled": True, "volume": 0.15, "clicks": True})
    p = sound.write_params(cfg, tmp_path / "params")
    lines = dict(line.split("=", 1) for line in p.read_text().splitlines())
    assert lines == {"enabled": "1", "clicks": "1", "volume": "0.150",
                     "one_shot_volume": "0.270", "version": sound.SYNTH_VERSION}


def test_write_params_carries_the_gain_and_the_clamp(tmp_path):
    cfg = sound.resolve({}, {"volume": 0.8, "one_shot_gain": 4.0})
    p = sound.write_params(cfg, tmp_path / "params")
    assert "one_shot_volume=1.000" in p.read_text(), "must clamp like the engine does"


def test_write_params_reflects_a_disabled_config(tmp_path):
    cfg = sound.resolve({}, {"enabled": False, "clicks": False})
    body = sound.write_params(cfg, tmp_path / "params").read_text()
    assert "enabled=0" in body and "clicks=0" in body


def test_install_renders_the_params_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "PARAMS_FILE", tmp_path / "params")
    monkeypatch.setattr(sound, "MUTE_FLAG", tmp_path / "muted")

    class Dead:
        def available(self):
            return False

    cfg = sound.resolve({}, {"enabled": True})
    try:
        sound.install(cfg, player=Dead(), assets={"whir": tmp_path / "w.wav",
                                                  "seek": tmp_path / "s.wav",
                                                  "clicks": [], "writes": [], "reads": []})
        assert (tmp_path / "params").exists(), "the hook needs this to make any sound"
    finally:
        sound.shutdown()
