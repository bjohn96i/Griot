# Griot Reactor — Design Spec

**Date:** 2026-09-09
**Status:** Approved by Johnathan (2026-09-09)
**Supersedes:** `2026-09-09-brain-background-design.md`
**Project:** `~/Documents/Personal/Griot`

## Purpose

Show the vault's activity as an arc-reactor-style synapse map in the bottom of
the right pane. Notes are points on concentric rings, the core is the vault
itself, and every read, write and newly created note lights its own position
and feeds the core.

The point is appreciation, not monitoring. Notes accumulate quietly and are
rarely seen as a body of work; this makes the second brain visible, and makes
a new note an event you can watch happen.

## Why this replaces the kitty background

The previous design rendered the graph behind the centre pane using kitty's
window `background_image` over its remote-control socket. It works — it was
built, tested and run — but it ties the workstation to one terminal, and that
cost showed up within hours of switching: pasting images into Claude Code
stopped working, because kitty does not hand image-flavoured clipboard data to
the application and its `clipboard_control` default refuses clipboard reads.

Griot is otherwise terminal-agnostic. Trading that for one background
animation is a bad trade, particularly when the same backend can drive a
widget that works everywhere.

The kitty implementation is deleted rather than kept behind a flag. It stays
in git history and in `2026-09-09-brain-background-build-log.md`; the design
spec is marked superseded rather than left standing as if it were current.

## What carries over

The expensive thinking was never about pixels:

```
KEEP    brain/graph.py    vault -> nodes, edges, folders, phantom notes
KEEP    brain/pulse.py    energy, the spark cascade, idle twinkles
KEEP    brain/events.py   spool reader with offset tracking and rotation
KEEP    bin/griot-disk    the PostToolUse hook, unchanged

DELETE  brain/render.py   PIL pixel renderer
DELETE  brain/kitty.py    remote-control client
DELETE  brain/app.py      detached animator, pidfile, focus gate, log
DELETE  brain/sim.py      force layout — ring positions are deterministic
DELETE  griot-brain       console script
DELETE  bin/griot         spawn and restart teardown
```

Deleting the animator process removes a whole class of failures found during
the kitty build: frames dropped while the window was unfocused, stale pidfiles
bricking `griot restart`, texture-upload cost, socket wedging on unread acks.
None of it can happen inside a Textual timer.

## Geometry

The right pane measures 43 columns. A block of 22 rows at the bottom gives
43x22 cells, and braille packs 2x4 dots per cell — **86x88 dots**, centred at
(43, 44), maximum radius 42. A braille dot is roughly 4.5 x 4.75 real pixels,
so the canvas is very nearly square and a circle is undistorted.

```
        ╭─────────────────────────╮
        │      · · ·  ·  · · ·    │   r=40  outer data ring
        │   ·   · ╭─────────╮ ·   │   r=32
        │  ·  ·  ╱  ·  ·  ·  ╲ ·  │   r=24
        │  ·  · │   ▟█████▙   │ · │   r=16  inner data ring
        │  ·  · │   ███████   │ · │   r=10  housing
        │  ·  · │   ▜█████▛   │ · │   r<=6  core, the vault
        │  ·  ·  ╲  ·  ·  ·  ╱ ·  │
        │   ·   · ╰─────────╯ ·   │
        │      · · ·  ·  · · ·    │
        ╰─────────────────────────╯
```

**Rings are sized to their folder.** A ring at radius r holds 2*pi*r dot
positions, so the dominant folders take the outer rings where there is room.
Measured on this vault:

```
r=40   251 positions   Swish Analytics          428   ~1.7 notes/dot
r=32   201 positions   Tech Library             378   ~1.9 notes/dot
r=24   151 positions   AD + Testing + Cyberpunk 158   ~1.0 notes/dot
r=16   100 positions   Griot, Templates, SWE QA,
                       Files, vault root         35   spare
```

Two folders hold 81% of the vault, which is why rings are assigned by size
rather than one folder per ring.

Those are *file* counts. The graph collapses notes sharing a basename to one
node — 1,013 files become 971 nodes — so each ring carries slightly fewer
points than its folder has files. A collapsed note takes the folder of
whichever path the builder kept. The counts above are therefore upper bounds
on ring occupancy, which is the safe direction: rings will be emptier than
planned, never fuller.

**Phantom nodes have no file and no folder.** The 15 unresolved link targets
the graph keeps go on the innermost ring, drawn as hollow points, the same
distinction the pixel renderer made. They can be lit by a cascade reaching
them but can never be read, written or born.

**Not every note gets a unique dot, and that is accepted.** Where notes share
a position the dot's brightness reflects how many sit there. A specific note
still lights a specific spot; the spot is not exclusive to it.

**Angular position is a hash of the note's path.** It never moves — not
between frames, not between sessions, not after a restart. This is the
property that makes the vault recognisable rather than abstract: a note you
work on often occupies a place you learn.

**The interior stays dark at rest.** The 2,523 links are deliberately not
drawn as chords. At this resolution they are a grey wash — the same mistake
the pixel version made with its edge haze, which cost a round to diagnose.
Chords appear only while a cascade is travelling, so an arc across the disc
always means something is happening.

**Rotation is a single added angle.** Everything is polar, so turning the
field cannot shear or collapse the way rotating a flat cartesian layout did.

## Behaviour

**At rest.** The core breathes on a slow cycle. Idle twinkles continue as
tuned: ~14 per second across the vault at 0.22 amplitude and 0.8s decay,
holding roughly 27 notes glowing at any moment. Twinkles set energy directly
and never cascade.

**A read.** The note's dot ignites; an arc runs inward to the core, and the
cascade spreads outward through its links. Every event feeds the core, so the
reactor draws power from wherever the work is happening.

**The cascade is the existing spark model, unchanged in timing.** Five hops,
`HOP_FALLOFF` 0.85 giving 0.85 / 0.72 / 0.61 / 0.52 / 0.44, last node firing
at 5.0s. The only difference is geometry: a spark traverses a curve between
two ring positions instead of a straight line between two layout points.

Fan-out drops from 12 to 6. Twelve arcs inside an 86-dot disc is a starburst;
six reads as branching. This is a judgement, not a measurement, and is
expected to need tuning against the real thing.

**A write** is the heavier version — brighter flare, thicker arc, longer
decay — preserving the asymmetry `sound.py` established for the drive.

**A birth is its own event**, and the one the feature exists for:

```
t=0.0   a bright point ignites just outside its ring
t=0.4   it draws inward and settles into its angular slot
t=0.8   an arc runs to the core, which flares
after   the dot is permanently part of that ring
```

Detection is by rescan. `graph.fingerprint` already keys on note count plus
newest mtime, so a check every 5 seconds costs ~1,000 `stat` calls and only
rebuilds when the fingerprint moves. Paths present in the new graph and absent
from the old are births.

**Write suppression.** A note created and written by Claude in the same moment
produces a hook write immediately and a birth up to 5 seconds later. The write
is suppressed when a birth for the same path arrives within that window: the
birth is the better animation and the truer event.

## Components

- **`brain/reactor.py`** — pure functions, no terminal: folder to ring, path
  to angle, polar dots to a braille frame, arc interpolation between two polar
  positions. Testable exactly as `status/animation.py` is.
- **`Reactor` widget** in the status app — a `Static` on a ~12fps interval
  that reads the spool, advances the pulses, and paints. Mirrors the existing
  `Animation` widget's shape.
- **`brain/births.py`** — periodic rescan, diffing note paths against the
  previous graph, and the write-suppression window.

## Palette

Two new theme tokens, `reactor` and `reactor_core`, in all three themes, so
each gets an arc-reactor reading in its own language and the core is always
the brightest thing in the pane:

```
vibranium-night   core #EAF6FF   ring #7FD4FF
vaporwave-mono    core #F2FBFF   ring #01CDFE
dataterm          core #FFF6E0   ring #FFC061
```

No hex literals outside `theme.py`. `tests/test_theme.py` reads
`theme.TOKENS`, so it covers new tokens without modification.

## Configuration

The kitty pipeline's keys — `size`, `socket`, `fps_idle`, `fps_active` — are
all artefacts of streaming PNGs and are removed.

```toml
[brain]
enabled = true
fps     = 12
hops    = 5
```

Frame rate is a smoothness dial only. Every timing in the pulse model is
wall-clock — that was fixed during the kitty build, after a fixed per-frame
step made the graph run at fps/15 times real speed — so 12fps draws the same
five-second cascade that 25fps did, less smoothly.

## Error handling

Every condition leaves the status pane working and the rest of the workstation
untouched. The reactor is a widget, so a failure degrades to an empty block
rather than a dead process.

| condition | result |
|---|---|
| `enabled = false` | the widget is not mounted |
| vault unreadable or empty | widget shows the housing and core, no rings |
| spool missing | no events; idle twinkling continues |
| graph rescan fails | keeps the previous graph, retries next interval |

## Testing

- `test_reactor_geometry` — folder to ring across the real distribution;
  ring capacity against folder size; dots land inside the canvas.
- `test_reactor_stability` — the same path yields the same angle across
  separate `Reactor` instances and a simulated restart. This is the property
  that makes the vault recognisable, and it is the one most likely to be
  broken by a careless change to hashing.
- `test_reactor_frame` — braille frame dimensions match the widget size;
  the core is drawn; the interior is empty at rest and non-empty during a
  cascade.
- `test_births` — a new path produces a birth; an existing path does not; a
  hook write is suppressed when a birth for the same path lands inside the
  window, and is NOT suppressed outside it.
- Existing `test_brain_graph`, `test_brain_pulse` and `test_brain_events`
  carry over unchanged.
- Deleted with their modules: `test_brain_render`, `test_brain_kitty`,
  `test_brain_app`, `test_brain_sim`.

## Out of scope

- Reacting to edits made outside Claude, in Obsidian or elsewhere. The
  reactor shows the assistant's work and the vault's growth.
- Drawing the link graph at rest.
- Any per-note labelling, hover or selection. It is a portrait, not an
  explorer.
- Keeping the kitty background behind a flag.
