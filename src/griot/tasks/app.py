"""griot-tasks: the left pane. Vault tasks as status-grouped two-line cards."""
import shlex
import subprocess
from datetime import date
from typing import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from griot import sound, theme
from griot.config import Config, load_config
from griot.tasks.heat import heat, heat_bar, is_do_or_die, mismatch
from griot.tasks.model import TaskNote
from griot.tasks.scanner import dir_signature, scan
from griot.tasks.writer import cycle_priority, touch

# Task-list filters: (label, predicate). "Open" is the default working set —
# everything except completed/cancelled work, so Done tasks don't bury the
# live list. Named "Open" (not "Active") to avoid colliding with the literal
# "Active" frontmatter status, which appears as its own group header.
# One 'f' press steps through to Done, then All.
_DONE_LIKE = {"Done", "Cancelled"}
FILTERS: list[tuple[str, Callable[["TaskNote"], bool]]] = [
    ("Open", lambda n: n.status not in _DONE_LIKE),
    ("In Progress", lambda n: n.status == "In Progress"),
    ("To Do", lambda n: n.status == "To Do"),
    ("Done", lambda n: n.status == "Done"),
    ("All", lambda n: True),
]

# Order status groups appear in the list; unknown statuses trail, alphabetical.
_STATUS_ORDER = ["In Progress", "To Do", "Active", "Backlog", "Paused",
                 "Done", "Cancelled"]

_HDR_PREFIX = "__hdr__:"


def _default_tmux_runner(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, capture_output=True)


def _default_opener(url: str) -> None:
    subprocess.run(["open", url], check=False, capture_output=True)


class TasksApp(App):
    CSS_PATH = theme.TCSS_PATH
    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("o", "open_note", "Open tab"),
        ("c", "claude_task", "Claude"),
        ("J", "open_jira", "Jira"),
        ("t", "touch", "Touch"),
        ("p", "priority", "Priority"),
        ("f", "filter", "Filter"),
        ("r", "rescan", "Rescan"),
    ]
    # Enter and mouse click are handled via OptionList.OptionSelected → detail.

    def __init__(
        self,
        config: Config | None = None,
        tmux_runner: Callable[[list[str]], None] | None = None,
        opener: Callable[[str], None] | None = None,
    ) -> None:
        # The palette must be live BEFORE App.__init__: that is where Textual
        # reads CSS_PATH and freezes $bg/$panel/$border through
        # get_css_variables(). Activating afterwards leaves every CSS-driven
        # surface painted in the default theme.
        cfg = config or load_config()
        theme.activate_from_config(cfg)
        super().__init__()
        self.config = cfg
        self.sound_cfg = sound.resolve(theme.default_sound(), self.config.sound)
        self.tmux = tmux_runner or _default_tmux_runner
        self.opener = opener or _default_opener
        self.notes: list[TaskNote] = []
        self.filter_idx = 0
        self._sig: tuple = ()

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **theme.css_variables()}

    def on_unmount(self) -> None:
        sound.shutdown()

    def compose(self) -> ComposeResult:
        yield Static(id="tasks-header", classes="panel-title")
        yield OptionList(id="task-list")
        yield Static(id="footer-hint")

    def on_mount(self) -> None:
        # This pane is a separate process from the status pane (bin/griot
        # send-keys into two tmux panes), so it needs its own engine or
        # sound.disk_write() on a vault write is a no-op. Ambient sound stays with
        # the status pane: no whir, no seek, and ticker=False so the idle tick
        # is not fired twice.
        sound.install({**self.sound_cfg, "whir": False, "seek": False}, ticker=False)
        # Hold direct references: query_one() resolves against the ACTIVE
        # screen, so timer-driven rescans would fail while the detail
        # overlay is pushed.
        self._list = self.query_one(OptionList)
        self._header = self.query_one("#tasks-header", Static)
        self._footer = self.query_one("#footer-hint", Static)
        self._list.focus()
        self._rescan(audible=True)   # startup reads every note
        self.set_interval(5.0, self._poll)

    # --- data ---

    def _poll(self) -> None:
        sig = dir_signature(self.config.tasks_path)
        if sig != self._sig:
            self._rescan()

    @staticmethod
    def _heat_style(h: float) -> str:
        """Bar brightness fades with the heat itself."""
        if h > 0.6:
            return theme.ACCENT_BRIGHT
        if h > 0.25:
            return theme.ACCENT
        if h > 0.05:
            return theme.MUTED
        return theme.BORDER

    @staticmethod
    def _priority_style(priority: int) -> str:
        if priority <= 2:
            return f"bold {theme.ACCENT_BRIGHT}"
        if priority == 3:
            return theme.TEXT
        return theme.MUTED

    def _card(self, n: TaskNote, today: date) -> Text:
        """Two-line card: title on top, dim metadata (P · heat · age) below."""
        if n.parse_error:
            t = Text()
            t.append("✗ ", style=theme.ERR)
            t.append(f"{n.title}\n", style=theme.MUTED)
            t.append("   parse error", style=theme.ERR)
            return t
        h = heat(n.progress_date, today)
        mark = mismatch(n.priority, h)
        glyph, gstyle = {
            "neglected": ("⚠ ", f"bold {theme.ACCENT_BRIGHT}"),
            "distraction": ("≈ ", theme.MUTED),
        }.get(mark, ("  ", theme.TEXT))
        days = (today - n.progress_date).days if n.progress_date else None
        t = Text()
        t.append(glyph, style=gstyle)
        t.append(f"{n.title}\n", style=theme.TEXT)
        t.append("   ")
        t.append(f"P{n.priority}", style=self._priority_style(n.priority))
        t.append(" · ", style=theme.MUTED)
        t.append(heat_bar(h), style=self._heat_style(h))
        t.append(" · ", style=theme.MUTED)
        t.append(f"{days}d" if days is not None else "—", style=theme.MUTED)
        if is_do_or_die(n, today):
            t.append("  ☠ DoD", style=f"bold {theme.ERR}")
        return t

    @staticmethod
    def _header_line(status: str) -> Text:
        rule = "─" * max(0, 20 - len(status))
        return Text(f"── {status} {rule}", style=f"bold {theme.ACCENT}")

    def _rescan(self, audible: bool = False) -> None:
        if audible:
            sound.disk_read()
        today = date.today()
        current = self._current()
        selected_path = str(current.path) if current else None
        self._sig = dir_signature(self.config.tasks_path)
        all_notes = scan(self.config.tasks_path, today)
        filter_label, predicate = FILTERS[self.filter_idx]
        self.notes = [n for n in all_notes if predicate(n)]

        groups: dict[str, list[TaskNote]] = {}
        for n in self.notes:
            groups.setdefault(n.status, []).append(n)
        ordered = ([s for s in _STATUS_ORDER if s in groups]
                   + sorted(s for s in groups if s not in _STATUS_ORDER))
        show_headers = len(groups) > 1

        lst = self._list
        lst.clear_options()
        for status in ordered:
            if show_headers:
                lst.add_option(Option(self._header_line(status),
                                      id=f"{_HDR_PREFIX}{status}", disabled=True))
            for n in groups[status]:
                lst.add_option(Option(self._card(n, today), id=str(n.path)))

        dod = sum(1 for n in self.notes if is_do_or_die(n, today))
        header = Text.assemble(
            (" ◆ TASKS ", f"bold {theme.ACCENT}"),
            (f"{filter_label} ", theme.ACCENT_BRIGHT),
            (f"{len(self.notes)}", theme.MUTED),
        )
        if dod:
            header.append(f"  ☠ DoD {dod}", style=f"bold {theme.ERR}")
        self._header.update(header)
        vault_ok = self.config.tasks_path.is_dir()
        hint = "" if vault_ok else "vault not found — check iCloud sync"
        self._footer.update(
            Text(hint or " ⏎ view · o tab · c claude · J jira · t touch · p pri · f filter",
                 style=theme.MUTED)
        )

        self._restore_highlight(selected_path)

    def _restore_highlight(self, path: str | None) -> None:
        lst = self._list
        if path is not None:
            for i in range(lst.option_count):
                if lst.get_option_at_index(i).id == path:
                    lst.highlighted = i
                    return
        # default: first selectable (non-header) option
        for i in range(lst.option_count):
            oid = lst.get_option_at_index(i).id
            if oid and not oid.startswith(_HDR_PREFIX):
                lst.highlighted = i
                return

    def _note_for_id(self, oid: str | None) -> TaskNote | None:
        if not oid or oid.startswith(_HDR_PREFIX):
            return None
        return next((n for n in self.notes if str(n.path) == oid), None)

    def _current(self) -> TaskNote | None:
        lst = getattr(self, "_list", None)
        if lst is None or lst.highlighted is None:
            return None
        try:
            oid = lst.get_option_at_index(lst.highlighted).id
        except Exception:
            return None
        return self._note_for_id(oid)

    # --- navigation ---

    def action_cursor_down(self) -> None:
        self._list.action_cursor_down()

    def action_cursor_up(self) -> None:
        self._list.action_cursor_up()

    # Enter or mouse click on a task → detail overlay.
    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        note = self._note_for_id(event.option.id)
        if note and not note.parse_error:
            from griot.tasks.detail import TaskDetailScreen

            sound.disk_read()   # detail.note_body() read_text()s the note
            self.push_screen(TaskDetailScreen(note))

    # --- note operations (shared by list actions and the detail overlay) ---

    def open_note_tab(self, note: TaskNote) -> None:
        self.tmux([
            "tmux", "-L", "griot", "new-window", "-t", "griot-center",
            "-n", note.title[:18],
            f"griot-view {shlex.quote(str(note.path))}",
        ])

    def open_note_in_claude(self, note: TaskNote) -> None:
        """New center tab: a Claude Code session primed to work on this task,
        with both the vault (task context) and the repos dir (code edits)
        granted via --add-dir. The prompt comes first so the variadic
        --add-dir at the end can't swallow it."""
        prompt = (
            f"Read the task note at {note.path} and help me work on it. "
            "Start by summarizing the task and proposing a plan."
        )
        claude_cmd = (
            f"claude {shlex.quote(prompt)}"
            f" --add-dir {shlex.quote(str(self.config.vault_path))}"
            f" --add-dir {shlex.quote(str(self.config.repos_dir))}"
        )
        self.tmux([
            "tmux", "-L", "griot", "new-window", "-t", "griot-center",
            "-c", str(self.config.claude_default_dir),
            "-n", note.title[:18],
            claude_cmd,
        ])

    def touch_note(self, note: TaskNote) -> None:
        if not note.parse_error:
            touch(note.path, date.today())
            sound.disk_write()   # the drive works when the disk is actually written
            self._rescan()

    def cycle_note_priority(self, note: TaskNote) -> None:
        if not note.parse_error:
            cycle_priority(note.path, note.priority)
            sound.disk_write()
            self._rescan()

    def open_jira(self, note: TaskNote) -> None:
        from griot.tasks.model import jira_urls

        for url in jira_urls(note.jira, self.config.jira_base_url):
            self.opener(url)

    # --- actions ---

    def action_open_note(self) -> None:
        note = self._current()
        if note:
            self.open_note_tab(note)

    def action_claude_task(self) -> None:
        note = self._current()
        if note and not note.parse_error:
            self.open_note_in_claude(note)

    def action_open_jira(self) -> None:
        note = self._current()
        if note:
            self.open_jira(note)

    def action_touch(self) -> None:
        note = self._current()
        if note:
            self.touch_note(note)

    def action_priority(self) -> None:
        note = self._current()
        if note:
            self.cycle_note_priority(note)

    def action_filter(self) -> None:
        self.filter_idx = (self.filter_idx + 1) % len(FILTERS)
        self._rescan()

    def action_rescan(self) -> None:
        self._rescan(audible=True)


def main() -> None:
    TasksApp().run()


if __name__ == "__main__":
    main()
