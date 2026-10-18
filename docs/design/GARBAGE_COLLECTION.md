# Garbage collection

Part of the canopy design, normative like all of it: what canopy removes of its own history and caches, and what it
keeps. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Plans](PLANNING.md). Next: [The overseer's tools](OVERSEER_TOOLS.md).

## 26. Garbage collection (M47)

Stage 1 of ROADMAP M47 is built: `canopy gc --dry-run` and `[retention]`, which nothing else reads yet. The pass and
the flags that remove anything are not. Until they land, canopy removes only what the third column of the table below
says it removes today, and §6, §11, §12, §18, and §22 describe canopy as it is. This section says what changes.

Almost everything canopy writes is kept forever. Most of the bytes are files, not journal rows: every run, tick, chore
run, and review writes a log of the runtime's JSON events beside a prompt, each up to megabytes. The journal grows too,
mostly through attention items, which the harness records again on every tick each one stays open (§14), and nothing
checkpoints or vacuums it. And the primary clones collect loose objects, since canopy turns off git's automatic
maintenance (§18) and nothing runs maintenance in its place.

### What grows

| What | Grows by | Removed today | Removed by M47 |
| --- | --- | --- | --- |
| `runs/<id>.log`, `.prompt` | one pair per worker run | never | after `run_files_days` |
| `ticks/<id>.log`, `.prompt` | one pair per tick | never | after `tick_files_days` (a tick not `ok`: `run_files_days`) |
| `chore-runs/<name>/<id>.log`, `.prompt` | one pair per chore run | never | after `run_files_days` |
| `reviews/<id>.log`, `.prompt`, `.diff` | one set per review run | never | after `run_files_days` |
| Any of those with no journal row | a review run that never started | never | after an hour |
| `canopy.log` | every log line of every canopy process | never; no rotation | rotated past `log_max_mib` |
| Attention items the harness raised | each open item, every tick | never | outside the window (below) |
| Free pages and the WAL in the journal | deletes, and checkpoints held back by readers | never | checkpointed each pass; `canopy gc --vacuum` |
| Loose objects and packs in a primary clone | every worker's fetches and commits | never (`gc.auto=0`) | `canopy gc --git` (below) |
| `$XDG_CACHE_HOME/canopy/sandbox/<role>/` | every sandboxed run's tool caches | never | `canopy gc --caches` |
| A run's lock, object directory, desk, and review checkout | one per run | when the run ends, or by reconcile | unchanged |
| `runtime/<digest>/` | one per definitions change | by reconcile when no run is live (§13) | unchanged |
| Notification events | each event | after 7 days once every sink has passed them (§20) | unchanged |
| Agent memory's notes and proposals no longer in force (§28) | each one replaced, dropped, or retired | never; `canopy memory forget` and `purge` delete its text | text deleted after `memory_days`, the row kept |

### What it never removes

- **A record a guard counts:** runs, their slots, review runs, attempt and review grants, and dismissals. Attempt
  limits and the review limit count over all time, and a guard that history can reset is not a guard (D030, D086).
  They are small; the bytes are in their files.
- **A tick, ticket, message, or unit.** Ticks are what runs, decisions, chore runs, and review runs point to;
  tickets, messages, and units are the conversation (§22) and its cursors.
- **The overseer's own decisions.** They are the audit log and the prompt-evaluation corpus (§11). Only the attention
  items the harness raises are pruned.
- **Records the design keeps, or a reader needs whole:** starts, notices, and ended review requests (§11, §21); chore
  runs, whose `ok` runs date each finding's sequence (§19).
- **Anything a live run uses.** A file is removed only when its run has ended, and never while the run's lifelock is
  held.
- **Remote branches.** Deleting one is outward-facing and the branch may hold work. They stay the operator's (§22);
  `canopy gc` lists the ones no open run or unit names, and deletes none.
- **What is not canopy's:** a chore's working directory, `<state_dir>/chores/<name>/` (the agent's own, §19); ignored
  files in a pool slot (build outputs a reused slot keeps on purpose, §18); the runtime's own data, such as
  `~/.local/share/opencode`.

### The pass

Reconcile runs the pass on a live tick (never a dry run), at most once every 24 hours, under the tick lock it already
holds. The journal records each pass: when, the tick, and what it removed of each kind, with the bytes. A pass that
fails logs the error and the tick goes on, as a failed definitions prune does (§13): a full disk is the pass's reason
to run, and must not stop the loop that would free it.

`canopy gc` runs the same pass by hand, taking the tick lock as `canopy workspace sync` does (§18):

- `canopy gc --dry-run [--json]` changes nothing, and reports for each row of the table above that M47 changes how
  many there are, their bytes, and what a pass with the operator's retention would remove. It counts the overseer's
  own attention rows apart from the harness's, for the open question below, and reads each primary clone with `git
  count-objects`, which writes nothing. A row's bytes are its text's, not the pages it fills.
- `--vacuum`, `--git`, and `--caches` add the steps below that the loop never runs on its own.
- It refuses inside a tick or a run, as `forget` and `grant` do (TRUST_MODEL T1). No flag shortens retention; only
  the operator's own config does. An agent that could remove history early could remove the transcript that shows
  what it did.

### Run and tick files

A run's, chore run's, or review run's files go once it has ended more than `run_files_days` ago; a tick's once it has
ended more than `tick_files_days` ago, or `run_files_days` for a tick that did not close `ok`, since those are the
ones the operator debugs. A file under `runs/`, `ticks/`, `chore-runs/`, or `reviews/` with no journal record, and
over an hour old, goes too. The pass removes only the paths the journal records, and only a regular file inside the
state directory, never a symlink.

A page whose file is gone says so: the web UI shows "removed after N days" where the run ended before the cutoff, and
"missing" otherwise.

Rejected: gzip before deleting. The transcript reader would read two formats and its size cap would mean two things,
for history the operator rarely opens after a month.

### `canopy.log`

Every canopy process appends to it: ticks, `_run`, `_chore`, `_review`, and the web UI's server. Reconcile checks its
size on every live tick, not only in the daily pass, since the check is cheap; past `log_max_mib` it renames it to
`canopy.log.1`, shifting older ones up to `log_keep`. So the limit is soft by at most one tick's lines. Every process
notices the rename and reopens the path; a line written between the check and the rename lands in `canopy.log.1`, and
nothing is lost. Rejected: rotating in whichever process crosses the size, which races every other process doing the
same.

### The journal

The pass deletes a harness-raised attention item once its tick is outside the window the attention list reads (the
newest 1000 `ok` ticks) and it was recorded more than `journal_days` ago. A journal with fewer ticks than the window
loses none, whatever `journal_days` says. The attention list, each item's open-since, and notifications read only
that window, so none of them changes. An old tick's page still shows the overseer's decisions, but not the harness's
attention items, and search no longer finds those.

Rejected: recording an item only when it opens and when it closes. That would save the same rows, but it changes how
§14 derives the list, and every reader of decisions with it; the window rule saves them and changes nothing that is
read.

After the deletes the pass checkpoints the WAL. A long-lived reader, such as one of the web UI's event streams, can
hold the checkpoint back; then the pass logs it and moves on. SQLite reuses freed pages, but the file never shrinks:
`canopy gc --vacuum` runs `VACUUM`, refusing while any run is live, since runs write the journal. It also refuses
when the disk has less free space than the journal's size, since `VACUUM` writes a whole copy first: it reclaims space
at leisure, and cannot help a disk that is already full. The file deletes above are what help then. Rejected:
`auto_vacuum = INCREMENTAL`, since an existing journal needs a `VACUUM` to switch, and it would free little more than
reuse does.

### Git in the primary clones

`canopy gc --git` runs git's `loose-objects` and `incremental-repack` maintenance tasks in each primary clone. The
first packs loose objects and deletes only those already in a pack; the second merges packs and deletes only packs
whose objects are all in another. Neither prunes an unreachable object or a worktree, which is what made automatic
maintenance unsafe for slots in use (§18). For each repository it holds the dispatch lock, so no lease starts, skips
a repository whose pool has a leased slot, and runs git as the harness always does (D107), automatic maintenance off.

Rejected: the `gc` task, which prunes unreachable objects and runs `git worktree prune`. Whether the pass runs `--git`
on its own, weekly, is open until the command has run live (SCENARIOS).

### Caches outside the workspace

`canopy gc --caches` empties `$XDG_CACHE_HOME/canopy/sandbox/<role>/` (§24) while no run of that role is live. They
are caches, so a run after it starts cold. A pass only reports their size. The sandbox runtime under
`$XDG_DATA_HOME/canopy/sandbox-runtime/` is one copy, replaced on reinstall, and stays.

### Configuration

User file, personal:

```toml
[retention]
run_files_days = 30    # a run's, chore run's, or review's log, prompt, and diff, once it ended this long ago
tick_files_days = 7    # a tick's log and prompt; a tick not `ok` keeps them for run_files_days
journal_days = 90      # harness attention rows, past the window the attention list reads
log_max_mib = 50       # canopy.log is rotated past this
log_keep = 3           # and this many rotated files are kept
memory_days = 30       # the text of a note or proposal no longer in force (§28); a lesson is never pruned
```

Each is a non-negative integer, and `0` keeps that kind forever. The values are a proposal: M47's first stage
measures a live workspace, and its numbers set the defaults.

### Open

- The defaults, from the measurement.
- Whether the overseer's own attention rows, which it also records every tick an item stays open, need a rule of
  their own. They are the evaluation corpus, so not until the measurement shows their share.
- Whether the pass runs `--git` on its own once it has run live.
