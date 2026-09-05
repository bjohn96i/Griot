# Griot

A three-pane tmux workstation over an Obsidian vault. The left pane tracks vault tasks
with a heat/priority tracker, the center pane hosts tabbed Claude Code sessions (and
rendered vault notes), and the right pane is a live status stack with a signature
kimoyo-bead animation.

> **Adopting this?** The center and right panes are self-contained, but **the left
> pane is coupled to a specific vault layout and frontmatter schema** (it reads *and
> writes* your task notes). Before running it against your own vault, read
> **[Requirements](#requirements)** and **[Vault conventions](#vault-conventions-the-left-panes-contract)** —
> they define exactly what the left pane needs to function.

```
┌──────────┬────────────────────────────────────┬─────────┐
│  TASKS   │   [claude:1][claude:2][note]       │  GRIOT  │
│  (20%)   │                                    │  (16%)  │
│ griot-   │    nested tmux "griot-center"      │  beads  │
│ tasks    │    each window = one tab           │  clock  │
│ (Textual)│    running claude or a             │ weather │
│          │    rendered markdown note          │calendar │
│          │                                    │ battery │
│          │                                    │ network │
│          │                                    │  usage  │
└──────────┴────────────────────────────────────┴─────────┘
```

The right pane's lower half is three sections (scrollable):
- **⚡ BATTERY** — charge %, AC/battery/charging, drain rate, and ETA to 10%.
- **⧉ NETWORK** — primary IP, Wi-Fi + VPN status, your listening ports with the
  owning process (e.g. `:8080 docker`), and any SSH tunnels open (`tun :36379`).
  Fires a macOS notification when the VPN or the Redis tunnel drops, or a
  calendar meeting is under 5 minutes away.
- **Σ CLAUDE (mo)** — month-to-date token *volume* broken out (total, in/out, cache
  read/write). Not billed dollars: the local Claude Code logs record token counts, not
  cost, and `ccusage`'s dollar figure is list-price × tokens (wildly higher than a
  subscription's actual spend), so this widget reports volume instead.

The theme is "Vibranium Night": a true-black background (so the panes blend into your
terminal and Claude Code) with dark-navy panels and vibranium-gold accents. Pane widths
are configurable under `[layout]` in the config (defaults 20 / 64 / 16).

## Requirements

**Platform: macOS only.** The right pane reads system state through macOS-specific
tools (`pmset`, `scutil`, `ipconfig`, `route`/`ifconfig`, `lsof`, `osascript`, `open`,
`icalBuddy`) and the tab keys rely on the terminal's Option-as-Meta setting. Running on
Linux would require rewriting the right-pane data sources in
`src/griot/status/sources.py`.

**Command-line tools** (all but the last group are required):

| Tool | Used for | Install |
|---|---|---|
| `tmux` ≥ 3.2 | the whole workstation; `display-popup` for ⌥x/⌥c | `brew install tmux` |
| `uv` | runs the Python (3.13) apps | [astral.sh/uv](https://docs.astral.sh/uv/) |
| `claude` | the center pane's Claude Code sessions | [claude.com/claude-code](https://claude.com/claude-code) |
| `glow` | renders vault notes in a center tab | `brew install glow` |
| `fzf` | the ⌥x command palette | `brew install fzf` |
| `icalBuddy` | calendar widget (optional — widget stays empty without it) | `brew install ical-buddy` |
| Node / `npx` | the Claude usage widget (`ccusage`) | comes with Node |

**Network:** the weather widget calls Open-Meteo; the usage widget downloads `ccusage`
via `npx` on first run. Both degrade to `?` offline.

**A vault** — an Obsidian vault (or any folder of markdown notes) that follows the
[Vault conventions](#vault-conventions-the-left-panes-contract) below.

## Vault conventions (the left pane's contract)

This is the part that's coupled to a specific setup. The left pane **scans, renders,
and writes** task notes, so your vault must match these conventions (or you point the
config/code at your own).

**Folder layout.** The left pane reads `*.md` files **directly inside**
`<vault_path>/<tasks_dir>` — the scan is **not recursive**, so anything in a subfolder
is ignored. That's deliberate: a subfolder (e.g. `Failed Tasks/`) is an archive the
pane won't show. Set both paths in the config:

```toml
vault_path = "~/Documents/ObsidianVault"
tasks_dir  = "Notes/Tasks"   # scanned non-recursively for *.md
```

**One task = one markdown note** with YAML frontmatter. The **card title is the
filename** (without `.md`). These frontmatter fields drive the pane:

| Field | Read/Write | Type | Default if missing | Drives |
|---|---|---|---|---|
| `Status` | read | string | `?` | grouping headers, the `f` view filter, Do-or-Die |
| `Priority` | read **+ write** (`p`) | integer 1–5 | `3` | sort order, `⚠`/`≈` mismatch markers |
| `Last Progress` | read **+ write** (`t`) | date `YYYY-MM-DD` | falls back to `creation date` | heat decay, age (`Nd`), Do-or-Die |
| `creation date` | read | date `YYYY-MM-DD` | — | fallback when `Last Progress` is absent |
| `Jira` | read | URL, ticket IDs, or `n/a` | — | the `J` open-in-browser key |

The app **writes** `Priority` and `Last Progress` back into frontmatter when you press
`p` or `t` (atomically, preserving every other byte of the note), so the vault must be
writable and those two fields are effectively app-managed.

**Special `Status` values.** Any string is allowed, but a few are treated specially:

- `Done` and `Cancelled` are hidden from the default **Open** view and are never flagged
  Do-or-Die.
- Group headers are ordered **In Progress → To Do → Active → Backlog → Paused → Done →
  Cancelled**; any other status you use sorts alphabetically after those.

**A canonical task note** (`Notes/Tasks/Continue the API cache test suite.md`):

```markdown
---
Status: In Progress
Priority: 1
Last Progress: 2026-09-05
creation date: 2026-09-01
Jira: https://your-org.atlassian.net/browse/PROJ-4914
---

# Continue the API cache test suite

Free-form body — rendered with `glow` when you press `o`, and read by Claude
when you press `c`.
```

**Adapting it to your own vault.** Point `tasks_dir` at your folder and match the
frontmatter above and you're done. If your notes use *different field names*, the names
(`Status`, `Priority`, `Last Progress`, `creation date`, `Jira`) are currently hardcoded
in `src/griot/tasks/model.py` — change them there. Heat half-life (4 days),
priority range (1–5), the Do-or-Die threshold (30 days), and the mismatch thresholds
live in `src/griot/tasks/heat.py`.

## Install

Install the [tools](#requirements) first, then:

```bash
brew install tmux glow fzf ical-buddy      # icalBuddy optional (calendar)
uv sync                                     # from the repo root
ln -s "$PWD/bin/griot" /usr/local/bin/griot # or add bin/ to PATH (sudo may be needed)
mkdir -p ~/.config/griot
cp config.example.toml ~/.config/griot/config.toml
```

Then edit `~/.config/griot/config.toml`. At minimum, for the left pane to find
your notes, set:

```toml
vault_path = "~/path/to/your/vault"
tasks_dir  = "relative/path/to/tasks"   # scanned non-recursively for *.md
```

and set `[weather] latitude`/`longitude` for the weather widget. Everything else has a
sane default; see the example file for `claude_default_dir`, `repos_dir`,
`startup_prompt`, `jira_base_url`, `[layout]` widths, and `[commands]` palette presets.

## Terminal setup (Option-as-Meta)

The center pane's tab keys (`⌥t`, `⌥w`, `⌥1`–`⌥9`) rely on the terminal sending Option as
a Meta/Esc+ prefix. Without this, ⌥ key combos do nothing:

- **Terminal.app:** Settings → Profiles → Keyboard → check "Use Option as Meta key".
- **iTerm2:** Preferences → Profiles → Keys → General → set "Left Option key" to `Esc+`.

## Running it

```bash
griot
```

First run builds the three-pane session; running it again re-attaches to the existing
one. Detach with `ctrl-b d` — the session keeps running, and `griot` picks it back up
whenever you come back.

The first center tab is named **griot** and opens a Claude Code session that runs
`startup_prompt` on launch (default `/griot:brief`, so Griot briefs the current state
as soon as you start). Set `startup_prompt = ""` in the config to disable it.

After updating the code, config, or theme, run `griot restart` — a plain `griot`
re-attaches to the already-running session, which still shows the old build.

## Features

**Workstation / launcher**
- `griot` builds a three-pane tmux session (tasks · Claude tabs · status), or re-attaches if it's already running; `griot restart` tears down and rebuilds after code/config changes.
- Detach/reattach survives closing the terminal (`ctrl-b d` to detach).
- Pane widths configurable (`[layout]`), and reliably applied at the real terminal size on every attach.
- "Vibranium Night" theme (true-black background) shared across the Textual apps, the tmux tab bar, and the glow note renderer.

**Left pane — tasks**
- Task notes scanned from `tasks_dir` (non-recursive), shown as **two-line cards grouped under status headers**: full title + `priority · heat bar · age`.
- **Heat tracker** — recency decay from `Last Progress` (4-day half-life); the bar brightness fades as a task goes cold.
- **Priority/heat mismatch markers** — `⚠` neglected (high priority gone cold), `≈` distraction (low priority but hot).
- **Do-or-Die** — `☠` badge + header count for open tasks with no progress >30 days.
- **View filter** (`f`) — Open / In Progress / To Do / Done / All.
- **In-pane detail overlay** (Enter/click) — rendered markdown body + status chips, scrollable.
- **Writes back to the vault** — touch (`t` → `Last Progress`) and cycle priority (`p`), atomic and byte-preserving; selection survives the re-sort.
- **Open a task elsewhere** — `o` renders it in a center tab, `c` loads it into a Claude session, `J` opens its Jira.
- Auto-refreshes every 5s when task files change; explicit "vault not found" state if the vault is missing.

**Center pane — Claude & notes**
- Tabbed nested-tmux sessions; the first tab (`griot`) runs `startup_prompt` (default `/griot:brief`) on open.
- `⌥t` new Claude tab · `⌥w` close · `⌥1`–`⌥9` jump · mouse-click a tab to switch.
- `c`-loaded task sessions get the vault **and** `repos_dir` via `--add-dir`, so Claude can read the note and edit code.
- Notes render with `glow` in the Vibranium style (`q` closes the pager tab).

**Right pane — live status** (each widget refreshes independently and degrades to `?`/`◌` on failure)
- **Kimoyo beads** animation — pulses faster on any state change or an imminent meeting.
- **Clock**, **weather** (Open-Meteo), **calendar** (next events via `icalBuddy`).
- **Battery** — %, AC/battery/charging, drain rate, ETA to 10%.
- **Network** — primary IP, Wi-Fi + VPN, listening ports with owning process, open SSH tunnels.
- **Claude usage** — month-to-date token volume broken out (total, in/out, cache).
- **macOS notifications** when the VPN or Redis tunnel drops, or a meeting is <5 min away.

**Global**
- **Command palette** (`⌥x`) — fzf popup of `[commands]` presets + free-form; runs the choice in a center tab.
- **Quick-capture** (`⌥c`) — type a line; Griot files it into the vault via `/griot:capture`.

## Keys

Every shortcut in one place. `⌥` = Option (needs [Option-as-Meta](#terminal-setup-option-as-meta)).

**Left pane (tasks):**

Tasks are shown as two-line cards grouped under status headers (In Progress, To
Do, …). Each card is the full title plus a dim line of `priority · heat bar ·
days since progress`; `⚠` marks a neglected task (high priority gone cold) and
`≈` a distraction (low priority but hot). A red **☠ DoD** badge (and a header
count) flags "Do-or-Die" tasks — open with no progress for over a month — per
the standing rule to force progress or kill them.

| Key | Action |
|---|---|
| `Enter` / click a task | open its full view in the pane (rendered markdown + status chips) |
| `j` / `k` | move selection (group headers are skipped) |
| `o` | open the task's note in a new center tab (rendered) |
| `c` | load the task into a new Claude Code session — reads the note from the vault and can edit code under `repos_dir` (`--add-dir`) |
| `J` | open the task's Jira in the browser — handles a full URL, bare ticket IDs (`PROJ-4927, PROJ-4937`, built onto `jira_base_url`), or `n/a` (no-op) |
| `t` | touch — set `Last Progress` to today |
| `p` | cycle priority |
| `f` | cycle view (Open / In Progress / To Do / Done / All) — "Open" = everything except Done/Cancelled |
| `r` | force rescan |

**Inside the task detail view:** `esc`/`q` back to the list · `o` open as center tab ·
`c` load into a Claude session · `J` open Jira · `t` touch · `p` cycle priority.

**Global (any pane):**

| Key | Action |
|---|---|
| `⌥x` | command palette — fuzzy-pick a `[commands]` preset or type any command; it runs in a new center tab (e.g. `restore tunnel` → `your-tunnel-cmd --up`) |
| `⌥c` | quick-capture — type a line; Griot files it into the vault via `/griot:capture` in a center tab |

**Center pane (tabs):**

| Key | Action |
|---|---|
| `⌥t` | new Claude tab |
| `⌥w` | close current tab (with confirm) |
| `⌥1`–`⌥9` | jump to tab N |
| mouse click | switch to a tab (click its name in the tab bar) |
| `q` | close a note (`o`) tab — quits the glow pager |

**Detach the whole workstation:** `ctrl-b d` (tmux prefix); `griot` re-attaches.

## Calendar

The calendar widget shells out to `icalBuddy`, which reads from macOS Calendar. For
events to show up, enable your Google account under System Settings → Internet Accounts
with Calendars turned on. The first time `icalBuddy` runs, macOS will prompt for Calendar
access — grant it or the widget stays empty.

## Heat model

Each task's heat decays from its `Last Progress` date with a 4-day half-life, so recently
worked tasks glow and stale ones go cold. Two markers flag a priority/heat mismatch:
`⚠` (gold) means high priority but cold — neglected; `≈` (dim) means low priority but
hot — a distraction pulling time from what matters.
