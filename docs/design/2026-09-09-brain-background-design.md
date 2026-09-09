# Griot Brain — Design Spec

**Date:** 2026-09-09
**Status:** Approved by Johnathan (2026-09-09)
**Project:** `~/Documents/Personal/Griot`

## Purpose

Put the vault's link graph behind the center pane as a living background: nodes
floating, electrons travelling the connections, and a visible bloom on the node for
whatever note Claude is reading or writing. A brain scan of the vault, running under
the Claude Code session rather than beside it.

## Feasibility (measured, 2026-09-09)

The obvious approach does not work, so the evidence is recorded here to stop anyone
re-deriving it.

| Probe | Result |
|---|---|
| kitty graphics `z=-1`, no tmux | Works — image under text, even under opaque cell backgrounds |
| kitty graphics `z=-1`, in tmux | **Fails** — renders only via unicode placeholders, so the image occupies real cells and any app writing there destroys it |
| Graphics protocol through 2 nested tmux layers | Escapes arrive (`_Gi=77;OK`), but rung 2 already rules the approach out |
| kitty `background_image` via remote control | **Works** — verified under real Claude Code inside nested tmux |
| Ghostty 1.3.1 `background-image` | Displays identically, but **cannot be animated** — no IPC, `SIGUSR2` is a no-op, `SIGUSR1`/`SIGHUP` terminate it |

**The mechanic.** kitty draws `background_image` *below cell backgrounds*. A cell with
an explicit background hides it; a cell using the terminal default reveals it. Measured
on a 120x40 Claude Code screen: exactly **11 cells** carry an explicit background
(`48;5;16`, the logo). Everything else — borders, input box, status line — is default
background, so the image shows through ~99.8% of the pane.

**The mask is free.** `griot.tcss:1` sets `Screen { background: $bg }`, so the tasks and
status panes paint every cell opaque and occlude the background image on their own. The
brain appears in the center pane only. No geometry, no pane-width tracking.

**Cost.** Benchmarked at 900x560, `compress_level=1`, on a synthetic **1,082-node /
4,089-edge** graph. The real graph is 986 / 2,523 — fewer nodes (-9%, affecting the
5.3 ms repulsion) and far fewer edges (-38%, affecting the 12.5 ms render), so the
figures below are upper bounds with real margin.

```
repulsion, grid + 3x3 neighbours      5.3 ms   (vs 26.5 ms for O(n^2))
render 4089 edges + 1082 nodes + PNG 12.5 ms
springs / centering / integrate      ~2   ms
                                     -------
per frame                            ~20  ms   -> 51 fps ceiling

active 15fps   animator 30% + kitty 23%  = ~53% of one core
idle    3fps   animator  6% + kitty  6%  = ~12% of one core
unfocused                                = 0%
```

kitty's figures are measured; the animator's are measured per-stage and summed.

## Architecture

A standalone process, `griot-brain`, launched detached by `bin/griot` alongside
`griot-tasks` and `griot-status`. Not a thread inside a Textual app: it needs its own
pause/resume lifecycle, must not block a pane's event loop, and must be able to die
without taking a pane with it.

```
Claude tool call
      |
      v
bin/griot-disk  (PostToolUse hook — exists; already classifies read vs write)
      |
      v
~/.cache/griot/brain/events        append-only spool
      |                            "<epoch> <read|write> <abs path>"
      v
+---------------------------------------------+
| griot-brain                                  |
|   graph.py   vault *.md + wikilinks -> nodes,|
|              edges, adjacency  (cached)      |
|   events.py  tail spool -> path -> node id   |
|   sim.py     grid repulsion + springs +      |
|              temperature floor + impulses    |
|   render.py  PIL frame, theme palette        |
|   app.py     adaptive clock, focus gate      |
+----------------------+-----------------------+
                       |  persistent unix socket
                       |  chunked base64 set-background-image
                       v
                 kitty --listen-on
                       |
                       v
        window background, below all cell backgrounds
```

## Components

### `graph.py` — the vault graph

Nodes are `*.md` files; edges are wikilinks resolved by basename, matching Obsidian.
Measured on this vault by the shipped builder: **971 real notes + 15 phantom = 986
nodes**, **2,523 edges**, 352 orphans (36%), hubs to degree 134 (`SAPI Caching
(SWE-4336)`), median degree 5 among linked notes.

> Corrected 2026-09-09 during implementation. The earlier figures here (1,118 nodes /
> 147 phantom / 2,696 edges / degree 219) were wrong in three ways: they counted
> attachments as notes (87 `Pasted image *.png` embeds, 9 `.base` view files, 8 PDFs
> and images), they counted `[[...]]` occurrences inside fenced code blocks, and the
> degree figure was measured per link occurrence while the builder dedupes edges.

- Unresolved targets are **kept as phantom nodes**, matching Obsidian. They render
  hollow — a ring in `muted`, no fill, reduced radius — so a note you have not written
  yet is visibly distinct from one you have. They can never be hit directly (no file to
  read or write) but they do carry the propagating wave from their neighbours.
- **Artifact filter.** Some apparent unresolved targets are parse noise rather than
  intended notes: the top four on this vault are `Bet-Request-Py\`, `'game'`, `1`, and
  `Projects.base`, and 117 of the 147 have a single reference. Links inside fenced code
  blocks are skipped, as are targets that are purely numeric, carry a file extension
  other than `.md`, or contain characters illegal in a filename. This is a filter, not a
  reference-count threshold — a genuine note you have linked once but not yet written is
  exactly the phantom worth drawing.
- Orphans are **kept**, floating free. They are the dust that makes the field read as
  tissue rather than a diagram.
- `.trash`, `.obsidian`, `.git` excluded.
- Cached to `~/.cache/griot/brain/graph.json`, invalidated by a fingerprint of note
  count plus max mtime.

### `sim.py` — the layout

Live force simulation with a fixed `dt` per frame, not wall-clock. Idle at 3fps
therefore drifts calmly and an active burst at 15fps genuinely quickens — the rate
change is part of the effect.

```
repel    grid + 3x3 neighbour cells, 60 px cells (short-range only)
spring   2520 edges, k * (len - rest)
center   weak pull toward centroid
temp     gaussian jitter — the graph never converges
mass     proportional to degree; keeps hubs from being flung
damp     v *= 0.85
```

Mass scales with degree, not its square root as this spec first said: measured
over 8 seeds on a 60-node star, `sqrt(degree)` let the hub move 3.6x *more* than
its leaves (0/8 seeds satisfying the property), while `1/degree` holds it at 0.54x
(8/8). Corrected 2026-09-09 during implementation.

The temperature floor is load-bearing, not decoration: without it a force layout
settles within a few hundred frames and freezes, which is the opposite of the brief.
Cell-local repulsion alone clumps at cell boundaries; the 3x3 neighbourhood is
required for correctness, and is what the 5.3 ms above measures.

### `render.py` — frames

PIL, `compress_level=1` (8 ms cheaper than the default 6). Node radius scales with
`sqrt(degree)` so hubs look like hubs. Colours come from theme tokens — no hex
literals, matching the existing theme contract:

| element | token |
|---|---|
| edges | `outline` |
| ambient nodes | `muted` |
| pulse ramp | `accent` -> `accent_bright` |
| read pulses | `secondary` |

`outline` rather than `border` deliberately: Dataterm's `border` is `#000000` and would
render every edge invisible against its own background.

### Pulse model

Each node holds energy `e` in `[0,1]`, decaying exponentially. On a hit, `e = 1.0` and a
wave schedules neighbours at ~0.12 s per hop, amplitude 0.55 then 0.30, dying at hop 3.
So a hub write blooms a whole cluster and an orphan write barely flickers — the vault's
structure becomes visible through activity.

Electrons ride each edge at parameter `t` in `[0,1]`:

```
speed  v = v_ambient + boost * max(e_a, e_b)
size   r = r0 + r1 * max(e_a, e_b)
```

Two electrons per edge, evenly offset in `t`, so an idle graph still reads as
trafficked. They always drift; they grow and accelerate on the node being accessed.

Read and write differ, mirroring the asymmetry `sound.py` already established for the
drive (write is the heavier event):

| | write | read |
|---|---|---|
| bloom | full, 3 hops | 60%, 2 hops |
| decay | ~1.4 s | ~0.5 s |
| colour | `accent_bright` | `secondary` |
| physics | impulse pushes neighbours apart | none |

### `events.py` and the hook change

`bin/griot-disk` gains one append: `<epoch> <read|write> <abs path>`.

**The care point:** the hook currently returns early when sound is disabled or muted.
The spool write must happen *before* those gates, or the brain goes dark whenever the
drive is muted. Two separate concerns currently share one early-exit path.

Path extraction stays plain sh, no jq: `grep -o '"file_path":"[^"]*"'`. Bash-tool writes
carry no `file_path` and therefore produce no node pulse — the drive still clicks, the
brain stays still. A deliberate gap, not a bug.

Spool mechanics: append-only, `O_APPEND` (atomic for short lines), reader tracks an
offset and rotates past 64 KB. Explicitly **not** a FIFO — a FIFO with no reader blocks
its writer, and this writer runs on every one of Claude's tool calls. A stalled hook
would stall Claude.

### `app.py` — clock, socket, lifecycle

- Socket discovered from `KITTY_LISTEN_ON` (verified to propagate into tmux panes,
  including panes split after session creation), falling back to `[brain].socket`,
  validated by connecting.
- Wire format: chunked base64 `set-background-image` over one persistent connection,
  ~2 KB per chunk, an empty-data message closing the stream. Measured 0.4 ms per frame
  to send.
- Adaptive clock: `fps_idle` normally; any hit sets a deadline of `now +
  active_window` and the clock runs at `fps_active` until that deadline passes, then
  steps straight back to `fps_idle`. Further hits push the deadline out rather than
  stacking. Paused while the kitty window is unfocused (polled over the existing
  socket, not a new connection).
- Detached process with a pidfile at `~/.cache/griot/brain/pid`; `griot restart` kills
  it. On exit it clears the background image, so a crash never leaves a frozen frame
  burned behind the terminal.

## Configuration

New `[brain]` section, opt-in:

```toml
[brain]
enabled       = false   # requires kitty with remote control
socket        = ""      # optional; overrides KITTY_LISTEN_ON discovery
fps_idle      = 3
fps_active    = 15
active_window = 4.0     # seconds a hit keeps the frame rate up
size          = [900, 560]
hops          = 3
```

Required in the user's `kitty.conf` (documented in the README — griot does not launch
the terminal):

```
allow_remote_control     socket-only
listen_on                unix:/tmp/kitty-griot
background_image_layout  scaled
background_tint          0.85
```

`background_tint` is the readability dial if the graph ever fights Claude Code's text.
Note `allow_remote_control yes` is **not** sufficient — `listen_on` is rejected under it.

## Error handling

Every condition below logs once and exits 0, leaving the workstation untouched.

| condition | result |
|---|---|
| `enabled = false` | never starts |
| no `KITTY_LISTEN_ON` and no configured socket | does not start |
| numpy missing | does not start |
| vault unreadable | does not start |
| socket dies mid-session | exits; panes unaffected |

The feature is opt-in and self-disabling, so the repo stays runnable in Warp, Ghostty,
or anywhere else — minus this one feature.

## Testing

Following the existing `tests/` structure:

- `test_brain_graph` — basename resolution, orphans kept, unresolved kept as phantom
  nodes, artifact filter (code fences, numeric, non-`.md` extensions, illegal
  characters), cache invalidation on mtime change
- `test_brain_sim` — seeded determinism, no NaN, kinetic energy stays above zero (the
  temperature floor's actual contract), hub mass scaling
- `test_brain_pulse` — hop amplitudes 1.0 / 0.55 / 0.30, decay curves, read vs write
  asymmetry
- `test_brain_events` — spool parsing, path-to-node mapping, offset tracking, rotation
- `test_hook` — extend the existing file: **a spool line is written even when the drive
  is muted** (the regression the reordering above invites)
- `griot-brain --selftest` — sends three frames and exits, covering the socket path that
  cannot be unit tested

## Out of scope (YAGNI)

- Ghostty support — displays but cannot animate; revisit only if it ships IPC
- Per-pane backgrounds — the Textual panes mask themselves for free
- Node labels, hover, click — it is a background, not a graph explorer
- Pulses for Bash-tool file writes — no `file_path` in the payload to map
