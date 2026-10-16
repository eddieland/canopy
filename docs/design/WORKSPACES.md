# Trackers and workspaces

Part of the canopy design, normative like all of it: where tickets come from, and one queue over several repositories.
Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Operating
canopy](OPERATING.md). Next: [Chores, notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md).

- [17. Trackers](#17-trackers)
- [18. Workspaces and multi-repo tickets](#18-workspaces-and-multi-repo-tickets)

## 17. Trackers

canopy works with any issue tracker the agent runtime can reach through an MCP server. There is no adapter interface and
no tracker code in the harness. Tracker differences are handled in three places, in order of preference:

1. **The contract below.** Agents map it onto the tools a tracker's MCP server exposes without being told how. This is
   the default for any tracker.
2. **Config.** `tracker.provider`, `tracker.query`, the queue labels, `needs_human_label`, and
   `trust.authorized_repliers` in the tracker's own identity format. `tracker.ticket_url`, optional, is where a
   ticket's page is, with `{key}` for its key: the web UI links each ticket's page there (§22), the key URL-encoded.
   It is the only tracker address canopy knows, and nothing but a browser the operator clicks in follows it (D003).
   It is shared because the tracker's address is the team's, and a link runs nothing, spends nothing, and authorizes
   no one (TRUST_MODEL T7). Not a URL per ticket from the overseer, which would put agent-written text in an `href`,
   and not a link format per provider, which would be tracker code in the harness.
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`. A skill is optional; add one when the
   `decisions` table shows the loop misreading a tracker, not in advance. The overseer gets the shipped skill for
   `tracker.provider` in its prompt (§13), where it is cached across ticks; workers load it as a skill.

### Contract

What the loop needs from a tracker, as capabilities, each used by the role in parentheses.

| Capability | Used for |
|---|---|
| Find open tickets matching `tracker.query` (overseer) | candidate set |
| Read a ticket: title, body, labels, open or closed (both) | phase, task |
| List comments with a stable id, author account id, and timestamp (overseer) | cursors, authorized replies |
| Post a comment (worker) | reports and questions |
| Add and remove a label (worker) | `needs_human_label` |
| Read blocker relations (overseer, optional) | ordering, stacking |
| When a label was added (overseer, optional) | `human_replied` |

"Label" means the tracker's tagging primitive, whatever it is called. Without blocker relations, tickets are treated as
unblocked. Without label history, the worker's question comment is the reference point for `human_replied`. If a tracker
cannot do a required row, the overseer records `skip` with rationale `tracker_unsupported: <capability>`, and the
operator fixes the MCP setup or writes a skill.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed, so a sloppy or plain-language query can waste a tick but cannot authorize work. Replies are
authorized only by `trust.authorized_repliers`, compared against the author's stable account id (Jira `accountId`,
GitHub login), never a display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so `canopy dispatch`,
`decide`, `attention`, and `ticket set` reject, in code, any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## 18. Workspaces and multi-repo tickets

ROADMAP M6 to M8 and M17; rationale in D016, D033, D058, and D066. canopy runs only from a
workspace, even for one repository: a workspace of one repository is a map with one entry.

### Shape

A workspace is a directory canopy manages: a map of the repositories a queue's tickets touch, one primary clone of
each, the worktree pools, and canopy's state. The loop runs from the workspace root.

```text
~/work/acme/                 workspace root; canopy tick runs here
  canopy-workspace.toml      the map, and the shared config layer
  MAP.md                     prose: what each repository owns and how they depend on each other
  repos/api/                 primary clones, one per repository in the map
  repos/web/
  .treehouse/                every repository's treehouse pool
  desks/PROJ-12/             one per running joint run: a link to each worktree it leased
    api -> ../../.treehouse/<api pool>/3/api
    web -> ../../.treehouse/<web pool>/1/web
  .canopy/                   journal, locks, logs, attention.md; operator-only
```

canopy finds the workspace by walking up from the current directory to the nearest `canopy-workspace.toml`, so it
works from inside `repos/` too. With none, every command that reads the config or the journal refuses, and names a
`canopy.toml` left in the repository it was run from as not read (D016). `canopy init`, `canopy skill`,
`canopy completion`, `canopy secret`, and `canopy sandbox setup` need no workspace.

### The map

```toml
[workspace]
name = "acme"

[repos.api]
url = "https://github.com/acme/api.git"
summary = "Public REST API. Owns the order schema and the generated OpenAPI spec."

[repos.web]
url = "https://github.com/acme/web.git"
summary = "Customer web app. Consumes the api's generated client from a release."

# [tracker], [policy], [trust]: the shared keys of §12.
```

- A repository name matches `[a-z][a-z0-9-]*` (a directory name, a treehouse leaf, a `--repo` argument). Its clone is
  at `repos/<name>`, not configurable, so a map cannot point outside the workspace.
- `summary` is one line, at most 200 characters, rendered into the overseer's state block. `MAP.md` is prose the
  overseer and workers read: ownership, dependency direction, where contracts live, landing order. Both are data, like
  ticket text, and authorize nothing.
- A branch's page on the repository's host is where the web UI links a ticket's branch in each of its repositories,
  and a worktree's branch (§22), each `/`-separated part of the name URL-encoded. By default canopy reads it from
  `url`: a GitHub clone URL (`https://github.com/OWNER/REPO`, `git@github.com:OWNER/REPO`, or `ssh://`, with or
  without `.git`) gives `https://github.com/OWNER/REPO/tree/{branch}`, and any other URL gives no link (D115). A
  credential in the URL never reaches the link. `branch_url`, optional, overrides it: a template with `{branch}` for
  the name, such as GitLab's `https://gitlab.com/acme/api/-/tree/{branch}`, checked as `tracker.ticket_url` is
  (§17): a plain `https://` URL of at most 500 characters with `{branch}` exactly once and no other braces. An empty
  `branch_url` turns the links off. Nothing but a browser the operator clicks in follows one, and a branch that was
  never pushed links to the host's not-found page.
- Config layers: built-in defaults, the workspace file, the user file (§12). The workspace file's policy may only
  tighten. Nothing in the repositories is read as config: one tracker, one queue.
- A map committed to a shared repository is exposed as any file in it is (TRUST_MODEL T7). `url` is read only by the
  operator commands `canopy workspace sync`, which prints what it clones first, and `canopy workspace add`, which writes
  it, and for the web UI's branch links. Map URLs should be HTTPS (§12); `sync` warns about SSH ones and clones them
  anyway. A tick never clones or changes a remote; a mapped repository with no clone is attention `repo_missing` and
  cannot be dispatched to.
- `canopy init` writes, overwriting nothing: the workspace file (asking for the tracker provider), a
  `MAP.md`, a `.gitignore` covering `repos/`, `.treehouse/`, `desks/`, and `.canopy/` (an existing one gains only
  missing lines), and the user file if missing. It prints the branch protection rules with every mapped repository
  they must be configured in. `canopy init` inside a workspace does the same.
  `canopy init [NAME=]URL...` also does `canopy workspace add` with the URLs, before printing the rules.
- `canopy workspace add [NAME=]URL...` appends a `[repos.<name>]` table per URL, with an empty summary, then syncs. The
  name is the URL's last path segment without `.git`, reduced to a valid name (`Web_App` is `web-app`), unless given as
  `NAME=URL`. A URL already listed (compared as sync compares `origin`) is left alone. A name already given another URL,
  or a URL with no usable name, refuses the whole command; nothing is written. The map is appended to as text, keeping
  comments and layout, under the tick lock after rereading it, via a temporary file renamed over it. The result is
  parsed as a map before sync runs.
- `canopy workspace sync` prints each clone, then runs `git clone -- <url> repos/<name>` with credential prompts and
  git's `ext::` transport off. For an existing clone it reports an `origin` differing from the map's URL (ignoring a
  trailing `/` or `.git`) and changes no remote. It also sizes pools and removes unlisted clones (below). It exits 1 if
  a clone failed, if `repos/<name>` exists and is not a clone, or if anything declared could not be reached. It prints
  a URL's credential as `***`; `canopy init` names repositories without URLs.
- A workspace's state is always `<workspace>/.canopy/`, created readable only by the operator, so each workspace has
  its own journal and locks. A `.canopy/` that is a symlink,
  someone else's, or open to others stops every command with a config error until removed (D053). A definitions
  snapshot inside it is checked the same way before each run loads it (§13).

### Worktrees live in the workspace

Every treehouse command canopy runs has `TREEHOUSE_ROOT` set to the workspace root and runs in the repository's
primary clone, so pools live under `<workspace>/.treehouse/`. The variable outranks both treehouse config files, so a
repository's `treehouse.toml` cannot move them, and `get` passes `--worktree-path '{pool}/{slot}/{repo}'` to pin the
layout. These pools are separate from the operator's interactive ones under `~/.treehouse`, so an interactive
`treehouse` never recycles canopy's slots. Build caches must still be slot-independent (§9).

There is no key to put a workspace's pools anywhere else (D033). For a fast disk, put the workspace on it. git keeps
each worktree's index and HEAD, and every object it writes, in the primary clone's `.git`, so a pool on another disk
than its clone still does git's work on the clone's. treehouse names a pool after the repository and a hash of its
remote URL, so one pool root that every workspace shared (the user file serves them all) would put two workspaces'
clones of a repository in one pool, where each sync and each declared size would count the other's slots. Build
outputs need not follow the workspace: Bazel's live under `--output_user_root`, wherever the operator's `.bazelrc`
puts it (§9).

Reconcile runs `treehouse status --json` once per mapped repository with a clone and returns stale `canopy:` leases. A
repository with no clone has no pool; the tick records `repo_missing` (§14) and dispatch refuses it. A run's slot is
returned through the pool of the repository it records; if that clone is gone, treehouse runs at the workspace root
and finds the pool from the slot's path (two levels below it). The overseer runs at the root, not a repository, so the
state block carries each pool's leased slots instead of its own `treehouse status`. Lease holders stay `canopy:<KEY>`;
one ticket can hold a slot in several pools.

### Declared repositories and slots

The map declares the repositories; the user file declares each pool's slots (D066). `canopy workspace sync` converges
on both, and a tick never grows a pool past its declared size.

```toml
# ~/.config/canopy/config.toml
[capacity]
slots_per_repo = 2      # every repository's pool, in any workspace
[capacity.repo_slots]
api = 4                 # by repository name; wins over slots_per_repo
```

- Pool sizes are user-only (§12). `repo_slots` may name repositories this map does not list. With neither key (the
  default) a pool is unmanaged: treehouse's `max_trees` bounds it and sync leaves it alone.
- **Leases stay within the size.** Before `treehouse get`, dispatch (§8) and a review (§21) read the pool. If as many
  slots as its declared size are busy, the lease is refused as `no_slot` without asking treehouse; a size of 0 refuses
  every lease. If treehouse makes a slot anyway (the available ones are not reusable, such as one recorded for another
  clone), canopy returns it, destroys it, and refuses. A pool under its size grows normally.
- **Sync fills each pool**: it leases with holder `canopy-sync` and `--no-fetch` until the pool has enough slots, then
  returns those leases. Holding each lease forces treehouse to make the next slot new, and `post_create` runs then,
  not in a run's lease. Reconcile never touches `canopy-sync` (not a `canopy:` holder); each sync returns leftover
  `canopy-sync` leases before counting. If treehouse refuses to grow the pool, usually because its `max_trees` is below
  the declared size, sync reports the repository failed; canopy cannot set `max_trees`, which treehouse reads only from
  its own config files.
- **Sync trims each pool**: it removes available slots, highest name first, with `treehouse destroy --yes` and no
  `--include-*` flags, so treehouse removes only a clean, merged, idle, unleased slot; one it keeps is passed over.
  Busy slots over the size wait for a later sync. A pool kept over its size by a slot with work in it makes sync exit
  1.
- **Sync removes clones the map no longer lists.** Anything under `repos/` the map does not name, except dot entries,
  is removed with its pool's slots only when nothing would be lost: a directory with a `.git`, not a symlink; empty
  `git status --porcelain --ignored` (ignored files count: a primary clone holds the local config `.worktreeinclude`
  seeds into slots) and `git stash list`; every commit reachable from `HEAD`, a branch, or a tag on a remote-tracking
  ref; and every slot in its pool available and destroyed by treehouse unforced. Anything else is kept and reported,
  and sync exits 1. treehouse's record of the emptied pool stays under `.treehouse/`.
- **Sync turns off git's automatic maintenance** in each primary clone's own config (`maintenance.auto=false`,
  `gc.auto=0`), which every slot of its pool shares, so neither the worker's git nor treehouse's starts it. A fetch or
  commit otherwise starts it in the background on that shared git directory, where it packs refs and prunes while
  other slots' runs use them; on CI it pruned a worktree `git worktree add` had made but not yet locked. The harness's
  own git has it off through `core/hostgit.py` (§8), which covers a clone no sync has reached yet. A dry run sets
  nothing. Nothing runs maintenance in its place yet; the operator can run `git maintenance run` in a clone while none
  of its pool's slots is leased.
- Sync holds the tick lock, waiting for a running tick to end. Runs in progress keep their leases, counted as busy.
- `canopy workspace sync --dry-run` reports what it would clone, make, and remove, changing nothing. It runs the
  read-only checks, so a clone it would keep a real sync keeps; what it would remove, treehouse may still keep. An
  uncloned repository is previewed with every slot to make.
- A lease sync cannot return, its own or a dead sync's, makes the pool `failed` and sync exit 1.

### What a pool guarantees

What canopy takes from a pool, whichever implements it, is a list of guarantees, each stated by one case in
`tests/canopy/test_pool_contract.py` (ROADMAP M45). The suite runs every case through `pools.Pool`, the interface every
caller uses, against canopy's own pool and the fake on every `make check`, and against real treehouse when it is on
PATH: `make pool-contract`, which CI runs on Linux and macOS with treehouse built at the pinned commit. A behavior with
no case is not a guarantee, and a caller may rely only on what is listed here. The fake models treehouse's CLI and
lease bookkeeping, not git, so the cases about what is in a slot run only against a pool of real worktrees.

Leasing:

- A new pool has no slots (`test_a_new_pool_has_no_slots`).
- A lease names its slot, its id, its holder `canopy:<KEY>`, when it was taken (ISO 8601 with an offset), and its base
  branch by its bare name, `main` by default; `status` shows the slot `leased` under the same id, holder, and time
  (`test_a_lease_names_its_slot_holder_time_and_base`).
- Slots are numbered from 1 under the workspace: treehouse's `<root>/.treehouse/<pool>/<N>/<repo>`, canopy's
  `<root>/pools/<repo>/<N>/<repo>` (`test_slots_live_under_the_workspace_in_the_pool_s_layout`).
- Leases held at once are different slots (`test_leases_held_at_once_are_different_slots`).
- A lease on a base starts at that branch's tip (`test_a_lease_on_a_base_starts_there`).
- A lease fetches `origin` first; sync's `--no-fetch` lease cuts the slot from the refs already there
  (`test_a_lease_fetches_first_unless_told_not_to`).
- A slot is a linked worktree of the primary clone, detached at its base, whose `.git` file and `commondir` `_run`
  checks (`test_a_slot_is_a_detached_worktree_of_the_primary_clone`).
- A sync lease names no ticket (`test_a_sync_lease_names_no_ticket`).

Returning:

- A return frees the slot: `available`, with no lease id, holder, or time (`test_a_return_frees_the_slot`).
- A return needs the lease's id and holder both, and fails otherwise, leaving the lease
  (`test_a_return_needs_the_lease_id_and_holder`); so a lease returns once, and never touches the slot's next holder
  (`test_a_lease_returns_once`).
- Returning a path no pool manages fails (`test_returning_a_path_no_pool_manages_fails`).
- A return finds the slot's pool from the slot's own path, so it works from the workspace root when the clone is gone
  (`test_a_return_finds_the_pool_from_the_slot_when_the_clone_is_gone`).
- A return is forced: it never answers `dirty`, and it discards uncommitted changes, untracked files, and commits no
  branch holds, leaving HEAD at the base (`test_a_return_is_forced_and_discards_what_the_run_left`).
- A return ends the processes in the slot first (`test_a_return_ends_the_processes_in_the_slot`).

Reuse:

- A returned slot is reused before a new one is made (`test_a_returned_slot_is_reused`).
- Reuse resets the slot to the base's tip and keeps its ignored files, such as build outputs and caches, and nothing
  else (`test_reuse_keeps_ignored_files_and_nothing_else`).
- A return parks the slot on its lease's base, and a slot parked on a stacked run's base is still reused
  (`test_a_return_parks_the_slot_on_its_base_and_it_is_reused`).
- An idle slot with changes is `dirty`, and one with a process in it `in-use`; neither is reused
  (`test_an_idle_slot_with_changes_is_dirty_and_not_reused`,
  `test_an_idle_slot_with_a_process_in_it_is_in_use_and_not_reused`).
- An idle slot whose HEAD is not merged into the base is not reused, though clean and so `available`
  (`test_an_idle_slot_with_unmerged_commits_is_not_reused`): `available` does not promise reusable.

Seeding (§9):

- Every lease, a reused slot's too, copies from the primary clone the untracked, ignored files the include file
  selects, and nothing else (`test_a_lease_seeds_the_ignored_files_the_include_file_selects`,
  `test_seeding_repeats_on_every_lease`); never a tracked file (`test_seeding_never_copies_a_tracked_file`).
- A return removes what seeding wrote, so the next lease seeds afresh (`test_a_return_removes_what_seeding_wrote`).
- A seed target already in the slot fails the lease, and the slot is held under a holder no ticket can name until the
  operator returns it (`test_a_seed_target_already_in_the_slot_fails_the_lease_and_holds_the_slot`).
- A seeded symlink is written as a regular file holding the link's target
  (`test_a_seeded_link_is_written_as_a_file_holding_its_target`); whether it should be a link is open (ROADMAP M45).
- A missing include file fails the lease before any slot is touched
  (`test_a_missing_include_file_fails_the_lease_before_any_slot`).

Removing (sync's trim, above):

- `destroy` removes an idle, clean, merged slot and its directory (`test_destroy_removes_an_idle_merged_slot`), and
  keeps, saying why, a slot that is leased, dirty, in use, or holds commits not merged into the default branch
  (`test_destroy_keeps_a_leased_slot`, `test_destroy_keeps_a_dirty_slot`,
  `test_destroy_keeps_a_slot_with_a_process_in_it`, `test_destroy_keeps_a_slot_with_unmerged_commits`), or that no
  pool manages
  (`test_destroy_of_a_path_no_pool_manages_says_why`).

Size (above):

- A pool with no declared size stops at its bound: treehouse's `max_trees`, or 16 for canopy's
  (`test_an_unmanaged_pool_stops_at_its_bound`).
- A declared pool with every slot busy, a dirty idle one counting as busy, refuses a lease without growing
  (`test_a_declared_pool_with_every_slot_busy_refuses_without_growing`,
  `test_a_declared_pool_counts_a_dirty_idle_slot_as_busy`), and keeps its size when its idle slot cannot be reused
  (`test_a_declared_pool_keeps_its_size_when_its_idle_slot_cannot_be_reused`).

Not guaranteed, though treehouse does it: `status` rewrites treehouse's state, forgets a slot whose directory is gone,
and records a worktree it finds in the pool directory as held; `destroy` runs `git fetch` and `git ls-remote` on
`origin` first; `post_create` hooks run after seeding. treehouse runs git with none of D107's flags.

### canopy's pool

canopy's own pool (`core/pool.py`, ROADMAP M45) keeps every guarantee above, and is held to them by the same cases.
Until stage 3 of M45 it is built beside treehouse and wired to no caller but reconcile's shadow (below).

- **Layout.** A repository's slots are `<workspace>/pools/<repo>/<N>/<repo>`, numbered from 1, each a detached linked
  worktree of the primary clone. There is no hash of the remote in the path: a workspace's repository names are
  unique, and the pools are the workspace's own (D033).
- **Leases are journal rows.** The `slots` table holds each slot: repository, name, path, lease id and holder, when it
  was leased, the base it was last leased on by name, and the paths seeding wrote. A lease claims its slot's row before
  it touches the worktree, all under the pool's lock, `<workspace>/pools/<repo>/.lock`, so two leases never pick one
  slot. The row is written in its own transaction, not the run's: the slot is claimed before the run that needs it can
  be recorded, as treehouse's lease is. A lease whose process dies before its run is recorded is a `canopy:` lease no
  running run holds, which reconcile returns, as it returns treehouse's.
- **Size.** The declared size is the only bound; a pool with none declared stops at 16, treehouse's default
  `max_trees`. canopy's pool reads no config of treehouse's.
- **Lease, reuse, return, and seeding** are treehouse's (above, and ROADMAP M45's notes from its source): a reused
  slot is reset with `read-tree --reset -u`, HEAD moved to the base's tip, and `clean -fd`, after the files seeding
  wrote are removed; seeding copies the untracked, ignored files the manifest selects, never through a link in the
  slot; a collision quarantines a reused slot under the holder `quarantined: worktree seeding failed`. Reuse takes an
  idle slot only when it is clean, has no process in it, and its HEAD is an ancestor of the base or of the base it was
  last leased on; treehouse also takes one whose HEAD has the same content as a squash merge into the base, and canopy's
  pool passes that one over and makes a slot instead.
- **Processes in a slot** are read from `/proc` on Linux and with `lsof` through `procs` on macOS (`infra/cwds.py`), so
  there is no dependency for them. A return ends them, SIGTERM and then SIGKILL after two seconds; one that outlives
  both fails the return and keeps the lease. A slot whose processes cannot be read is `unverified`, never reused, and
  kept by `destroy`.
- **The host stays safe.** Every git the pool runs goes through `hostgit.argv` (D107). Before any git in a slot, the
  slot's `.git` file must name a directory under the clone's `.git/worktrees/`, and its `commondir` the clone's `.git`
  (D118); a slot that fails is `damaged`, never reset, reused, or removed. A return frees such a slot without a reset.
- **No network but a lease's fetch.** `destroy` judges merged against the default branch as last fetched, never with
  `ls-remote`: sync runs it after leases that fetched, and a stale ref keeps a slot rather than losing one.
- **Recovery.** A worktree in the pool's directory with no row, as a lease that died after `git worktree add` leaves
  one, is adopted as an idle slot when it is a sound worktree of the clone. An idle row whose directory is gone is
  forgotten at the next lease. `status` changes nothing.

**The shadow.** While treehouse makes the pools, every tick's reconcile also classifies each idle treehouse slot with
canopy's pool's checks (`pool.classify`) and logs a `pool_shadow_mismatch` line, with the repository, the slot, and
both answers, wherever they disagree. It changes nothing, and a check that fails is logged, never raised. Each mismatch
the operator explains becomes a contract case, and canopy's checks are fixed until it passes (ROADMAP M45, stage 2).

### Units

A ticket's work is divided into units, one per repository it changes, each with its own PR, phase, review and CI
cursors, and attempt counts. Per ticket stay the comment cursor, the ticket's own phase (`ready`, `blocked`,
`needs_human`, and the others not about a PR), and the branch, which every unit shares (D058). A single-repository
ticket has one unit.

A ticket's units are the repositories it has been dispatched to. Each dispatch names its units with `--repo`
(repeatable, at least one), chosen by the overseer from the ticket, the summaries, and `MAP.md`. An
`implement` over several repositories is a joint change: one worker, one PR per repository, each linking the others,
for changes that cannot build or pass tests separately. `fix-ci` and `resume` normally name only the unit needing
work.

A later `implement` naming a repository the ticket has no unit in adds one, also after another unit's PR merged: a
sequenced change, authorized by the ticket's label (D058). A repository has at most one unit per ticket; a follow-up PR
after its unit merged is a new ticket a human files (TRUST_MODEL T1). The overseer marks the ticket done when every
unit's PR has merged and no other repository is left to change.

A multi-repository ticket stays one ticket, worked jointly or in sequence as the overseer judges, and is split
(below) only when an authorized replier asks in a comment on it. One that is several independent pieces with no such
request gets `multi_repo` attention: a human asks for a split, splits it by hand, or narrows it.

Guards (§8) change as follows:

- `running` stays per ticket: one worker per ticket, whatever its units (TRUST_MODEL §6).
- `unknown_repo`: in a workspace, no `--repo`, or one not in the map or with no primary clone; for a split child, any
  repository but the one recorded, or more than one.
- `bad_slug`: a later `implement` whose `--slug` names another branch than the ticket's.
- `no_branch`: `fix-ci` and `resume` for a unit with no branch.
- `attempt_limit` counts per unit: a run counts against every unit it covers.
- `cooldown`: from the end of the latest fix-ci run covering the unit.
- `capacity` counts runs, not slots: a joint run over three repositories is one worker holding three slots.
- `no_slot`: leases are all or nothing; if any `treehouse get` fails, slots already leased are returned before the
  refusal is recorded.

Harness attention items for runs (§14) stay per ticket, their detail naming the repositories that failed. An
`attempt_limit` refusal's item and the overseer's items about a PR name their unit.

### Runs over several repositories

- The branch is `<trust.branch_prefix><KEY>-<slug>` in every repository. The ticket's first `implement` fixes the slug;
  later implements reuse it and refuse a `--slug` naming another.
- `_run` does branch setup (§8 step 2) and push verification (step 5) in each worktree. A one-repository run's worker
  runs in the worktree; a joint run's runs in its desk, `desks/<KEY>/`, made just before it starts, with a relative
  link per worktree named for its repository. The trap removes the desk and returns every slot; reconcile does both
  for a run whose `_run` died. A desk is made only in a `desks/` that is not a symlink, and removal never follows its
  links. canopy marks its desks with a `.canopy-desk` file and removes only marked ones; anything else under `desks/`
  is the operator's, and something unmarked where a desk goes refuses the run. A run is `unpushed` if any repository's
  branch is.
- Before a joint run's worker starts, the shadowing check (§13) covers each worktree, `desks/`, and the workspace root,
  since OpenCode may read config above the desk.
- The worker prompt lists each repository: name, path (in the desk for a joint run), branch, base, the unit's PR if
  any, and summary.
- The result contract's `"pr"` becomes `"prs"`, an object from repository name to PR URL or null; each URL is recorded
  as its unit's `pr_url`.
- Worker obligations add: each PR's body links its sibling PRs and says which to merge first; the ticket comment lists
  every PR. Workers still never merge.

### Splitting

canopy splits a ticket in the tracker only when asked, in an authorized replier's comment rather than by a label anyone
who can label could add, and never schedules what it split: children start without a queue label, so a human
authorizes each (TRUST_MODEL T1).

- The overseer dispatches a split only when an authorized replier's comment on the ticket, newer than its comment
  cursor, asks for a split into separate tickets; never on its own judgment.
  `canopy dispatch <KEY> --label <label> --kind split --request <comment id> --repo api --repo web` names that
  comment. A split without `--request` is `unauthorized`; `--request` on another kind is `bad_request`. The harness
  cannot read the comment (D003), so `--request` is a recorded claim, like `--label`; the splitter reads it and creates
  nothing unless an authorized replier wrote it and it asks for a split. A split prompt override without `{{REQUEST}}`
  or `{{REPOSITORIES}}` is `bad_prompt`.
- `bad_split` refuses a split over fewer than two repositories, of a ticket that has a branch
  (split it by hand), or of a split's child. `--slug` is `bad_slug` and `--base` `bad_base`: a split has no branch.
  `policy.max_split_attempts`, default 1, limits `split` attempts per ticket, never per unit.
- The split worker runs with `runtime.split_cmd` as `canopy-splitter`: an agent definition with no edit, shell, web
  fetch, or subagent tools, and MCP tools whose names suggest labels, assignees, edits to existing tickets, PRs,
  branches, or files denied by pattern. Where the runtime can restrict a create tool's arguments, a definition could
  also forbid labels on create; the check below holds regardless.
- It runs like a joint run, in a desk of the named repositories' worktrees, with the worker's timeout. Its prompt
  carries the first 20,000 characters of `MAP.md`, since it may not read outside its desk. `_run` checks each worktree
  out at its base branch, detached, makes no branch, pushes and verifies nothing, and records no branch or unit
  (`runs.branch` is empty). Slots are returned and the desk removed on every exit path; reconcile treats a dead split
  run like any other.
- It creates one child per repository with a share of the work, if each share can be built and reviewed alone;
  otherwise it creates nothing and reports `failed` saying why. Each child's body names its repository
  (`canopy-repo: web`) for people, links the parent, and says what it covers. Children that must land in order get
  the tracker's blocker relation (`web` blocked by `api`), so M4's ordering applies. Children carry no queue label and
  no assignee.
- It comments on the parent listing the children and which label starts each. Its result line is
  `{"status":"done|failed","summary":"...","children":{"PROJ-13":"api","PROJ-14":"web"}}`, listing every child it
  created even when `failed`. `_run` validates: each key a valid ticket key (§17) of at most 100 characters, new to the
  journal (never a split's child, never dispatched, never in `tickets`) and not the parent; each repository one the
  split was dispatched with, at most once; a `done` split names at least one child. `blocked` is not a split status.
  Anything else makes the run `unknown` and records nothing; its stored result keeps the note but none of the children.
  A valid result goes into `split_children`, also when the run timed out after printing it, and is the source of a
  child's repository afterwards.
- The parent's phase becomes `split`: wait, with attention `split_unlabeled` naming each child still open and
  unlabeled. Any dispatch for it is `bad_split`. The overseer marks the parent `done` in the journal once every child
  is closed; canopy does not touch its tracker state.
- A child is a candidate only if its queue label was added after the split run ended. The state block carries
  `split_children` (parent, repository, split run, `split_ended_at`) until parent and child are both done, and the
  overseer compares it with the tracker's label history. A label the split worker added, at creation or later, does
  not count: the overseer records `split_self_labeled` for that child, which stays out of the queue until a human
  removes the label and adds it again. On a tracker without label history (the optional row of §17's contract) the
  overseer does not split; it records `multi_repo` saying why.
- This check is the overseer's, not a harness guard, since the harness never reads the tracker (D003): the same kind
  of control as the queue-label check (§17), with the same residual (TRUST_MODEL T1).
- A child is an ordinary one-repository ticket. `canopy dispatch` for a key in `split_children` refuses any `--repo`
  but the recorded one (`unknown_repo`), so editing its `canopy-repo` line changes nothing, and refuses another split
  (`bad_split`). A ticket split by hand has no such row; the overseer chooses its repository as for any ticket.

### Journal

- `ticket_units`: ticket key, repository, branch, PR URL, phase, `last_review_id`, `last_ci_run_id`. `tickets.phase`
  is the ticket's own; the state block shows it and each unit's.
- `run_slots`: run id, repository, slot path, lease id, lease holder, base branch. `runs` has no slot columns.
- `split_children`: child key, parent key, repository, split run id; written only by `_run` from a validated split
  result.
- `tickets.repo` holds the workspace root.
- Attention items carry an optional repository and are identified by ticket, repository, and reason, so two units at
  their fix-ci limit are two items. `canopy attention` takes `--repo`.

### Trust model changes

TRUST_MODEL items this section relies on, each approved with the milestone that needed it:

- T1 (M8): the loop may create tickets, never on its own decision and never with a queue label; the check is in the
  overseer prompt, backed by the splitter's read of the request and its permissions.
- T4 (M7): a worker's edit permission covers the worktrees linked from its desk. The desk canary
  (`tests/canopy/test_opencode_canary.py`), like D021's, shows OpenCode allows edits through the links and denies
  paths beside them.
- T6 (M7, M8): the write scope is the repositories of the run's units; the splitter's is creating and linking tickets
  and commenting on the parent.
- T7 (M6): a shared workspace file is a file anyone who can push may change; clone URLs are read only by an operator
  command; state directory and definitions snapshots are private to the operator (D053).
- §7 (M6): branch protection is needed in every mapped repository; `canopy init` prints the rules for each.

### Open

- Whether an authorized replier's approval of the split on the parent, rather than a label on each child, should make
  an unlabeled child a candidate. The request that started the split is not that approval.
- Whether a child's desk should also hold its blockers' unmerged branches, read-only by prompt, to build against.
- Whether a started ticket should ever be split. `bad_split` refuses it now; a human splits one by hand.
- Whether a follow-up PR after a unit merged, for late review feedback, should be possible inside the ticket, on an
  authorized replier's comment. D058 leaves it to a new ticket; revisit if filing those proves friction.
