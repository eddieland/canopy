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
   `trust.authorized_repliers` in the tracker's own identity format. `tracker.ticket_url`, optional, with `{key}` for a
   ticket's key, is where the web UI links each ticket (§22). It is the only tracker address canopy knows, and nothing
   but a browser the operator clicks in follows it (D003). It is shared config, since a link runs nothing, spends
   nothing, and authorizes no one (TRUST_MODEL T7). Rejected: a URL per ticket from the overseer (agent-written text in
   an `href`); a link format per provider (tracker code in the harness).
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action.
   Skills ship for `jira` and `github`. Add one when the decisions show the loop misreading a tracker, not in advance.
   The overseer gets the skill for `tracker.provider` in its prompt (§13); workers load it as a skill.

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
cannot do a required row, the overseer records `skip` with rationale `tracker_unsupported: <capability>`.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed, so a sloppy query can waste a tick but cannot authorize work. Replies are authorized only by
`trust.authorized_repliers`, compared against the author's stable account id (Jira `accountId`, GitHub login), never a
display name.

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so every command that takes
one rejects, in code, any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## 18. Workspaces and multi-repo tickets

canopy runs only from a workspace, even for one repository: a workspace of one repository is a map with one entry.

### Shape

A workspace is a directory canopy manages: a map of the repositories a queue's tickets touch, one primary clone of
each, the worktree pools, and canopy's state. The loop runs from the workspace root.

```text
~/work/acme/                 workspace root; canopy tick runs here
  canopy-workspace.toml      the map, and the shared config layer
  MAP.md                     prose: what each repository owns and how they depend on each other
  repos/api/                 primary clones, one per repository in the map
  .treehouse/, pools/        the worktree pools, treehouse's or canopy's own
  desks/PROJ-12/             one per running joint run: a link to each worktree it leased
  .canopy/                   journal, locks, logs, attention.md; operator-only
```

canopy finds the workspace by walking up to the nearest `canopy-workspace.toml`. With none, every command that reads the
config or the journal refuses, and names a `canopy.toml` left in the repository as not read (D016).

### The map

The map names each repository with a `url` and a one-line `summary`, and holds the shared config keys of §12.

- A repository name matches `[a-z][a-z0-9-]*`, and its clone is always `repos/<name>`, so a map cannot point outside the
  workspace.
- `summary`, rendered into the state block, and `MAP.md` (ownership, dependency direction, landing order) are data, like
  ticket text, and authorize nothing.
- Config layers: built-in defaults, the workspace file, the user file, the workspace's private file (§12). The workspace
  file's policy may only tighten. Nothing in the repositories is read as config: one tracker, one queue.
- A map committed to a shared repository is exposed as any file in it is (TRUST_MODEL T7). `url` is read only by the
  operator's `canopy workspace sync` and `add`, and for the web UI's branch links (§22), which come from a GitHub `url`
  or a `branch_url` template checked as `tracker.ticket_url` is (§17), and never carry a credential (D115).
- A tick never clones or changes a remote; a mapped repository with no clone is attention `repo_missing` and cannot be
  dispatched to. `canopy workspace sync` clones it, with credential prompts and git's `ext::` transport off, never
  printing a URL's credential, and reports, never changes, an `origin` that differs from the map.
- `canopy init` makes the skeleton, overwriting nothing, and prints the branch protection rules every mapped repository
  needs (TRUST_MODEL §7).
- A workspace's state is always `<workspace>/.canopy/`, readable only by the operator. A `.canopy/` that is a symlink,
  someone else's, or open to others stops every command until removed (D053); so does a definitions snapshot inside it
  that fails the same check (§13).

### Worktrees live in the workspace

canopy's pools live under the workspace, whatever a repository's `treehouse.toml` says, apart from the operator's
interactive pools, so an interactive `treehouse` never recycles canopy's slots. There is no key to put them elsewhere
(D033); for a fast disk, put the workspace on it. Rejected: a pool root shared by workspaces, where two workspaces'
clones of a repository would share a pool and count each other's slots. Build caches must be slot-independent (§9).

Each tick's reconcile returns stale `canopy:` leases in every mapped repository's pool. A run's slot goes back through
the pool of the repository it records, even after that clone is gone. Lease holders are `canopy:<KEY>`; one ticket can
hold a slot in several pools. The state block carries each pool's leased slots.

### Declared repositories and slots

The map declares the repositories; the operator's private or user config declares each pool's slots (D066),
`capacity.slots_per_repo` and `capacity.repo_slots` (§12). With neither, treehouse's `max_trees` bounds the pool and
sync leaves it alone. `canopy workspace sync` converges on both, holding the tick lock.

- **Leases stay within the size.** Dispatch (§8) and a review (§21) refuse a lease as `no_slot` when the declared
  number of slots is busy; a size of 0 refuses every lease. A tick never grows a pool past its size.
- **Sync fills each pool** to its size, so slots are made, and setup hooks run, during sync rather than in a run's
  lease. Reconcile never touches sync's own leases.
- **Sync trims** idle slots over the size only through an unforced `destroy`, which keeps any slot with work in it.
- **Sync removes a clone the map no longer lists** only when nothing would be lost: no changes, ignored files, or
  stash, every commit on a remote-tracking ref, and every slot of its pool removable. Anything else is kept.
- **Sync turns off git's automatic maintenance** in each primary clone, since it prunes the git directory every slot
  shares under other slots' runs; the harness's own git runs with it off too (§8).
- A dry run changes nothing. Sync exits 1 on anything declared it could not reach and anything it had to keep.

### What a pool guarantees

What canopy takes from a pool, whichever implements it, is this list, and a caller may rely on nothing else. Each
guarantee is held by a case of the pool contract suite, run against canopy's pool, the fake, and real treehouse; a
behavior with no case is not a guarantee.

- **Leasing.** A lease names its slot, id, holder `canopy:<KEY>`, time, and base branch. Leases held at once are
  different slots. A run's lease fetches `origin` first and starts at the base's tip, in a linked worktree of the
  primary clone, detached, that passes the run's check (§8).
- **Returning.** A return needs the lease's id and holder both, so it never touches the slot's next holder, and works
  after the clone is gone. It is forced: it ends the slot's processes and discards changes, untracked files, and
  commits no branch holds.
- **Reuse.** A returned slot is reused before a new one is made, reset to the base's tip, keeping its ignored files
  (build outputs, caches) and nothing else. A slot that is dirty, in use, or not merged into the base is never reused.
- **Seeding (§9).** Every lease copies from the primary clone the ignored files the include file selects, never a
  tracked file, and a return removes them. A seed target already in the slot fails the lease and quarantines the slot.
- **Removing.** `destroy` removes only an idle, clean, merged slot that a pool manages.
- **Size.** A declared pool with every slot busy, a dirty idle one counting as busy, refuses a lease without growing.

### canopy's pool

canopy's own pool keeps every guarantee above. `pools.backend` (§12), private, chooses which pool makes a workspace's
worktrees, `"treehouse"` by default or `"canopy"`; callers do not know which they have.

- **A lease goes back where it came from.** The journal records which pool made each lease and returns the slot
  through it, so switching with runs in flight is safe. Switching is sync's: it moves idle slots, with their caches,
  into the new pool, a busy one at a later sync, and keeps any slot with something to lose.
- **Leases are journal rows**, taken under a lock per pool, so two leases never pick one slot. It runs no
  `post_create` hook (that work moves to `runtime.setup_cmd`, §9), reads no treehouse config, and stops at 16 slots
  with no declared size.
- **A quarantined slot waits for the operator,** in either pool, since the file seeding collided with may be a run's
  work. Nothing frees it on its own; it counts as busy until `canopy workspace release REPO SLOT`, which frees only a
  quarantined slot.
- **The host stays safe.** Every git the pool runs has D107's flags. Before any git in a slot, its `.git` file and
  `commondir` must point into the primary clone (D118); a slot that fails is `damaged`, never reset, reused, or
  removed. A slot whose processes cannot be read is never reused or removed, and one whose process survives SIGKILL
  keeps its lease.
- **No network but a lease's fetch.** Merged is judged against the default branch as last fetched, so a stale ref keeps
  a slot rather than losing one.

**The shadow.** While treehouse makes the pools, reconcile also classifies its idle slots with canopy's pool's checks
and logs `pool_shadow_mismatch` wherever they disagree, changing nothing. Each mismatch the operator explains becomes a
contract case.

### Upgrading past treehouse

Designed, not built (ROADMAP M45, stage 4). Proposed (2026-10-19, #813), for the operator to accept by merging. The
release that removes treehouse finishes, with git alone, a move the workspace has not made yet, rather than refuse to
run until the operator makes it on the release before: that would mean a downgrade, and config is not
downgrade-compatible. Nothing here may stop a tick. Three things can be left over: a lease the journal says treehouse
made (`'treehouse'` in a run's or review's lease, as every lease from before the journal named the pool is), a
worktree of a clone still under `.treehouse/`, and a config still setting `pools.backend`.

- **A treehouse lease goes back through canopy.** `'treehouse'` stays a value the journal holds, and names a lease of
  a worktree under `.treehouse/`. When its run or review ends, or reconcile closes it as crashed, canopy returns the
  worktree itself, with no treehouse call: forced, its processes ended, reset to its lease's base as the journal
  records it (the default branch where none is), ignored files kept, as a return to canopy's pool is. The slot must be
  under `.treehouse/` and pass D118's check, or it is left as it is, never reset. There is no treehouse record to hold
  the lease against, so the journal is the record: the return is refused while another running run or review names the
  slot under another lease. A slot whose directory is gone has nothing to return. Every failure is logged and answers
  `failed`, never an error, so no tick stops on one; the worktree stays under `.treehouse/`, for sync.
- **Sync moves what is left.** It finds each worktree of a clone under `.treehouse/` with `git worktree list` and moves
  it into `pools/` as a switch does (canopy's pool, above), keeping its ignored files, and records with it the base of
  the last lease the journal names for it, so reuse treats it as a slot parked there. One a running run or review holds
  waits for a later sync, and counts toward the declared size as a slot waiting on a switch does; one with changes, a
  process in it, or a git link canopy cannot vouch for stays, and sync says so and exits 1. Once `.treehouse/` holds no
  worktree, sync removes it. A dry run lists what it would move and changes nothing. Reconcile no longer reads
  `.treehouse/`: a treehouse lease the journal never recorded, such as one whose `_run` died before its run row, is an
  idle worktree to sync.
- **What treehouse seeded is recorded as seeded.** treehouse removed its seeded files at a return, and canopy cannot
  know which they were. So a moved slot records as seeded each path the include file selects whose copy in the slot is
  the clone's, byte for byte (a link as treehouse wrote it, a file holding its target): the next reset removes it and
  seeding writes it again, losing nothing. One that differs stays, as any ignored file does, and the next lease that
  seeds it quarantines the slot until `canopy workspace release`.
- **`pools.backend` is warned about, then ignored,** whichever value it sets: canopy's pool makes every lease, and its
  slots are made beside the ones still to move, within the declared size.
- **The release note** asks the operator to run `canopy workspace sync` on the release that made `"canopy"` the
  default, and to upgrade with no run in flight, since a `_run` of the release before returns its slot through
  treehouse. It is advice, not the guarantee: the path above is what a workspace that skipped it relies on.

Rejected: refusing to run until the operator finishes the move on the release before (a downgrade); reading
treehouse's state for its leases and seeded files (canopy would depend on the private format of a program it no longer
installs); a release note alone (a workspace that skipped it would fail its first tick with a treehouse lease in it).

### Units

A ticket's work is divided into units, one per repository it changes, each with its own PR, phase, review and CI
cursors, and attempt counts. The comment cursor, the ticket's own phase (`ready`, `blocked`, `needs_human`, and the
others not about a PR), and the branch, which every unit shares, stay per ticket (D058). The journal and the state
block carry both.

A ticket's units are the repositories it has been dispatched to, each named with `--repo` by the overseer from the
ticket, the summaries, and `MAP.md`. An `implement` over several repositories is a joint change: one worker, one PR per
repository, each linking the others, for changes that cannot build or pass tests separately. A later `implement`
naming a new repository adds a unit, also after another unit's PR merged, authorized by the ticket's label (D058). A
repository has at most one unit per ticket; work after its unit merged is a new ticket a human files (TRUST_MODEL
T1). The ticket is done when every unit's PR has merged and no other repository is left to change. A ticket of several
independent pieces that nobody asked to split gets `multi_repo` attention.

Guards (§8) change as follows:

- `running` stays per ticket: one worker per ticket, whatever its units (TRUST_MODEL §6).
- `unknown_repo`: in a workspace, no `--repo`, or one not in the map or with no primary clone; for a split child, any
  repository but the one recorded, or more than one.
- `bad_slug`: a later `implement` whose `--slug` names another branch than the ticket's.
- `no_branch`: `resume` for a unit with no branch.
- `attempt_limit` counts per unit: a run counts against every unit it covers.
- `cooldown`: a `resume` for CI alone, from the end of the latest run covering the unit that worked on CI (§8).
- `capacity` counts runs, not slots: a joint run over three repositories is one worker holding three slots.
- `no_slot`: leases are all or nothing; slots already leased are returned before the refusal is recorded.

Attention items carry an optional repository, so two units at their resume limit are two items; a run's items (§14)
stay per ticket.

### Runs over several repositories

- The branch is `<trust.branch_prefix><KEY>-<slug>` in every repository; the first `implement` fixes the slug.
- Branch setup and push verification (§8 steps 2 and 5) run in each worktree; the run is `unpushed` if any is.
- A joint run's worker runs in its desk, `desks/<KEY>/`, a link per worktree, removed when the run ends or by
  reconcile. A desk is made only in a `desks/` that is not a symlink, removal never follows its links, and canopy
  removes only desks it marked as its own; anything unmarked where a desk goes refuses the run.
- The shadowing check (§13) covers each worktree, `desks/`, and the workspace root.
- The result line's `"pr"` becomes `"prs"`, from repository name to PR URL or null, and `"pr_titles"` the same (§8).
  Each PR's body links its siblings and says which to merge first. Workers still never merge.

### Splitting

What canopy does until ROADMAP M46 replaces it with follow-up tickets (below). canopy splits a ticket in the tracker
only when an authorized replier's comment asks for it, and never schedules what it split: children start without a
queue label, so a human authorizes each (TRUST_MODEL T1).

- `--kind split` names that comment with `--request`, or is `unauthorized`. The harness cannot read the comment
  (D003), so `--request` is a recorded claim the splitter checks before creating anything.
- `bad_split` refuses a split over fewer than two repositories, of a ticket with a branch, or of a split's child.
  `policy.max_split_attempts`, default 1, counts per ticket.
- The split worker, `canopy-splitter`, has no edit, shell, web fetch, or subagent tools, and its tracker tools for
  labels, assignees, edits, PRs, branches, and files are denied. It runs in a desk and pushes nothing.
- It creates one child per repository, linked to the parent, ordered with blocker relations (§10), unlabeled and
  unassigned, or nothing. Its result line is `{"status":"done|failed","summary":"...","children":{"PROJ-13":"api"}}`,
  accepted only if each key is valid (§17), new, and not the parent, and each repository is one the split named, once;
  otherwise the run is `unknown` and records no children.
- The parent's phase becomes `split`, with attention `split_unlabeled` for each child still unlabeled, until the
  overseer marks it done once every child is closed; canopy never touches its tracker state.
- A child is a candidate only if its queue label was added after the split ended, which the overseer checks from label
  history (D003, the queue-label check's residual); a child the splitter labeled is `split_self_labeled`. Without label
  history the overseer does not split. A recorded child is refused any other `--repo` and another split.

### Follow-up tickets

Designed for ROADMAP M46, not built; the milestone lists what it removes and tests. The PR that builds it replaces
Splitting with this, and edits every section that names splits or the queue label as a ticket's only authorization.

A worker that finds work outside its ticket files it as a follow-up ticket, and canopy works it under its ticket's
authorization: a human's queue label authorizes a ticket and the follow-ups its runs file, since that work lands only
through a PR a human reviews and merges (TRUST_MODEL §6). A request to split becomes guidance to the ticket's next run,
which files the pieces as follow-ups; `--kind split` is refused `bad_kind`.

- **Who files.** An `implement` or `resume` worker on a public ticket that is not itself a follow-up; a private ticket's
  worker files none (§22). A follow-up is linked to its parent, in its project, with no assignee and no labels, and a
  blocker relation where it must land after another ticket (§10). §17's contract gains an optional row for that link.
- **The result.** The result line (§8) gains optional `"created": {"PROJ-14": "web", "PROJ-15": null}`, each ticket with
  its repository or null. `_run` checks each entry alone and records those that pass: a valid key (§17), not the run's
  ticket, new to the journal, the parent's key prefix where both have one, a mapped repository or null, at most
  `policy.max_follow_ups` per run (default 5), none from a follow-up's or a private run. A refused entry leaves the
  run's status the worker's, since a side output must not cost the run its PRs. The checks see only the key's text
  (D003), so a worker can record a ticket it did not file: an accepted gap, backed by review of every PR.
- **Working one.** A recorded follow-up is a candidate without a queue label, in the state block, and otherwise an
  ordinary ticket. Dispatch checks its record in place of `--label`, refuses `parent_withdrawn` while the parent is
  stopped (§22) or forgotten, and `unknown_repo` for any other repository. The worker's re-read (D051) checks that it
  is open and links its parent (`{{AUTHORIZATION}}`, required in an override).
- **Bounds** keep a well-meaning worker from fanning out, not a steered one, which can already label any ticket it
  reaches; the guards in code and review bound that. A reported ticket past them is an ordinary ticket, and the
  harness raises `follow_up_unrecorded`. Upgrading carries over only split children already worked, so authorizes
  nothing new.
- **Trust.** `canopy-worker` gains the tracker's create and link tools (D084); TRUST_MODEL T1, T3, and T6 change with it.

Rejected: follow-ups that wait for a queue label (the operator moved the line); a `canopy` verb to record one (anything
with a shell could); follow-ups of follow-ups (fan-out compounds).

Open, for the operator: the parent's phase once a split moved its work into follow-ups; journal-only follow-ups for a
private ticket; whether `max_follow_ups = 0` is enough for an operator who wants the old line; whether a parent losing
its label withdraws its follow-ups; a bound per ticket rather than per run; how long `follow_up_unrecorded` stands;
whether a follow-up waits as a draft under `trust.review_replies = "approve"` (§29).

### Trust model changes

This section relies on TRUST_MODEL T1 (a split creates tickets, never on its own decision and never labeled), T4 (a
worker's edit permission covers the worktrees linked from its desk, which the desk canary checks), T6 (the write scope
is the run's repositories; the splitter's, creating and linking tickets and commenting on the parent), T7 (the shared
workspace file; the private state directory, D053), and §7 (branch protection in every mapped repository).

### Open

- Whether an authorized replier's approval of the split on the parent should make an unlabeled child a candidate.
- Whether a child's desk should also hold its blockers' unmerged branches, read-only by prompt, to build against.
- Whether a started ticket should ever be split. `bad_split` refuses it now; a human splits one by hand.
- Whether a follow-up PR after a unit merged, for late review feedback, should be possible inside the ticket. D058
  leaves it to a new ticket.
