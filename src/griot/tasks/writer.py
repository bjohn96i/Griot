"""Atomic, byte-preserving frontmatter edits. The one module that writes to the vault."""
import os
import stat
import tempfile
from datetime import date
from pathlib import Path

from griot.tasks.model import split_frontmatter


def set_field(path: Path, field: str, value: str) -> None:
    # Read with newline="" to preserve CRLF
    with open(path, newline="") as f:
        text = f.read()
    split = split_frontmatter(text)
    if split is None:
        raise ValueError(f"{path} has no frontmatter")
    lines = text.splitlines(keepends=True)
    close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    prefix = f"{field}:"
    for i in range(1, close):
        if lines[i].split("#", 1)[0].strip().startswith(prefix) or lines[i].startswith(prefix):
            # Preserve the original line terminator (\r\n, \n, or none)
            if lines[i].endswith("\r\n"):
                terminator = "\r\n"
            elif lines[i].endswith("\n"):
                terminator = "\n"
            else:
                terminator = ""
            lines[i] = f"{field}: {value}{terminator}"
            break
    else:
        lines.insert(close, f"{field}: {value}\n")
    _atomic_write(path, "".join(lines))


def touch(path: Path, today: date) -> None:
    set_field(path, "Last Progress", today.isoformat())


def cycle_priority(path: Path, current: int) -> int:
    new = (current % 5) + 1
    set_field(path, "Priority", str(new))
    return new


def _atomic_write(path: Path, content: str) -> None:
    # Get original file mode
    original_mode = stat.S_IMODE(os.stat(path).st_mode)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".griot-")
    try:
        # Use newline="" to preserve CRLF
        with os.fdopen(fd, "w", newline="") as f:
            f.write(content)
        # Copy original file mode to temp file
        os.chmod(tmp, original_mode)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
