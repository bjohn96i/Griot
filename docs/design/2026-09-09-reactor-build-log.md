# Reactor build log — 2026-09-09

Companion to [the spec](2026-09-09-reactor-design.md) and [the plan](2026-09-09-reactor-plan.md).
The kitty-era log is [here](2026-09-09-brain-background-build-log.md).

Seven tasks, executed by subagent with a scoped review after each, then a whole-branch
review and one fix wave. This records what the plan got wrong, what the tests failed to
catch, and the decisions taken without asking. It exists because the branch is unpushed
and awaiting review, and reviewing it is much faster with this in hand.

Range `5df84e3..a86c836` is the fix wave; `ac748b7..a86c836` is the whole branch.
Final state: **399 passing, 0 failing**.

## The plan was wrong five times

Each of these was found by the implementer working the task, not by review, and each was
reported rather than papered over. That is the single most useful behaviour observed in
this run.

**1. `_folder()` returned the wrong folder.** The brief specified `return parts[-2]` under
a docstring reading "top-level folder under the vault". Those differ for any note more than
one level deep. Measured on the live vault: by immediate parent there are 173 folders, so
`Tasks` (66 notes) wins the outermost ring while ~170 leftover folders pile onto ring 1 at
**5.5 notes/dot** — the plan's own flag threshold is 3.0. The reactor came out inverted:
crowded inside, empty at the rim. Fixed by deriving the vault root via `commonpath` over the
real paths' dirnames. After: 0.20 / 1.33 / 1.70 / 1.70 notes per dot, outermost carrying the
most. The brief's flat test fixture (`/vault/{folder}/note{i}.md`) could never have caught
this, because at one level deep the two definitions coincide.

**2. The core level was unsatisfiable.** The brief drew the always-on core at `LEVELS - 1`
= 4 while capping notes at 3, so a resting frame's max level was 4 and a hot frame's was
also 4 — its own test asserting `hot > quiet` could not pass. No smaller fix existed:
lowering the core alone leaves both at 3. Both halves (core to `LEVELS - 2`, plus a new
`_level_for` tier at energy ≥ 0.75) were forced.

**3. The arc never reached the interior.** The brief's Cartesian bow left a near-parallel
ring-3 pair at radius 26, outside the 10 < r < 15 band its test counted. Rewritten in polar
coordinates. The test could not justify that rewrite — both forms score 19/20 on it — but
under Cartesian scaling two *antipodal* nodes lerp through the origin, so the spark draws a
straight line through the centre of the core. Measured minimum distance from centre at
head=0.5: **1.0 Cartesian vs 8.0 polar**, against `CORE_RADIUS` 6. With hash-scattered
angles over 986 nodes, near-antipodal pairs are common. Now pinned by its own test.

**4. The widget code raised on its own test.** `pulses.positions` needs numpy-style vector
subtraction; `reactor.positions()` returns plain tuples. And the brief hit-then-advanced in
the same tick, decaying a fresh READ pulse to 0.85 × exp(−1/1.2) = 0.3694 against a
required > 0.5 — the pulse was dead on the tick that lit it.

**5. Task order was inconsistent.** Task 6 had to replace `settings.DEFAULTS` while the
kitty pipeline that read those keys was still live, and was forbidden from deleting it
because that was Task 7's job. There was no way to finish Task 6 green; commit `0979574`
sits in history with 10 failures, all `KeyError: 'fps_idle'`. Task 7 was reordered ahead of
review and the suite went green. Task 7 should have come first.

## Six vacuous tests

Every one passed while the behaviour it named was absent.

| Test | Why it caught nothing |
|---|---|
| `test_the_biggest_folder_takes_the_outermost_ring` | Fixture's folder order already matched size order |
| `test_...same_path_same_angle` | Passed for a constant `angle_of` |
| `test_...positions_inside_canvas` | Passed if `positions` collapsed everything to the centre |
| `test_the_core_is_drawn_at_the_centre` | Asserted the middle row was non-empty; housing and spokes fill it with the core deleted |
| `test_...vault_directory_vanishes` | Passed via the empty-vault guard, not the `except OSError` it named — `rglob` on a missing dir returns empty rather than raising |
| `test_a_cell_takes_the_brightest_level_plotted_in_it` | Plotted ascending (1 then 3), so "brightest wins" and "last wins" are indistinguishable |

The last one mattered concretely: `scene()` plots arcs at level 3 *before* notes at level 1,
so a broken guard would let resting notes punch holes through arcs.

Two more tests were weak rather than vacuous. The interior-cascade test discriminated by
**one dot** (19 vs 20), because the housing spokes' real quantized spread is r 10.6–13.9 and
so falls inside the 10 < r < 15 band being counted — it measured a graze, not a crossing.
Replaced with a minimum-lit-radius comparison: margin 24.90 against a required 3, and it now
survives `ARC_STEPS` perturbed to both 8 and 22, which is the point, since tuning those
constants is exactly what comes next.

## Two of my own instructions were wrong

Recorded because the implementers caught both and the corrections are load-bearing.

- I claimed the no-hex-literals constraint was **enforced repo-wide by a test**. It was not.
  The only such test scanned one file, `brain/render.py` — which Task 7 deletes. Left alone,
  the feature would have ended with zero enforcement of its own colour rule. Now
  `test_no_hex_literals_outside_theme_module` in `tests/test_theme.py`, scanning all of
  `src/griot/*.py` except `theme.py`.
- I prescribed a test method for the antipodal arc — diff a fired scene against a quiet one
  and inspect the added dots — that **does not discriminate**. The core disc's rendered
  footprint is ~5.8 dots after cell quantisation, masking the entire r < 6 danger zone in
  both frames. Rewritten to drive `_draw_arc` directly on a bare canvas. Testing a private
  function is right here precisely because the public path hides the behaviour under test.
- Smaller: my predicted ring-0 count of 35 double-counted the phantoms (correct: 5 root
  notes + 15 phantoms = 20), and the `HOUSING_RADIUS + 3` floor I specified was below the
  housing's true reach of 13.038.

## What the whole-branch review found

It rendered real-vault frames first: the resting picture reads well — four clean rings,
300 lit cells of 946, not mush. Then seven findings, verdict *not yet fit to hand over*.

- **Births were lossy.** `_rebuild()` sat inside the `for index in poll(now)` loop and
  replaced `self.pulses`, zeroing energy. Three notes in one turn animated one. It also
  erased cascades in flight (energy sum 1.494 → 1.000). Fixed by hoisting the rebuild and
  carrying state across **by path** — including in-flight sparks, since carrying energy
  alone still cancels every hop to come.
- **Launch replayed history.** `Spool.__init__` set `offset = 0` and `Event.ts` was parsed
  but never read, so the whole backlog fired as if it had just happened: 12 of 16 nodes above
  0.5 energy and 72 sparks on the first frame. Now seeded to the file's size.
- **The core never reacted, and the README said it did.** `breath` depended only on a
  free-running sine and `_draw_arc` was only ever called between two ring nodes. The spec
  asserts "every event feeds the core" three times. Implemented rather than documented away:
  `scene()` gained `core_energy`/`feeds`, the core swells and steps to `LEVELS - 1`, and
  `_draw_feed` arcs inward from the hit note. The resting frame is pinned cell-exact.
- **A 63 ms vault walk blocked the event loop every 5 s**, stalling the whole status app,
  not just the reactor. `fingerprint()` alone was 61 ms of it — 1,013 `rglob`+`stat` calls,
  not the 1.7 ms JSON parse. Moved to a worker thread: worst main-thread gap 63.5 → 15.3 ms
  against a 10.9 ms idle baseline. `BirthWatcher` split into `due`/`mark`/`scan`/`adopt`,
  with only the pure `scan()` off-thread.

A pre-existing defect surfaced during that work: the rebuild was gated on `born`, so a
**deleted or renamed** note left `rings` and `pulses` sized for a vault that no longer
existed. Now gated on the fingerprint.

## Open, deliberately

- **Ring radii are absolute dots and do not scale with the widget.** `RING_RADII = (16, 24,
  32, 40)` assumes 43×22. Measured clipping: 12% of notes lost at 36 columns, 25% at 30, 74%
  at 24×12. The real pane is 43 wide, where nothing clips, and the fix touches geometry that
  was reviewed and closed — but **the failure mode is silence**, so it must not be forgotten.
  Fix is scaling by `min(width, height) / 88.0`.
- **A hot note out-shines the core.** `ramp()` paints the core `accent_bright` (level 3) and
  a note at energy ≥ 0.75 `reactor_core` (level 4), the brightest token — the reverse of what
  the theme work assumed. Plausibly right (activity flashes hotter than ambient), but it
  needs eyes on a screen.
- **Ring 0 is sparse** at 0.20 notes/dot against ~1.70 outside, because the rank formula
  drops every folder past rank 2 onto ring 1. Matching the spec's grouping needs a size-tier
  constant the plan never defines. The review looked at a rendered frame and thought it fine.
- **`pulses._sparks` is read from the widget** — a private attribute across a module
  boundary, because `pulse.py` was closed to changes. The re-reviewer would add a narrow
  export/import method to `Pulses` instead, and is probably right on the merits: the current
  shape breaks silently if that tuple ever changes.
- **A teardown race.** `_marshal`'s `call_from_thread` is unguarded, so a worker finishing
  mid-teardown can raise and leave `_scanning` stuck. The app is exiting; cosmetic.
- **`Reactor.__init__` builds the graph synchronously** — ~60 ms once at launch. One-time,
  left alone.
- **`brain_enabled=1` outlives the app**, so the hook keeps appending (~96 B/tool call) with
  no reader. The spool-offset change improves it: the seeded offset is already past
  `max_bytes`, so a stale file is rotated on frame one instead of read through.
- **An intermittent test.** One run during wrap-up reported `1 failed, 398 passed`; the two
  runs either side of it, and every run before, reported 399 passing. I did not capture
  which test it was before the output scrolled, so this is an observation, not a diagnosis.
  A ticker test in `tests/test_sound.py` was known to fail roughly one run in three during
  the kitty-era work and is the likeliest candidate — it predates this branch either way.
