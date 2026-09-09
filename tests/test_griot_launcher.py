"""bin/griot — the pidfile teardown in the `restart` branch.

Runs under `set -euo pipefail`, so any command in that branch that can exit
non-zero (like `kill` against a dead pid) must be defused with `|| true` or
the script dies before `rm -f "$BRAIN_PID_FILE"` — bricking every later
`griot restart`. This does not invoke bin/griot itself: that script drives
the live tmux session and socket by name, which must not be touched here.
Instead it extracts the shipped pidfile-kill line by regex and exercises it
in isolation under the same shell options.
"""
import re
import subprocess

from griot import theme

GRIOT = theme.REPO_ROOT / "bin" / "griot"


def _pidfile_kill_line() -> str:
    text = GRIOT.read_text()
    m = re.search(r'^\s*\[ -f "\$BRAIN_PID_FILE" \].*$', text, re.MULTILINE)
    assert m, "could not find the pidfile-kill line in bin/griot"
    return m.group(0).strip()


def _dead_pid() -> int:
    """A pid guaranteed to be gone: a real process, already reaped."""
    proc = subprocess.Popen(["sleep", "0"])
    proc.wait()
    return proc.pid


def test_a_stale_pidfile_does_not_brick_restart_under_errexit(tmp_path):
    line = _pidfile_kill_line()
    pidfile = tmp_path / "pid"
    pidfile.write_text(str(_dead_pid()))
    script = (
        'set -euo pipefail\n'
        f'BRAIN_PID_FILE="{pidfile}"\n'
        f'{line}\n'
        'echo REACHED\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stderr={proc.stderr!r} stdout={proc.stdout!r}"
    assert "REACHED" in proc.stdout, \
        "the script must survive a dead pid and still reach the rebuild"
