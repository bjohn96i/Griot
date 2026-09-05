"""Task detail overlay: full note view rendered inside the left pane."""
from datetime import date
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Markdown, Static

from griot import theme
from griot.tasks.heat import heat, heat_bar
from griot.tasks.model import TaskNote, parse_task, split_frontmatter


def note_body(path: Path) -> str:
    """The note's markdown body — everything after the frontmatter block."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return "*could not read note*"
    if split_frontmatter(text) is None:
        return text
    lines = text.splitlines(keepends=True)
    close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return "".join(lines[close + 1:])


class TaskDetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "close", "Back"),
        ("q", "close", "Back"),
        ("o", "open_center", "Open tab"),
        ("c", "open_claude", "Claude"),
        ("J", "open_jira", "Jira"),
        ("t", "touch", "Touch"),
        ("p", "priority", "Priority"),
    ]

    def __init__(self, note: TaskNote) -> None:
        super().__init__()
        self.note = note

    def compose(self) -> ComposeResult:
        yield Static(id="detail-title", classes="detail-title")
        yield Static(id="detail-chips", classes="detail-chips")
        with VerticalScroll(id="detail-scroll"):
            yield Markdown(note_body(self.note.path), id="detail-body")
        yield Static(
            Text(" esc back · o open tab · c claude · t touch · p priority",
                 style=theme.MUTED),
            classes="detail-footer",
        )

    def on_mount(self) -> None:
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        n = parse_task(self.note.path)
        self.note = n
        self.query_one("#detail-title", Static).update(
            Text(f" {n.title}", style=f"bold {theme.GOLD}")
        )
        h = heat(n.progress_date, date.today())
        pri_style = f"bold {theme.GOLD_BRIGHT}" if n.priority <= 2 else theme.MUTED
        chips = Text(" ")
        chips.append(f" {n.status} ", style=f"{theme.BG} on {theme.GOLD}")
        chips.append("  ")
        chips.append(f"P{n.priority}", style=pri_style)
        chips.append("  ")
        chips.append(heat_bar(h), style=theme.GOLD)
        chips.append("  ")
        chips.append(
            n.progress_date.isoformat() if n.progress_date else "no progress date",
            style=theme.MUTED,
        )
        self.query_one("#detail-chips", Static).update(chips)

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_center(self) -> None:
        self.app.open_note_tab(self.note)

    def action_open_claude(self) -> None:
        self.app.open_note_in_claude(self.note)

    def action_open_jira(self) -> None:
        self.app.open_jira(self.note)

    def action_touch(self) -> None:
        self.app.touch_note(self.note)
        self._refresh_meta()

    def action_priority(self) -> None:
        self.app.cycle_note_priority(self.note)
        self._refresh_meta()
