# Garbage collection

Part of the canopy design, normative like all of it: what canopy removes of its own history and caches, and what it
keeps. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Plans](PLANNING.md). Next: [The overseer's tools](OVERSEER_TOOLS.md).

## 26. Garbage collection

All of it is built but one row: the pass removes no memory text yet, though `canopy gc --dry-run` counts it (§28).

### What grows

| What | Grows by | Removed |
| --- | --- | --- |
| `runs/<id>.log`, `.prompt`, and `<id>.<repo>.diff`, `.head` under `approve` (§29) | one set per worker run | after `run_files_days`; a plan run's prompt never |
| `ticks/<id>.log`, `.prompt` | one pair per tick | after `tick_files_days` (a tick not `ok`: `run_files_days`) |
| `chore-runs/<name>/<id>.log`, `.prompt` | one pair per chore run | after `run_files_days` |
| `reviews/<id>.log`, `.prompt`, `.diff` | one set per review run | after `run_files_days` |
| Any of those with no journal row | a review run that never started | after an hour |
| `canopy.log` | every log line of every canopy process | rotated past `log_max_mib` |
| `traces.jsonl` (§12, Traces) | every span, while traces are on | rotated as `canopy.log` is |
| Attention items the harness raised | each open item, every tick | outside the window (below) |
| Connector runs and derivations (§30) | each tick, and each of the loop's polls (§6) | outside the window (below) |
| Check runs a `vcs` source keeps (§7) | each completed check run of a PR | once off its PR's head (below) |
| Free pages and the WAL in the journal | deletes, and checkpoints held back by readers | checkpointed each pass; `canopy gc --vacuum` |
| Loose objects and packs in a primary clone | every worker's fetches and commits | by hand, `canopy gc --git` (below) |
| `$XDG_CACHE_HOME/canopy/sandbox/<role>/` | every sandboxed run's tool caches | by hand, `canopy gc --caches` |
| A run's lock, object directory, desk, and review checkout | one per run | when the run ends, or by reconcile |
| `runtime/<digest>/` | one per definitions change | by reconcile when no run is live (§13) |
| `plan-exports/<digest>.json`, what an export last found as it stands (§25) | a line per plan, per destination | never |
| Notification events | each event | after 7 days once every sink has passed them (§20) |
| Agent memory's notes and proposals no longer in force (§28) | each one replaced, dropped, or retired | text after `memory_days`, the row kept (not yet built); `canopy memory forget` and `purge` delete it |

### What it never removes

- A record a guard counts: runs, their slots, review runs, attempt and review grants, and dismissals. Limits count
  over all time, and a guard that history can reset is not a guard (D030, D086).
- Ticks, tickets, messages, units, forgets, starts, notices, ended review requests, chore runs, the web UI's record of
  its writes, and the overseer's own decisions, the audit log and prompt-evaluation corpus (§11, §19, §21, §22); plan
  files, the operator's to remove, and their runs' prompts, which the plan archive carries (§25).
- Anything a live run uses, or a run's lifelock holds; remote branches, which `canopy gc` lists and deletes none of,
  since deleting one is outward-facing and may lose work (§22); and what is not canopy's: a chore's working
  directory (§19), ignored files in a pool slot (§18), the runtime's own data.

### The pass

Reconcile runs the pass on a live tick, never a dry run, at most once a day, under the tick lock. A pass that fails
logs it and the tick goes on: a full disk is the pass's reason to run, and must not stop the loop that would free it.
`canopy gc` runs it by hand; `--dry-run` changes nothing and reports what a pass would remove, and `--vacuum`, `--git`,
and `--caches` add steps the loop never runs on its own. It refuses inside a tick or a run (TRUST_MODEL T1), and no
flag shortens retention; only the operator's config does. An agent that could remove history early could remove the
transcript that shows what it did.

Files go only by the paths the journal records, or as orphans an hour old, and only regular files inside the state
directory, never a symlink. A tick not `ok` keeps its files as long as a run, since the operator debugs those. Reconcile
alone rotates `canopy.log` and `traces.jsonl`, on every live tick: rotating in whichever process crosses the size
races the others, which follow each file to its new one. Rejected: gzip before deleting, which gives the transcript
reader two formats for history rarely opened after a month.

### The journal

A harness-raised attention item is deleted only once it is older than `journal_days` and its tick is outside the
window the attention list reads, so the list, its open-since, and notifications do not change. Rejected: recording
an item only when it opens and closes, which changes how §14 derives the list and every reader with it. Connector runs
and derivations (§30) go under the same rule, except each source's newest run and the newest that recorded the query's
result, which `canopy status`, `connector_failed`, and the derivation read. A kept check run goes after `journal_days`
once a read shows its PR at another head, merged, or closed, since `handled` reads only those at the head. `--vacuum`
refuses while any run is live, and when the disk has less free space than the journal, since `VACUUM` writes a whole
copy first.

### Git in the primary clones

`canopy gc --git` runs only git's `loose-objects` and `incremental-repack` maintenance, then `prune-packed`, none of
which deletes an object no pack holds or prunes a worktree, what made automatic maintenance unsafe for slots in use
(§18). It holds the dispatch lock for each repository in turn, skips one with a leased slot or with git's own
maintenance under way, and runs git as the harness always does (D107). `canopy gc --caches` empties a
role's sandbox cache (§24) while no run of that role is live.

### Configuration

`[retention]` is personal, in the user file (§12): the keys the table names, and `log_keep`, the rotated logs kept.
Each is a non-negative integer, and `0` keeps that kind forever. The defaults are a proposal until measured live.

### Open

- The defaults, from the measurement.
- Whether the overseer's own attention rows, also recorded every tick an item stays open, need a rule of their own.
  They are the evaluation corpus, so not until the measurement shows their share.
- Whether connector runs and derivations need a key of their own rather than `journal_days`.
- Whether the pass runs `--git` on its own, weekly, once the command has run live (SCENARIOS).
