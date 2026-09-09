# Griot

A three-pane tmux workstation over an Obsidian vault. The left pane tracks vault tasks
with a heat/priority tracker, the center pane hosts tabbed Claude Code sessions (and
rendered vault notes), and the right pane is a live status stack with a signature
heartbeat animation.

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

Three themes ship. Two sit on true black so the panes blend into your terminal and
Claude Code: **Vibranium Night** (default; dark-navy panels, gold accents) and
**Vaporwave Mono** (grayscale with a hot-pink accent). **Dataterm** deliberately does
not — it is an amber-phosphor screen set in beige case plastic, with black seams
between the panes, and it can whir like a hard drive. See *Themes & animation* below.
Pane widths are configurable under `[layout]` in the config (defaults 20 / 64 / 16).

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
- Three themes (`[theme]`), shared by the Textual apps and the outer tmux borders; each with its own default heartbeat animation and its own idea of whether the machine should be audible.

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
- **Heartbeat animation** (`[animation]`: beads, scope, bars, glyphs) — excites on any state change or an imminent meeting.
- **Clock**, **weather** (Open-Meteo), **calendar** (next events via `icalBuddy`).
- **Battery** — %, AC/battery/charging, drain rate, ETA to 10%.
- **Network** — primary IP, Wi-Fi + VPN, listening ports with owning process, open SSH tunnels.
- **Claude usage** — month-to-date token volume broken out (total, in/out, cache).
- **macOS notifications** when the VPN or Redis tunnel drops, or a meeting is <5 min away.

**Global**
- **Command palette** (`⌥x`) — fzf popup of `[commands]` presets + free-form; runs the choice in a center tab.
- **Quick-capture** (`⌥c`) — type a line; Griot files it into the vault via `/griot:capture`.

## Themes & animation

Pick a theme in `~/.config/griot/config.toml`, then `griot restart`:

```toml
[theme]
name = "vaporwave-mono"     # vibranium-night | vaporwave-mono | dataterm
# [theme.colors]            # optional per-token overrides (hex)
# accent = "#FF71CE"
```

| Theme | Look | Default heartbeat |
|---|---|---|
| `vibranium-night` | navy panels, gold accents | `beads` — the kimoyo pulse |
| `vaporwave-mono` | grayscale, hot pink `#FF71CE`, cyan flashes | `scope` — a sine wave scrolling across a braille oscilloscope, phosphor trail |
| `dataterm` | amber phosphor `#FFB000` on warm-brown `#140F08`/`#1E1710`, khaki `#877254` chrome and card frames, black seams, `UPPERCASE` titles | `glyphs` — a hex data stream with travelling packets |

Colour tokens, by the surface each one paints:

| Token | Surface |
|---|---|
| `bg` | the pane background — Dataterm's lit screen |
| `panel` | card fill; `.panel` is every status widget, so this carries body text |
| `chrome` | filled bars — pane title strip, detail title, pane/detail footer |
| `chrome_text` | text *on* chrome — goes the opposite way to `text`, see below |
| `border` | the seams between panes (tmux `pane-border-style`) |
| `outline` | the frame drawn around a card |
| `select` | the highlighted row |
| `text` `muted` | body text and the tier below it (stale rows, dim animation cells) |
| `accent` `accent_bright` | titles, and the animation's bright cells |
| `secondary` `ok` `err` | status colours |

`border` / `outline` / `select` were one token until Dataterm needed them apart: it
wants black seams between panes, but a black card frame or selection band on a dark
screen is invisible. Same for `chrome` out of `panel`, and for `chrome_text` out of
`text` — chrome is near-black in two themes and a mid-tone khaki in the third, so its
foreground has to go light in one direction and dark in the other. Inheriting `text`
left Dataterm's bars at 2.51:1.

One caveat if you override colours: **a mid-tone cannot carry text.** `#877254` is
4.6:1 against *both* black and white, so the tier below body text has nowhere to go —
`muted` on it lands at 1.67:1. Keep mid-tones in `chrome`, `outline` and `select`,
and leave `bg` and `panel` dark or light.

The heartbeat is configurable independently of the theme:

```toml
[animation]
style = "bars"      # beads | scope | bars | glyphs
speed = 0.10        # seconds per tick
height = 2          # rows
# scope:  wavelength = 12  amplitude = 1.0  trail = true
# bars:   bar_width = 1  gap = 1  wavelength = 8  amplitude = 1.0
# glyphs: glyph_set = "mixed" (katakana | blocks | hex | mixed)
#         mutation_rate = 0.08  packets = 2  packet_length = 5  seed = 0
```

`bars` is a sine wave across spaced vertical bars; `glyphs` is a cyberspace stream whose
cells mutate while bright packets cross it. Every style brightens and tightens for ~10s
when a status flips or a meeting is close.

### The drive

Dataterm can sound like the machine it looks like. Off unless you ask for it:

```toml
[sound]
enabled       = true   # default false — nothing plays until you set this
volume        = 0.15   # 0.0-1.0, the ambient reference level
whir          = true   # the ambient platter loop
seek          = true   # head chatter when a status flips
clicks        = true   # the actuator family: idle tick, write burst, read tap
click_min     = 4.0    # idle tick interval, randomised in [min, max] seconds
click_max     = 20.0
one_shot_gain = 1.8    # transients play at volume x gain, clamped to 1.0
```

`m` in the status pane mutes and unmutes it live, and the footer docked at the bottom
of that pane always shows which state you are in. macOS only; elsewhere every call is a
silent no-op.

**Mute is a flag file**, `~/.cache/griot/sound/muted`, not an in-memory bool. The tasks
and status panes are separate processes — `bin/griot` send-keys into two tmux panes — so
an in-memory flag would only silence half the drive. It also means mute survives a
`griot restart`: if you silenced it before a call, it stays silenced, and the footer is
there to tell you why it is quiet. One `stat` per one-shot is the whole cost.

**The sounds, and what earns them:**

| Sound | Shape | Fires on |
|---|---|---|
| *whir* | continuous platter loop | always, while the pane is up |
| *seek* | ~350ms of head chatter | the `excite()` hook — a status flipped |
| *click* | one lone thunk, 45ms | the idle ticker, at a randomised interval |
| *write* | 3-6 impacts over 290-460ms, then the arm settling | a real vault write — `t` touch, `p` cycle priority |
| *read* | 2-3 lighter, higher taps, ~150ms | a real vault read — opening a task's detail view, the startup scan, `r` force rescan |

An *automatic* rescan stays silent. The 5s poll only rescans when the directory
signature changed, which is usually your own write — and that already sounded.

**Transients need lifting.** A click is only 0.32x the whir's RMS at the same volume,
so one tick under a continuous bed is nearly inaudible. `one_shot_gain` (default 1.8x,
clamped to 1.0) applies to seeks, clicks, writes and reads but *not* the whir, so the
ambient loop stays the reference level and everything else rides above it. At
`volume = 0.15` that puts one-shots at 0.27.

`clicks = false` silences the whole actuator family — idle tick, write and read. If you
want writes and reads without random idle ticking, leave `clicks` on and push
`click_max` out to an hour.

The ambient sounds belong to the status pane; the tasks pane installs a click-only
engine (`whir` and `seek` off, `ticker=False`) so its own writes and reads are audible
without a second platter loop or a double idle tick.

### Hearing Claude work

Griot's own panes only ever see their *own* file operations, which is a small fraction
of what happens to the vault. `scanner.py`'s watch is `tasks_dir/*.md`, non-recursive —
so a note Claude writes under `Decisions/` or `Meetings/` is never noticed, and a read
leaves nothing to detect after the fact. `bin/griot-disk` closes that: wire it to Claude
Code `PostToolUse` hooks in `~/.claude/settings.json` and the drive reacts to the work
actually being done.

```json
{"hooks": {"PostToolUse": [
  {"matcher": "Read|Grep|Glob|NotebookRead",
   "hooks": [{"type": "command", "command": "$HOME/path/to/Griot/bin/griot-disk read",
              "async": true}]},
  {"matcher": "Write|Edit|NotebookEdit",
   "hooks": [{"type": "command", "command": "$HOME/path/to/Griot/bin/griot-disk write",
              "async": true}]},
  {"matcher": "Bash",
   "hooks": [{"type": "command", "command": "$HOME/path/to/Griot/bin/griot-disk auto",
              "async": true}]}
]}}
```

One player is cached per asset inside the panes rather than created per sound: an
`AVAudioPlayer` holds its file open for its whole lifetime, and neither dropping the
reference, nor `stop()`, nor draining an autorelease pool releases it (all three
measured). Created per one-shot, the idle ticker alone leaked ~10 descriptors a minute.
Cached and rewound, the open count is bounded by the number of assets.

`async: true` means the hook never blocks a tool call. `auto` reads the hook's JSON on
stdin and classifies a Bash command: write markers win, so `sed -i`, a heredoc, a
redirect, `mv`/`cp`/`rm`, or `git commit`/`git add` burst, while `cat`, `sed -n`, `grep`
and `git status` tap. `2>&1` is deliberately not treated as a redirect, so a test run
reads rather than writes.

The script is plain `sh` with no Python — it runs on every tool call and must not pay
the ~170ms interpreter startup. Everything it needs comes from
`~/.cache/griot/sound/params`, which `sound.write_params()` renders on install, so
`resolve()` stays the only place `enabled`, `volume` and the gain are decided. It
honours the same mute flag, so `m` in the status pane silences Claude's sounds too.
No params file means griot has never installed an engine, and the hook stays silent.

A hook is invisible when it succeeds, so there is a way to watch it:
`touch ~/.cache/griot/sound/debug` and every play appends a line to
`~/.cache/griot/sound/hook.log` (`rm` the marker to stop). The log is written after
the debounce, so it records what you actually heard rather than every attempt.

**What this does not cover:** writes you make in Obsidian itself, or that obsidian-git
and iCloud sync make. Nothing observes those — catching them would need a filesystem
watcher, which cannot see reads either way. For the same reason griot's *automatic*
rescan stays silent: with the hook installed, Claude's write already sounded, and
sounding the rescan too would double up on every edit.

**Nothing ships as an audio file.** A 5400rpm platter is a 90 Hz fundamental, so the
whir is that sine plus harmonics, a slow bearing wobble and a lowpassed air bed,
synthesized with the stdlib `wave` module and cached in `~/.cache/griot/sound/`.
`22050 / 90` is exactly 245 frames, so a whole number of revolutions is a whole number
of frames — the tone's phase closes at the loop point, and the noise bed, which cannot
wrap on its own, is cross-faded onto its own tail. Seeks are bandpassed noise bursts on
a randomised rhythm. Every actuator sound is built from one impact primitive — a 2ms
noise excitation through two damped resonances, the high ring being the head arm
hitting its stop and the low one the chassis answering — composed into a lone tick,
a write burst, or a lighter read tap. Each comes in three variants with jittered
frequencies and decay times, so nothing ever reads as one sample fired twice. A
burst is a single baked asset rather than scheduled one-shots, so playing one costs
one `play()` call and cannot drift or stack.

**Two playback tiers.** With PyObjC installed (a macOS-gated dependency, pulled in by
default) griot uses AVFoundation's `AVAudioPlayer` with `numberOfLoops = -1`: a real
gapless loop, in-process, nothing to orphan. Without it, the fallback shells out to
`afplay`, which has no loop flag — a supervisor thread relaunches it and you hear a few
ms of silence at the seam every 20 seconds. `sound.best_player()` picks the better tier.

The two other themes set `whir`, `seek` and `clicks` false, so `enabled` alone does
nothing on them; set the flags explicitly if you want the drive under Vibranium.

**Terminal side.** Colours inside the panes come from griot; the terminal's own chrome and
font do not. `uv run griot-theme --warp --write` drops `~/.warp/themes/griot-<name>.yaml`
for Warp to pick up (add `--name <theme>` for one you are not currently running).
Dataterm declares its own 16-colour ANSI ramp rather than deriving one, because a
single-phosphor monitor could not show green or blue: eight dim amber rungs and eight
bright ones, no slot repeated, every rung but `black` clearing 4.5:1 on the screen. Fonts that fit: Space Mono for Vaporwave Mono, Monaspace Krypton
for Dataterm. `griot-theme --tmux` prints the border/accent pair the launcher uses.

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

**Right pane (status):**

| Key | Action |
|---|---|
| `m` | mute / unmute the drive — the footer at the bottom of the pane shows the current state (`DRIVE ON`, `DRIVE MUTED`, or `SOUND OFF` when it is disabled in config) |

The pane has to have tmux focus for `m` to reach it — click it, or `ctrl-b →`.

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
