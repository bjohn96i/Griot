# Griot — Design Spec

**Date:** 2026-09-05
**Status:** Approved by Johnathan (2026-09-05)
**Project:** `~/Documents/Personal/Griot`

## Purpose

Give Griot (the assistant layer over an Obsidian vault) a face: a three-pane
terminal workstation. Left pane shows vault tasks with a heat tracker; center pane hosts
tabbed Claude Code sessions and rendered vault notes; right pane is a live status stack
with a signature animation.

## Architecture (Approach A — tmux composition)

A `griot` launcher command builds (or re-attaches to) an outer tmux session with three
panes. The side panes run two small custom Textual (Python) apps. The center pane runs a
**nested tmux session** whose windows are the tabs. Claude Code runs as a native process
in real ptys — no terminal emulation anywhere in the design.

```
┌────────────┬──────────────────────────────┬────────────┐
│  TASKS     │  [claude:1][claude:2][note]  │   GRIOT    │
│  (22%)     │                              │   (22%)    │
│ griot-     │   nested tmux "griot-center" │  beads     │
│ tasks      │   each window = one tab      │  clock     │
│ (Textual)  │   running claude or a        │  weather   │
│            │   rendered markdown note     │  calendar  │
│            │                              │  statuses  │
│            │                              │  spend     │
└────────────┴──────────────────────────────┴────────────┘
```

- Outer session name: `griot`. Inner session name: `griot-center`.
- `griot` re-attaches if the session already exists; detach survives closing the
  terminal window.
- Runtime: Python 3.14, project managed with `uv`. tmux ≥ 3.4 (installed: 3.4).
- Components communicate only through tmux commands and the filesystem — no shared
  in-process state.

## Components

### Launcher (`griot`)

Shell entry point installed on PATH. Responsibilities:

1. Dependency check (tmux, uv env, glow, claude) with clear install hints on failure.
2. If session `griot` exists → attach. Otherwise create the outer session, split into
   22% / 56% / 22% panes, launch `griot-tasks` (left), the nested `griot-center`
   session (center, first window running `claude` in the configured default dir), and
   `griot-status` (right).
3. Apply tmux theme options (border colors, inner status-bar-as-tab-bar styling).

### Theme — "Vibranium"

Single palette source consumed by everything: `src/griot/theme.py` plus
`griot.tcss` for the Textual apps, the same hexes injected into tmux options and the
glow/rich markdown style.

| Token | Hex | Use |
|---|---|---|
| bg | `#0A1428` | app background |
| panel | `#0F1B33` | widget/panel background |
| border | `#1E3A5F` | pane and widget borders |
| gold | `#E3B341` | accents, selection, active tab, beads |
| gold-bright | `#F0C75E` | highlights, alerts |
| text | `#C7D3E8` | primary text |
| muted | `#8FA3C7` | secondary text |
| ok | `#4EC97B` | healthy status |
| err | `#E05561` | failed status |

### Left pane — `griot-tasks` (Textual app)

- **Source:** `<vault>/Notes/Tasks/*.md`, excluding `Failed Tasks/`.
  Frontmatter parsed with PyYAML.
- **Heat** = recency decay from the `Last Progress` frontmatter date:
  `heat = 0.5 ** (days_since / 4)` (half-life 4 days). Full flame ≤ 1 day, ember by
  ~2 weeks, cold past a month. Missing `Last Progress` → falls back to
  `creation date`; missing both → cold. Rendered as a small gold heat bar per row.
- **Priority** = new `Priority` frontmatter field, integer 1–5 (1 = highest). Missing →
  treated as 3. Existing task notes get a one-time backfill (done in a vault session,
  not by this app).
- **Mismatch signal** (the point of the tracker):
  - Priority ≤ 2 **and** heat < 0.2 → gold alert marker (neglected).
  - Priority ≥ 4 **and** heat > 0.7 → dim marker (distraction).
- **Ordering:** priority ascending, heat descending as tiebreaker. Status filter cycles
  through All / In Progress / To Do.
- **Keys:** `j`/`k` move · `Enter` open note in a center tab · `t` touch (set
  `Last Progress` to today) · `p` cycle priority · `f` cycle status filter · `r` force
  rescan.
- **Writes** (`t`, `p`) modify only the single frontmatter line and must round-trip the
  rest of the file byte-for-byte. This is the highest-risk operation in the project and
  gets the densest test coverage.
- **Refresh:** rescan on file mtime changes (poll every 5s).

### Center pane — tabs (nested tmux)

- Inner session `griot-center`; its status bar, styled gold-on-navy, is the tab bar.
  Mouse-clickable tab switching (tmux 3.4 mouse mode).
- Prefix-less bindings chosen to avoid Claude Code collisions: `⌥t` new Claude tab,
  `⌥w` close tab, `⌥1`–`⌥9` jump to tab.
- `griot-view <note-path>`: helper that opens a note in a new inner window rendered
  with `glow` pager using the Vibranium style. The left pane's `Enter` shells out:
  `tmux new-window -t griot-center "griot-view '<path>'"`.
- New Claude tabs start in the configured default working directory.

### Right pane — `griot-status` (Textual app)

A vertical widget stack. Every widget is isolated: it has its own refresh timer, and on
any failure it shows its last value with a stale-data indicator (`◌`) — a widget error
never crashes the pane.

| Widget | Source | Refresh |
|---|---|---|
| Kimoyo beads | Textual timer animation; traveling gold pulse across a bead strip. Pulse rate doubles for ~10s whenever any status widget changes state (tunnel drops, VPN flips, meeting < 15 min away). | 150 ms |
| Clock | system time | 1 s |
| Weather | Open-Meteo API (keyless; lat/lon from config) | 15 min |
| Calendar | macOS Calendar via EventKit (`icalBuddy` or PyObjC) — requires the Google account enabled in System Settings → Internet Accounts. No OAuth. Shows the next ~5 events for today/tomorrow. | 60 s |
| Battery | `pmset -g batt` | 30 s |
| WiFi | SSID from `ipconfig getsummary en0` + interface-up check (`airport` is deprecated on modern macOS) | 15 s |
| Redis tunnel | TCP probe on `localhost:36379` (the `tunnel.sh` bastion tunnel) | 10 s |
| VPN | `scutil --nc list` → any Corp VPN service `(Connected)` | 15 s |
| Claude spend | `npx ccusage` monthly totals over `~/.claude/projects` JSONLs (local; no API key). Shows month-to-date USD. | 10 min |

All network/subprocess calls run off the UI thread (Textual workers).

## Configuration

`~/.config/griot/config.toml`:

```toml
vault_path = "~/Documents/ObsidianVault"
tasks_dir = "Notes/Tasks"
claude_default_dir = "~/code"
redis_tunnel_port = 36379
[weather]
latitude = 0.0    # set at install
longitude = 0.0
```

## Error handling

- Launcher: missing dependency → named, actionable message; never a stack trace.
- Task file writes: parse failure → task listed with a warning glyph, file left
  untouched; write path is atomic (write temp, rename).
- Status widgets: degrade to stale indicator, retry on next tick with backoff.
- Vault unavailable (iCloud not synced): left pane shows an explicit "vault not found"
  state instead of an empty list.

## Testing

- **pytest:** heat decay math; priority/mismatch logic; frontmatter read → modify →
  write round-trip preserves all other bytes (property-style tests over real task-file
  shapes); config loading.
- **Textual pilot:** smoke tests that both apps mount, render, and handle key events.
- **Manual:** tmux layout, Claude tab lifecycle, glow rendering, status truthfulness
  (pull the tunnel down, toggle VPN, unplug power).
- TDD throughout per superpowers workflow.

## Out of scope (YAGNI)

- Creating new tasks from the TUI (Griot vault sessions already do capture).
- Editing note bodies in the center pane (viewer only; editing happens in Obsidian or
  Claude Code).
- Google Calendar API/OAuth (replaced by EventKit).
- Linux/Windows portability; this is macOS-only by design.
- Historical heat analytics or persistence beyond what frontmatter already stores.
