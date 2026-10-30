# M47. Garbage collection

DESIGN §26, D030, D086, D107. `canopy gc --dry-run [--json]` measures what canopy keeps under `[retention]`; a live
tick rotates `canopy.log` and runs a daily pass, recorded in `gc_passes`, that removes run, tick, chore, and review
files past their retention, the harness's attention rows, connector runs, and derivations outside the window, and
checkpoints the journal. By hand, `--vacuum`, `--git` in the primary clones, and `--caches`; the dry run lists remote
branches no open run names, and deletes none. No row a guard counts, nothing a live run uses, and no remote branch is
removed, and no flag shortens retention.

Status: done 2026-10-30.
Learned: closed on real use, stages 2 to 4 built against the fakes at the operator's word before the stage before had
passed its check, and none of S59, S60, S62, or S65 run; they are in SCENARIOS. So §26's defaults stay as proposed,
unmeasured. git's maintenance refuses both tasks at once in a clone with no pack, and skips one whose lock another
holds without saying so, so `--git` runs each task alone and looks for the lock itself.
Next: the dry run counts memory's text past `memory_days`, but the pass removes none of it yet (§26, M50). Whether
the pass runs `--git` on its own, weekly, waits on S65 (§26, Open).
