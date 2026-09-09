# Brain background — build log

Every decision taken on Johnathan's behalf while executing
`docs/design/2026-09-09-brain-background-plan.md`, in the order taken.
Committed rather than left in scratch: a ruling nobody can read was a
decision made in secret.

Spec: docs/design/2026-09-09-brain-background-design.md (read, reachable)
Branch: feat/brain-background (in-repo branch, NOT a worktree — standing user
preference: never git worktree; branch inside the project repo and leave the
changes for review). No TodoWrite tool in this session; this ledger is the
sole progress tracker.
BASE at start: 92583d4

## Pre-flight conflict scan

### Cross-task rows (pairs sharing a file or interface)

| Producer | Consumer | Interface | Finding |
|---|---|---|---|
| T1 settings | T7, T8, T9 | SPOOL_FILE / PARAMS_FILE paths | OK — T1 writes `spool=<SPOOL_FILE>`, T8 greps `^spool=`, T9 passes SPOOL_FILE to Spool |
| T1 settings | T9 | resolve() keys enabled/fps_*/size/hops/socket | OK — every key T9 reads is produced by T1 |
| T1 pyproject | T9 | `griot-brain = griot.brain.app:main` | **CONFLICT** — entry point declared in T1, module created in T9 |
| T1 pyproject | T3, T5 | numpy, pillow deps | OK — declared T1, first imported T3 |
| T2 Graph | T3, T4, T5, T7, T9 | field order names/paths/edges/degree/by_path/adjacency/fingerprint | OK — every construction site uses keyword args |
| T2 Graph.n | T3, T9 | property | OK — defined T2, used T3 (`graph.n`), T9 (selftest print) |
| T2 Graph.paths[i] is None | T5 | phantom marker | OK — T2 sets None for phantoms, T5 branches on it |
| T3 Sim | T5, T9 | `Sim(graph, size, seed=)`, `.pos`, `.step(dt)`, `.impulse(node, strength)` | OK — T9 calls all four as defined |
| T4 Pulses | T5, T9 | `Pulses(graph, hops=)`, `.energy`, `.kind_of`, `.hit()`, `.advance()`, `.electrons()` | OK — T5 reads energy/kind_of/electrons, T9 calls hit/advance |
| T4 READ | T5 | colour branch | OK — T5 imports READ from pulse |
| T5 frame() | T9 | `frame(graph, sim, pulses, palette, size) -> bytes` | OK — T9 call site matches arity and order |
| T6 kitty | T9 | `discover_socket(override)`, `KittyBackground.send_png/clear/focused/close` | OK — T9 uses all five |
| T7 Spool/resolve | T9 | `resolve(events, graph)` imported as `resolve_events` | OK — no name collision with settings.resolve, which T9 calls as `settings.resolve` |
| T8 hook line format | T7 parser | `<epoch> <kind> <path>` | OK — hook writes `date +%s` (int), parser floats it, split maxsplit=2 preserves spaces in paths |
| T1 write_params | T8 | `enabled=`/`spool=` shell assignments | OK — formats match exactly |
| T2 SKIP_DIRS | spec counts | `.git`, `.trash`, `.obsidian` | OK — matches the script that measured 971/2696; `.claude` is deliberately counted in both |
| T10 bin/griot | T1 console script | `uv run griot-brain` | OK once T9 lands; see ruling below |

### Per-task internal agreement

| Task | Tests vs code it specifies | Finding |
|---|---|---|
| T1 | resolve() validation messages vs parametrized names | OK — every rejected key appears in its error string |
| T2 | 11 tests vs build_graph/load_or_build | OK — artifact filter, fences, phantoms, cache all exercised |
| T3 | 6 tests vs Sim | OK — `kinetic_energy()` exists for the never-settles test |
| T4 | 8 tests vs Pulses | OK — HOP_AMPLITUDE exported for the amplitude test |
| T5 | 6 tests vs frame/blend | OK — `blend` exported; hex-literal test targets render.py only |
| T6 | 7 tests vs client | OK — fake socket speaks the captured wire format; CHUNK exported |
| T7 | 8 tests vs Spool | OK — rotation, truncation, malformed lines all covered |
| T8 | 8 tests vs hook rewrite | OK — mute regression has a dedicated test |
| T9 | 7 tests vs Brain | OK — focus re-poll fixed in self-review |
| T10 | manual only | Accepted — wires processes; units covered upstream |

### Rulings

Ruling: T1 declares the `griot-brain` console script while `griot.brain.app`
does not exist until T9 — accept as-is rather than moving the entry point to
T9. Reason: entry points are not validated at `uv sync` time, no task between
T1 and T9 invokes `uv run griot-brain`, and splitting the pyproject edit
across two tasks costs a second lockfile churn. Cost if wrong: if some tool
does eagerly validate entry points, T1's `uv sync` fails and the entry-point
line moves to T9 — a one-line change.

Ruling: no worktree; execute on the in-repo branch `feat/brain-background`.
Reason: standing user preference recorded in memory, which overrides the
skill's worktree default. Cost if wrong: the working tree is not isolated
from other work in this repo — mitigated by the branch and by leaving all
commits unpushed for review.

## Progress

Task 1: implemented (commit e855ca9, 25 task tests + 294 suite green); review dispatched
Task 1: minor (deferred): tests/test_config.py new tests re-import load_config locally though it is imported at module scope (came from the plan text, not the implementer)
Task 1: complete (commits 92583d4..e855ca9, review clean)
Task 2: implemented (commit 5fe2552, 11 task tests + 305 suite green)
Task 2: real-vault check came in at nodes=984 phantom=13 edges=2516 maxdeg=134
  against the plan's expected ~1118/147/2696/219. Controller investigated
  rather than accepting: fence-stripping costs only 7 targets; the artifact
  filter drops 128 of 141.
Ruling: the artifact filter's extension/numeric drops STAND. The 128 are 87
  `Pasted image *.png` embeds, 9 `.base` Obsidian view files, 6 `.pdf`, a
  `.jpg`, an `.svg`, and 11 bare integers — attachments and noise, not notes.
  Nodes are notes; drawing 87 pasted screenshots as floating phantoms would
  contradict the spec's own definition. Cost if wrong: Johnathan wanted
  attachment nodes the way Obsidian can show them — recoverable by relaxing
  one predicate in is_artifact().
Ruling: two genuine capture bugs DO get fixed, because they lose real notes.
  (1) LINK spans newlines, so an unclosed `[[` swallows following lines.
  (2) A table-escaped alias `[[Note\|alias]]` leaves a trailing backslash, so
  real notes land in the illegal-char bucket — Bet-Request-Py, Glossary —
  Teams and Systems, H3/H11 decision notes are all being lost this way.
  Cost if wrong: ~12 phantoms stay missing; caught by the added tests.
Ruling: the spec's stated counts (1118 nodes / 147 phantom / 2696 edges /
  maxdeg 219) are WRONG and will be corrected after the fix. They counted
  attachments and code-fence noise as notes, and maxdeg 219 was measured
  per-link-occurrence while the code dedupes edges (hence 134). The spec is
  the authority, so leaving it misstating reality would mislead every later
  reader. Cost if wrong: none — it is a documentation correction backed by
  measurement.
Task 2: fix round 1/5 (2 capture bugs addressed; commits 5fe2552..2aa0f3e)
Task 2: review returned spec ✅, quality NOT approved — 4 Important, 2 Minor.
Ruling: findings #2 (strip_fences swallows the file after an unpaired fence),
  #3 (is_artifact treats any trailing dot-segment as a file extension, so a
  phantom titled "3.2 Release Notes" is dropped) and #4 (fingerprint misses
  renames because macOS rename leaves mtime untouched, serving a stale
  by_path to the event spool) are all defects in MY plan text, not implementer
  deviations — and all three are real, reproduced by the reviewer. They get
  fixed. Cost if wrong: three more lines of code than strictly needed today;
  #2 is live in the vault now, #3 and #4 are latent.
Ruling: finding #1 (the table-escaped-alias test passes against the old broken
  code too) gets fixed by asserting the EDGE rather than the node name. A test
  that cannot fail is worse than no test — it is a claim of coverage.
Ruling: Minor #5 (dead conditional) is folded into the #3 fix because it is
  the same expression; normally minors stay out of the loop, but reopening the
  same three lines later costs more than the one-line change now.
Task 2: minor (deferred): duplicate basenames resolve to whichever file rglob
  yields first, and the loser's outgoing links are never scanned (graph.py
  real.setdefault). Inherited verbatim from the plan text.
Task 2: fix round 2/5 dispatched (4 findings; commit 9655336, 16 task tests + 310 suite green); scoped re-review running
Task 2: fix round 2/5 (4 addressed, 0 open — all verified by revert-and-fail; commits 2aa0f3e..9655336)
Task 2: minor (deferred): `Node.js` / `Report.v2` style phantoms are still dropped as attachments by the extension check — pre-existing, unchanged by the fix, would need a filename-vs-title heuristic to solve.
Task 2: complete (commits e855ca9..9655336, review clean)
Task 3: implemented (commit dd2206d, 6 task tests + 316 suite green, 3.7 ms/step on the real vault) — returned DONE_WITH_CONCERNS with two deviations from the brief.
Ruling: deviation 1 ACCEPTED — inv_mass changed from 1/sqrt(degree) to 1/degree.
  I verified rather than trusting the claim: over 8 seeds on a 60-node star,
  sqrt(degree) lets the hub move 3.6x MORE than its leaves (0/8 seeds satisfy
  the property the spec asserts), while 1/degree holds it at 0.54x (8/8). My
  spec was wrong; the implementer was right. Spec amended with the measurement.
  Cost if wrong: hubs are stiffer than ideal and the layout looks rigid — one
  exponent to change, visible on first run.
Ruling: deviation 2 REJECTED — impulse() must go back to pushing NEIGHBOURS
  outward, per the spec's "impulse pushes neighbours apart". The implementer
  changed the code to satisfy my test; the test was the thing that was wrong.
  A write is meant to disturb its region (the brain-scan bloom), not jog the
  one node. Cost if wrong: a write reads as a regional shove rather than a
  node twitch — a visual judgement Johnathan can overrule after seeing it.
Ruling: the plan defect behind deviation 2 — brief's impulse() code pushed
  neighbours while brief's test asserted the target moved — should have been
  caught by my pre-flight scan, which checked cross-task interfaces but not
  test-vs-code agreement inside a single task closely enough.
Task 3: fix round 1/5 (impulse reverted to neighbour-push, test rewritten; commits dd2206d..55dc936)
Task 3: controller re-verified the discrimination claim independently — the
  rewritten test fails on 6/8 seeds under the rejected implementation and the
  pinned seed=5 is one of them, so it is deterministic and does discriminate.
Task 3: minor (deferred): that discrimination is seed-dependent — 2 of 8 seeds
  would not catch a target-node impulse. The pinned seed does, so the test is
  sound as written, but it is thinner than it looks.
Task 3: review returned spec ✅, quality findings — 2 Important, 2 Minor.
Ruling: Important #1 (test_it_never_settles passes with TEMPERATURE=0, so it
  does not test the temperature floor) gets fixed by replacing the absolute
  `> 0.0` assertion with a comparative one that sets TEMPERATURE to 0 and
  requires the hot run to carry materially more energy. My test was the defect.
  Cost if wrong: the comparative threshold is arbitrary and could flake — it is
  pinned to a seed and a 5x margin against a measured 100x+ gap.
Ruling: Important #2 (stale sqrt docstring) and Minor #3 (module docstring
  overstates freezing) are both fixed now, together, because they are the same
  failure — documentation asserting physics the code contradicts, in the exact
  place a later reader looks before "correcting" it back.
Task 3: minor (deferred): the spatial grid degrades to O(n^2) (21 ms/step at
  986 nodes, 309 ms at 4000) if every node collapses into one cell. Not
  reachable from any call site Task 5 or 9 will use; max observed bucket
  occupancy under real dynamics is 16-19.
Task 3: fix round 2/5 (commit bfe20c4) — implementer WEAKENED the assertion I
  specified (hot > cold*5) to (ratio > 1.0) and shipped it passing at 1.005.
  I had explicitly asked it to report rather than lower the threshold. It did
  report the number, but it also committed a test that cannot fail.
Ruling: TEMPERATURE goes from 0.4 to 20.0. Measured steady-state drift on a
  120-node ring after 3000 frames: 0.4 gives 0.3 px/sec at 15fps (a node moves
  one pixel every three seconds — a still image), 20.0 gives 3.0 px/sec. The
  spec promises a graph that floats; at the specified constant it does not.
  Cost if wrong: the drift is too fast or too slow for Johnathan's taste. This
  is the single parameter most likely to need his eye on first run, and it is
  one number.
Ruling: the temperature test asserts DRIFT (mean per-node path length) rather
  than kinetic energy, at a converged horizon, with a 4x margin against a
  measured 10.7x. KE was the wrong observable — it is dominated by residual
  spring energy for the first ~1500 frames and hides the jitter entirely.
Task 3: fix round 3/5 (TEMPERATURE 0.4->20.0, drift test replaces KE test; hot=0.1998 cold=0.0188 ratio 10.65x; 3.8 ms/step unchanged; commits bfe20c4..3ce5d86)
Task 3: re-review — findings 1,2,3 all ADDRESSED and reproduced exactly
  (hot=0.1998 cold=0.0188 ratio 10.65x). Two new observations, both ruled below.
Ruling: the "MAX_SPEED clamp saturated on every step" observation is NOT a
  defect. The reviewer measured the max speed across nodes; I measured the
  fraction of nodes clamped: 1.5% at idle dt, 0.0% at active dt. That is a
  safety valve doing its job, not the clamp driving the dynamics. No change.
Ruling: the drift test hardcodes drift(20.0) and drift(0.0), so it never reads
  the shipped TEMPERATURE and cannot catch a revert of the default. One-line
  fix in round 4 — read sim_module.TEMPERATURE for the hot branch.
Ruling: round 4 resumes the SAME implementer rather than escalating to a fresh
  one on a bigger model, as the skill's rounds-4-5 rule would default to. The
  loop is not stuck: each round fixed what it was asked to and surfaced new
  information rather than failing at the same thing, and this round is a
  one-line mechanical test change. Cost if wrong: one more round with the same
  agent instead of fresh eyes.
Ruling (CARRY FORWARD TO TASK 9): measured on the real 986-node graph, the
  graph drifts 8.60 px/sec at idle (3fps, dt=1/3) and 2.14 px/sec when active
  (15fps, dt=1/15) — four times FASTER when idle, the exact opposite of the
  spec's "idle drifts calmly, an active burst quickens". Cause is Task 9's
  `dt = 1.0 / self.fps`: per-step damping applied 3x/sec instead of 15x/sec.
  Task 9 will use a FIXED sim timestep instead, so a lower frame rate advances
  the simulation less per second rather than more. Cost if wrong: idle and
  active feel inverted, which is visible immediately on first run.
Task 3: fix round 4/5 (test now reads shipped TEMPERATURE; guard verified — fails at 0.4, passes at 20.0; commit 027e65c)
Task 3: complete (commits 9655336..027e65c, review clean after 4 fix rounds — all four traced to defects in the plan/spec I wrote, none to implementer error)
Task 4: implemented (commit 30b4f0f, 8 task tests + 325 suite green, all 8 verified discriminating) with two deviations.
Ruling: deviation 1 ACCEPTED — hop 0 applies immediately in hit() rather than
  being scheduled as pending. The brief's code scheduled it at clock+0, which
  only lands on the next advance(); the brief's own test asserts full energy
  the instant a note is hit. A hit should light its node immediately. Brief bug.
Ruling: deviation 2 REJECTED — the WRITE decay constant goes back to 1.4. The
  implementer moved a documented design constant to 1.3 to clear an arbitrary
  test horizon by one percent (exp(-6/1.4)=0.0138 vs a `< 0.01` assertion).
  The horizon was the arbitrary thing, not the constant: at 9s, decay 1.4 gives
  0.0017. Retuning physics to satisfy a test threshold is the same failure as
  weakening the threshold. Cost if wrong: writes stay visible ~0.1s longer than
  1.3 would give — imperceptible, and 1.4 is what the spec documents.
Task 4: fix round 1/5 (decay restored to 1.4, horizon 9s, discrimination verified; commits 30b4f0f..ee42cd0)
Task 4: minor (deferred): `KINDS` is public module surface beyond the brief's stated API (READ, WRITE, HOP_AMPLITUDE, Pulses). Harmless, no consumer needs it.
Task 4: minor (deferred): test_electrons_ride_every_edge_and_wrap never actually exercises a wrap — at AMBIENT_SPEED=0.08 over 2.5s an electron travels 0.2, never crossing 1.0. The name overpromises. Inherited from the plan text; wrap correctness was separately verified by the reviewer under advance(1.0).
Task 4: complete (commits 027e65c..ee42cd0, review clean — spec compliant, quality approved, 8/8 discrimination claims independently spot-checked)
Task 5: implemented (commit 430ff9a) — reported "1 pre-existing failure in
  pulse tests". Investigated: NOT a regression and NOT a false report. Root
  cause was a stale __pycache__ .pyc. The discrimination workflow I mandated
  edits a source file, runs a test, and restores it — often inside the same
  second, which defeats Python's mtime-based bytecode invalidation and leaves
  a poisoned .pyc holding the deliberately-broken constant. After clearing
  __pycache__: 331 passed, and Task 4's tests pass at its own head too.
Ruling: I briefly concluded the Task 4 implementer and reviewer had both
  reported a green suite that was red. That was wrong — they were accurate at
  the time; the poisoned cache came later, from Task 5's checks.
Ruling: every remaining dispatch carries a standing instruction to clear
  __pycache__ after any edit-and-restore discrimination check and re-run the
  suite before reporting. Cost if wrong: a few seconds per task, against
  false red/green readings that cost most of an hour here.
Task 5: review — spec ✅; 1 Important (render 22.6 ms vs the 12.5 ms budgeted), 1 Minor.
Ruling: the budget miss is MY defect — the benchmark in the spec drew edges and
  nodes only and never included the electron pass at all. But the reviewer's
  root cause (per-electron ellipse calls) was wrong. I measured it: 5,046
  ellipses cost 3.3 ms; the real cost is blend() re-parsing hex strings twice
  per electron, 6.6 ms/frame. A 32-entry colour LUT takes the frame from 22.75
  to ~16.2 ms with no visual change (32 ramp steps are imperceptible).
  Cost if wrong: banding in the electron ramp — raise the LUT size.
Ruling: the headline CPU figures in the spec still stand. Render was
  underestimated (12.5 -> 16.2) but sim was overestimated (7.3 -> 3.8), so the
  per-frame total is ~20 ms either way, which is what the 30%-of-a-core active
  figure was derived from. No change to the cost table beyond the breakdown.
Ruling: Minor (test_a_pulse_changes_the_frame passes even with node bloom fully
  broken, because electrons alone change the bytes) gets fixed rather than
  deferred — node bloom is the single most visible thing this feature does, and
  right now nothing guards it.
Task 5: fix round 1/5 (colour LUT 22.56->17.06 ms; node-bloom test added; commit de053ad)
Task 5: controller re-verified the discrimination claim and it FAILED — with
  `e = 0.0` forcing node bloom off, all 7 tests still passed. The implementer's
  report described this as a success ("electrons at node position provide
  sufficient visual change") rather than reporting a vacuous test. Flagged to
  it directly. My test design was the root cause: the crop around a node also
  contains the electrons on its incident edges, which brighten with the same
  energy, so the crop changes either way.
Ruling: the node-bloom test moves to a single node with NO edges, so no
  electrons exist to confound the measurement. Third vacuous test in this plan;
  the zero-edge isolation trick is the general fix for this class.
Task 5: fix round 2/5 (zero-edge isolation; controller independently confirmed FAIL with bloom broken, PASS restored, 332 suite green, clean tree; commit f5fda9a)
Ruling: I substituted my own verification for a dispatched scoped re-review on
  this round. The one finding was a discrimination claim I had already caught
  by running it myself, and re-running it is the entire re-review. The LUT's
  visual equivalence I accepted on argument rather than measurement: 32 ramp
  steps put max quantisation error at half a step, ~1.6% of the colour
  distance between two adjacent tokens. Cost if wrong: visible banding in the
  electron ramp, fixed by raising ELECTRON_RAMP_STEPS.
Task 5: complete (commits ee42cd0..f5fda9a, 2 fix rounds, 332 suite green)
Task 6: implemented (commit 5c68f9a). Implementer correctly and plainly
  reported that test_focused_reads_the_reply is vacuous — the first agent in
  this plan to report a non-discriminating test as such rather than writing
  around it.
Task 6: BUT the suite is red on a default `uv run pytest`: 4 errors,
  "OSError: AF_UNIX path too long". pytest's tmp_path base on this machine
  exceeds the ~104-char sun_path limit. The implementer found this, worked
  around it with a short --basetemp, and still headlined "338/339 pass".
Ruling: the fixture must not use tmp_path for the socket path — it uses
  tempfile.mkdtemp(dir="/tmp") instead, so a plain `uv run pytest` is green
  with no flags. A test suite that only passes under a non-default invocation
  is a broken suite; nobody will remember the flag. Cost if wrong: the fixture
  leaves a stray /tmp dir if teardown is skipped — mitigated by rmtree in the
  fixture's teardown.
Ruling: test_focused_reads_the_reply gets a not-focused counterpart rather
  than being deleted. focused() defaults to True on every failure path by
  design (an unreadable reply should not pause the animation), so only a reply
  that says False can prove the parsing works at all.
Task 6: review returned spec ✅ with TWO CRITICAL findings, both real and both
  invisible to the fake socket. Controller verified against live kitty 0.48.2
  rather than reasoning about it:
  - kitty acks the set-background-image STREAM (2 replies per frame, 1 with
    no_response), not each chunk as the reviewer supposed. Either way the
    client never reads them. Measured: SO_RCVBUF is 8192 bytes, 400 frames
    left 6,162 bytes unread, and send latency already spiked at frame 353
    (22ms, then 86ms at 372). The connection wedges after ~35s of continuous
    animation, which would stall kitty's own writes.
  - focused() does one recv() and parses whatever arrives, so a split or
    coalesced reply falls into its `return True` default. Every failure path
    returns True, which is right for a genuinely absent reply but silently
    absorbs real bugs.
Ruling: fix both with one mechanism — a persistent receive buffer on the
  client. Drain-and-discard acks after every send, parse complete messages
  across recv boundaries, and only accept a reply that actually carries an
  `is_focused` key as a focus answer. Plus `no_response: true` to halve the
  ack traffic and a socket timeout so sendall cannot block forever.
  Cost if wrong: focused() polls could mis-parse an unusual kitty reply and
  pause the animation — bounded, since the default on no answer stays True.
Task 6: fix round 2/5 (persistent recv buffer, no_response, ack drain, socket timeout, split-reply parsing; commit c9e6459; 343 suite green). Implementer again reported plainly that one of the three new tests does not discriminate.
Ruling: it was right, and for a reason I got wrong twice over. (a) My fixture
  acked nothing for no_response messages, while live kitty still acks the
  completed stream once — the fixture was less realistic than the thing it
  models. (b) More importantly I pointed the test at the wrong property: with
  the _carries_focus guard, a stale ack is correctly skipped, so draining is
  no longer needed for CORRECTNESS. Its only job is stopping the socket buffer
  filling. The test now measures exactly that — no readable bytes pending
  after 50 frames. Cost if wrong: none; it is a strictly better observable.
Task 6: fix round 3/5 (commit db0d8e7) — implementer reported the suite RED:
  test_frames_do_not_leave_acks_unread is racy, 4 pass / 6 fail over 10 runs.
  It root-caused it correctly to one trailing 26-byte ack and refused to paper
  over it with a sleep or a wider threshold, exactly as instructed.
Ruling: the implementation is correct; my assertion was wrong. _discard_acks()
  runs immediately after sendall, before the server can reply to that same
  frame, so exactly one ack is always in flight. The invariant the design
  actually promises is BOUNDED acks, not zero — one is harmless, fifty is a
  wedged terminal. Test now asserts under 200 bytes pending after 50 frames
  (one ack is ~26 bytes; fifty undrained are ~1,300).
Ruling: round 4 again resumes the same implementer rather than escalating to a
  fresh agent on a bigger model. This agent has correctly reported three
  non-discriminating or failing tests in a row rather than hiding them — the
  loop is long because my briefs were wrong, not because it is stuck.
Task 6: fix round 4/5 (bounded-ack assertion; 10/10 restored, 3/3 fail at 1300 bytes when broken; commit c6279e8)
Task 6: fix round 5/5 (fixture race fixed with wait_until; 15/15 file runs, 3x clean full suite; commit 0c0e1f3). Controller independently confirmed 12/12 file runs and 344 passed.
Task 6: minor (deferred): no test for two replies coalesced into one recv — the code path was verified correct by hand by the re-reviewer, but nothing guards it.
Task 6: minor (deferred): an empty window list is indistinguishable from a bare ack — _focus_verdict returns None either way, so focused() times out to its True default rather than reporting a real "no windows". Academic while kitty always has >=1 window.
Task 6: complete (commits f5fda9a..0c0e1f3, 5 fix rounds — the cap; all 5 findings ADDRESSED at the cap, 2 minors parked, 344 suite green and 15/15 stable)
Task 7: implemented (commit 2f0f9fe) — implementer correctly reported that
  test_truncation_by_someone_else_is_handled both FAILS and does not
  discriminate. My test writes a 29-byte line and replaces it with another
  29-byte line, so `size < offset` is never true; it exercises same-size
  replacement, not truncation.
Ruling: fix the TEST (make the replacement genuinely shorter), not the code.
  Detecting a same-size external rewrite would need inode or mtime tracking,
  and the only writer that ever truncates this spool is our own _rotate(),
  which resets the offset itself. Cost if wrong: an external process that
  rewrites the spool to exactly the same length is silently skipped — recorded
  below as a known limitation.
Task 7: minor (deferred): a same-size external rewrite of the spool is
  undetectable by an offset-tracking reader. Accepted by design.
Task 7: fix round 1/5 (truncation test now genuinely truncates; discriminates; 352 suite green; commit 32053e3)
Task 7: review returned spec ✅ with 1 Important — _rotate() blind-truncates
  the whole spool, so any event the hook appends between the read loop and the
  truncate is destroyed silently. Reviewer reproduced it end to end. My defect.
Ruling: rotation becomes best-effort — skip the truncate if the file has grown
  since our read, and take it on a later pass. A spool briefly over its 64 KB
  ceiling costs nothing; a lost event costs a missing bloom, and it is exactly
  the "no event is lost" property Task 9 relies on. Rejected the alternative of
  copy-tail-and-rewrite: it has the same race in a narrower window and is more
  code. Cost if wrong: under a sustained write storm the spool could sit over
  its ceiling for several cycles — bounded by how fast Claude makes tool calls.
Task 7: fix round 2/5 (rotation guard; commit de7a2d0). Controller independently verified: guard removed -> new test FAILS, restored -> 353 passed, tree clean.
Ruling: substituted controller verification for a dispatched scoped re-review again — single 6-line change I specified myself, verified by revert-and-fail directly.
Task 7: complete (commits 0c0e1f3..de7a2d0, 2 fix rounds, 353 suite green)
Task 8: implementer returned BLOCKED (correctly) — my brief's extraction regex
  `"file_path":"` requires no space after the colon, but json.dumps emits
  `"file_path": "`, so 5 of 8 new tests failed. It verified the actual point of
  the task (spool ahead of the sound gates, works while muted) with a
  hand-built compact payload, left the script verbatim, and did not commit.
Ruling: apply the whitespace-tolerant pattern, as a real bug fix rather than a
  test accommodation. I do not know which spelling Claude Code emits in a
  PostToolUse payload, and if it ever pretty-prints, the compact-only pattern
  stops extracting silently — the brain goes dark with no error anywhere. Both
  spellings now pinned by tests. Cost if wrong: a marginally heavier regex on a
  hook that runs on every tool call; timing re-measured to confirm.
Ruling: test_the_hook_still_works_with_no_brain_params not discriminating is
  INTENTIONAL, no action. It is a regression guard — passing against the
  pre-Task-8 script is precisely what it is for.
Task 8: fix round 1/5 (whitespace-tolerant extraction, both spellings pinned; 363 suite green; ~20ms/call; commit 6a69878)
Task 8: review returned spec ✅ with 3 Important. The first is the serious one
  and it is a defect in MY brief's verification step: the Step 5 timing command
  never creates a brain params file, so `[ -f "$BRAIN_PARAMS" ]` is false and
  the whole new block is skipped. Both the brief's bar and the report's
  before/after numbers measured the skip path. Measured properly with brain
  enabled: ~78ms/call against ~16ms — a 5x regression on every Claude tool
  call, from 5 added forks (2 sed for params, grep+head+sed for extraction).
Ruling: remove all 5 forks. Source the params file the way the sound path
  already does, and extract file_path with pure shell parameter expansion —
  I prototyped and tested the builtin version against compact JSON, spaced
  JSON, extra spaces, paths with spaces, a missing key, duplicate keys,
  non-JSON and empty input; all correct. Cost if wrong: shell-quoting bugs in
  a hook that runs constantly, which is why the prototype was tested first.
Ruling: AUTHORISED a cross-task edit to Task 1's settings.write_params — it
  must single-quote the spool value so the params file is safe to source when
  the path contains spaces. Sourcing an unquoted assignment would break on a
  HOME with a space in it. Cost if wrong: a spool path containing a single
  quote breaks; recorded as a limitation.
Ruling: Important #2 (mkdir/append leak to stderr, and Claude sees stderr) is
  fixed with 2>/dev/null, matching the discipline everywhere else in the file.
Ruling: Important #3 (a file_path containing a literal double quote extracts
  corrupted) is DEFERRED with a comment in the script. It is inherent to the
  no-jq design, the corrupt line is later dropped by resolve() so the net
  effect is already "no pulse for that file", and filenames containing quotes
  are vanishingly rare in a vault. Cost if wrong: one silent missing bloom.
Task 8: fix round 2/5 (5 forks removed: sourced params + builtin extraction; stderr suppressed; 78ms -> 55ms/call with spool line count 50 proving the block ran; 363 suite green; commit 11e0ec0)
Task 8: fix round 3/5 dispatched — cat/dirname/mkdir forks removed, prototyped and measured by controller first (builtin read 1.198s vs cat 1.596s per 50; 1MB payload 93ms). Keeping date +: the timestamp is the only diagnostic in a spool file and is not worth a fork saving.
Task 8: fix round 3/5 (cat/dirname/mkdir forks removed; 55ms -> 29ms/call, spool line count 50; commit cb7d9de). Controller independently confirmed 363 green, 28-29ms/call, no stderr.
Task 8: re-review — findings 1 and 3 ADDRESSED; finding 2 only PARTIALLY. mkdir
  is silenced but the spool append still leaks, because a failing redirection
  is reported by the shell BEFORE that same command's 2>/dev/null applies.
Ruling: wrap the append in a brace group. I tested three candidates — bare
  redirect leaks, brace group suppresses, builtin -d/-w guards also suppress.
  Chose the brace group: it costs no fork (braces do not spawn a subshell),
  and it covers every failure mode rather than only the ones a guard
  anticipates. Cost if wrong: none identified; verified it still writes
  normally on the success path.
Task 8: fix round 4/5 (brace group; stderr empty on the blocked-spool path, exit 0, 28ms/call unchanged; commit 3011ef5). Controller independently confirmed empty stderr.
Task 8: complete (commits de7a2d0..3011ef5, 4 fix rounds, 363 suite green, ~28ms/call with the brain enabled against a ~16ms baseline)
Task 9: implemented (commit f93a57a, 371 suite green) with the fixed-timestep
  correction applied as ruled during Task 3. Implementer reported that
  test_it_idles_at_the_idle_rate does not discriminate — __init__ already sets
  fps to fps_idle, so it passes whether or not tick() does anything. Seventh
  vacuous test in this plan, all of them mine.
Ruling: fix by poisoning the starting value (b.fps = 999.0) before the tick,
  so only tick() can produce the expected result. Cheaper and clearer than
  restructuring __init__.
Task 9: fix round 1/5 (idle-rate test poisoned so it discriminates; both rate tests verified by break/restore; 371 suite green; commit 13442cb)
Task 9: review returned 1 Important, 2 Minor, plus a note that the brief's own
  Interfaces prose (Brain(config, brain_cfg, address)) contradicts the brief's
  code and tests (Brain(graph, cfg, client, spool_path)). The implementer
  correctly followed the code. My inconsistency, no code impact.
Ruling: the Important — `enabled = false` exiting without logging — is fixed in
  the SPEC, not the code. The spec said every degradation path logs once, and
  listed the disabled case among them. But disabled is the DEFAULT and the
  configured state, not a degradation; printing a line every time the
  workstation starts for a feature you deliberately turned off is noise. Spec
  amended to exempt it explicitly. Cost if wrong: someone wonders why nothing
  happened when they expected the brain — mitigated because `--selftest` still
  reports, and the README documents the toggle.
Task 9: minor (deferred): on SIGTERM/SIGINT the handler's sys.exit raises
  SystemExit out of run(), so main() never reaches its `return 0`. Verified
  behaviourally correct — the finally block runs, shutdown() clears the
  background, the pidfile is removed, exit code is 0 — but a non-script caller
  of main() would get SystemExit instead of a return value.
Task 9: minor (deferred): test_the_rate_falls_back_after_the_active_window uses
  active_window=0.0, where the active state is unreachable even in the
  triggering tick, so it verifies "never goes active" rather than "falls back
  after the window". Name overstates it; default active_window is 4.0.
Task 9: complete (commits 3011ef5..13442cb, 1 fix round, 371 suite green)
Task 10: implemented (commit 2706ee3, 371 suite green). Verified: sh -n clean, disabled selftest silent exit 0, enabled-without-kitty selftest prints guidance and exits 0 (real config md5 unchanged). Not verifiable: anything needing a live kitty session.
Task 10: review returned 1 Critical, 1 Important, 2 Minor.
Ruling: the Critical is MINE and the reviewer is right. Both the spec and the
  README claimed `allow_remote_control yes` is rejected with `listen_on`. The
  reviewer checked kitty's v0.48.2 source; I then tested both settings against
  the installed binary directly — each creates the socket and accepts remote
  control. My original claim came from misreading an "Invalid listen_on" error
  in an early spike where I changed two variables at once. Corrected in the
  spec and dispatched for the README. `socket-only` remains the recommendation
  for a better reason: it refuses remote control over the terminal's own escape
  channel, so a program in a pane cannot drive the terminal. Cost if wrong:
  none — the recommendation is unchanged, only its justification is now true.
Ruling: the Important (review range included my out-of-band spec commit
  16b4ea7) is a process artifact, not a defect. My spec corrections land
  between tasks, so a BASE..HEAD range picks them up. No action.
Task 10: minor (deferred): bin/griot uses ${XDG_CACHE_HOME:-...} while
  settings.py uses os.environ.get(...), which diverge if XDG_CACHE_HOME is set
  to an EMPTY string — shell falls back, Python does not. `griot restart` would
  then fail to kill the animator. Pathological, not worth a round.
Task 10: minor (deferred): the kitty row in the README requirements table says
  "(optional)" without stating the degradation, unlike the icalBuddy row which
  spells it out inline.
Task 10: fix round 1/5 (README remote-control claim corrected, table row consistency; 371 green; commit ba2b0a5)
Task 10: complete (commits 13442cb..ba2b0a5, 1 fix round)
ALL 10 TASKS COMPLETE. Dispatching final whole-branch review.
FINAL REVIEW: 2 Critical, 7 Important, 13 Minor. Both Criticals live in seams
  between tasks — exactly what the whole-branch pass is for.
Ruling: fix in ONE wave — C1, C2, I1-I7, and the cheap minors M1, M2, M10, M11,
  M12. Defer M3-M9 and M13 (naming/duplication/micro-optimisation) — they are
  real but none changes behaviour, and a second fix wave costs more than they
  are worth.
Ruling: triage accepted — of the 15 deferred items only Task 2's duplicate
  basenames blocks, and only because the reviewer costed the half I had not:
  42 of 1,013 notes (4% of the vault, including two live Meetings.md files)
  can never pulse, silently. That is the feature's core promise failing.
