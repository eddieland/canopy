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
   ticket's page is, with `{key}` for its key, and the web UI links each ticket there (§22). It is the only tracker
   address canopy knows, and nothing but a browser the operator clicks in follows it (D003). It is shared config
   because the address is the team's, and a link runs nothing, spends nothing, and authorizes no one (TRUST_MODEL T7).
   Rejected: a URL per ticket from the overseer (agent-written text in an `href`); a link format per provider (tracker
   code in the harness).
3. **A provider skill**, `.agents/skills/tracker-<provider>/SKILL.md`, for what an agent would otherwise get wrong:
   identity fields, how "closed" is expressed, where blockers live, and text that silently triggers a tracker action
   (closing keywords, smart commits). Skills ship for `jira` and `github`. A skill is optional; add one when the
   `decisions` table shows the loop misreading a tracker, not in advance. The overseer gets the shipped skill for
   `tracker.provider` in its prompt (§13); workers load it as a skill.

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

canopy runs only from a workspace, even for one repository: a workspace of one repository is a map with one entry.

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
  pools/api/1/api            canopy's own pools, with `pools.backend = "canopy"` (canopy's pool, below)
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
- The web UI links a ticket's branch in each repository, and a worktree's branch, to its page on the host (§22). By
  default the link comes from a GitHub `url`; any other host gives none (D115), and a credential in the URL never
  reaches the link. `branch_url`, optional, overrides it with a template, `{branch}` for the name (GitLab's
  `https://gitlab.com/acme/api/-/tree/{branch}`), checked as `tracker.ticket_url` is (§17): a plain `https://` URL of
  at most 500 characters with `{branch}` exactly once and no other braces. An empty one turns the links off. Nothing
  but a browser the operator clicks in follows one.
- Config layers: built-in defaults, the workspace file, the user file, the workspace's private file
  (`.canopy/config.toml`, §12). The workspace file's policy may only tighten. Nothing in the repositories is read as
  config: one tracker, one queue.
- A map committed to a shared repository is exposed as any file in it is (TRUST_MODEL T7). `url` is read only by the
  operator commands `canopy workspace sync`, which prints what it clones first, and `canopy workspace add`, which
  writes it, and for the web UI's branch links. Map URLs should be HTTPS (§12); `sync` warns about SSH ones and clones
  them anyway. A tick never clones or changes a remote; a mapped repository with no clone is attention `repo_missing`
  and cannot be dispatched to.
- `canopy init` makes the workspace skeleton, overwriting nothing, and prints the branch protection rules with every
  mapped repository they must be configured in; given URLs, it first adds them as `canopy workspace add` does.
- `canopy workspace add` adds repositories to the map by URL, keeping its comments and layout, then syncs. A name
  already given another URL, or a URL with no usable name, refuses the whole command and writes nothing.
- `canopy workspace sync` makes the workspace match the map and the declared slots: it clones each missing repository
  with credential prompts and git's `ext::` transport off, never prints a URL's credential, reports an existing
  clone's `origin` that differs from the map and changes no remote, and sizes pools and removes unlisted clones
  (below). It exits 1 when anything declared could not be reached.
- A workspace's state is always `<workspace>/.canopy/`, created readable only by the operator, so each workspace has
  its own journal and locks. A `.canopy/` that is a symlink, someone else's, or open to others stops every command
  with a config error until removed (D053). A definitions snapshot inside it is checked the same way before each run
  loads it (§13).

### Worktrees live in the workspace

Every treehouse command canopy runs has `TREEHOUSE_ROOT` set to the workspace root, so pools live under
`<workspace>/.treehouse/` whatever a repository's `treehouse.toml` says. They are separate from the operator's
interactive pools under `~/.treehouse`, so an interactive `treehouse` never recycles canopy's slots. Build caches must
still be slot-independent (§9).

There is no key to put a workspace's pools anywhere else (D033); for a fast disk, put the workspace on it. git does a
worktree's work in its primary clone's `.git`, so a pool on another disk than its clone still works on the clone's. A
pool root shared by every workspace would put two workspaces' clones of a repository in one pool (treehouse names a
pool by repository and remote), where each would count the other's slots. Build outputs need not follow the
workspace: Bazel's live wherever the operator's `.bazelrc` puts them (§9).

Each tick's reconcile reads the pool of every mapped repository with a clone and returns stale `canopy:` leases. A
repository with no clone has no pool; the tick records `repo_missing` (§14) and dispatch refuses it. A run's slot is
returned through the pool of the repository it records, even after that clone is gone. The overseer runs at the root,
not in a repository, so the state block carries each pool's leased slots. Lease holders stay `canopy:<KEY>`; one ticket
can hold a slot in several pools.

### Declared repositories and slots

The map declares the repositories; the operator's config declares each pool's slots (D066): the workspace's private
file for its own pools, or the user file for every workspace's. `canopy workspace sync` converges on both, and a tick
never grows a pool past its declared size.

```toml
# .canopy/config.toml, or ~/.config/canopy/config.toml for every workspace
[capacity]
slots_per_repo = 2      # every repository's pool
[capacity.repo_slots]
api = 4                 # by repository name; wins over slots_per_repo
```

- Pool sizes are private (§12). `repo_slots` may name repositories this map does not list, as a user file's does. With
  neither key (the default) a pool is unmanaged: treehouse's `max_trees` bounds it and sync leaves it alone.
- **Leases stay within the size.** Dispatch (§8) and a review (§21) refuse a lease as `no_slot` when as many slots as
  the declared size are busy; a size of 0 refuses every lease. If treehouse makes a slot anyway, canopy returns it,
  destroys it, and refuses. A pool under its size grows normally.
- **Sync fills each pool** to its size with leases of its own, holder `canopy-sync`, made without fetching and then
  returned, so slots are made, and `post_create` runs, during sync rather than in a run's lease. Reconcile never
  touches `canopy-sync` leases. If treehouse refuses to grow the pool, usually because its `max_trees` is below the
  declared size, sync reports the repository failed; canopy cannot set `max_trees`, which treehouse reads only from
  its own config files.
- **Sync trims each pool** of available slots over its size through `treehouse destroy`, unforced, so treehouse
  removes only a clean, merged, idle, unleased slot and passes over any other. Busy slots over the size wait for a
  later sync. A pool kept over its size by a slot with work in it makes sync exit 1.
- **Sync removes clones the map no longer lists.** Anything under `repos/` the map does not name, except dot entries,
  is removed with its pool's slots only when nothing would be lost: a real directory with a `.git`; no changes, no
  ignored files (a primary clone holds the local config seeded into slots), and no stash; every commit on a
  remote-tracking ref; and every slot in its pool available and destroyed by treehouse unforced. Anything else is kept
  and reported, and sync exits 1.
- **Sync turns off git's automatic maintenance** in each primary clone's own config, which every slot of its pool
  shares. Started in the background by a fetch or commit, it packs refs and prunes on that shared git directory while
  other slots' runs use it, and has pruned a worktree being made. The harness's own git runs with it off too (§8). A
  dry run sets nothing. Nothing runs maintenance in its place yet (§26 plans `canopy gc --git`); the operator can run
  `git maintenance run` in a clone while none of its pool's slots is leased.
- Sync holds the tick lock, waiting for a running tick to end. Runs in progress keep their leases, counted as busy.
- A dry run changes nothing. A clone it would keep a real sync keeps; what it would remove, treehouse may still keep.
- A lease sync cannot return, its own or a dead sync's, makes the pool `failed` and sync exit 1.

### What a pool guarantees

What canopy takes from a pool, whichever implements it, is this list. Each guarantee is held by a case of the pool
contract suite (`tests/canopy/core/test_pool_contract.py`), run against canopy's own pool, the fake, and real
treehouse. A behavior with no case is not a guarantee, and a caller may rely only on what is listed here. The fake
does not model git, so the guarantees about what is in a slot hold only for a pool of real worktrees.

Leasing:

- A new pool has no slots.
- A lease names its slot, its id, its holder `canopy:<KEY>`, when it was taken (ISO 8601 with an offset), and its base
  branch by its bare name, `main` by default; `status` shows the slot `leased` under the same id, holder, and time.
- Slots are numbered from 1 under the workspace: treehouse's `<root>/.treehouse/<pool>/<N>/<repo>`, canopy's
  `<root>/pools/<repo>/<N>/<repo>`.
- Leases held at once are different slots.
- A lease on a base starts at that branch's tip.
- A lease fetches `origin` first; sync's lease without a fetch cuts the slot from the refs already there.
- A slot is a linked worktree of the primary clone, detached at its base, whose `.git` file and `commondir` pass the
  run's check (§8).
- A sync lease names no ticket.

Returning:

- A return frees the slot: `available`, with no lease id, holder, or time.
- A return needs the lease's id and holder both, and fails otherwise, leaving the lease; so a lease returns once, and
  never touches the slot's next holder.
- Returning a path no pool manages fails.
- A return finds the slot's pool from the slot's own path, so it works from the workspace root when the clone is gone.
- A return is forced: it never answers `dirty`, and it discards uncommitted changes, untracked files, and commits no
  branch holds, leaving HEAD at the base.
- A return ends the processes in the slot first.

Reuse:

- A returned slot is reused before a new one is made.
- Reuse resets the slot to the base's tip and keeps its ignored files, such as build outputs and caches, and nothing
  else.
- A return parks the slot on its lease's base, and a slot parked on a stacked run's base is still reused.
- An idle slot with changes is `dirty`, and one with a process in it `in-use`; neither is reused.
- An idle slot whose HEAD is not merged into the base is not reused, though clean and so `available`: `available` does
  not promise reusable.

Seeding (§9):

- Every lease, a reused slot's too, copies from the primary clone the untracked, ignored files the include file
  selects, and nothing else; never a tracked file.
- A return removes what seeding wrote, so the next lease seeds afresh.
- A seed target already in the slot fails the lease, and the slot is held under the holder `quarantined: worktree
  seeding failed`, which no ticket can name, until the operator releases it.
- A release frees only a slot held so, and resets it as a return does: the file seeding collided with stays.
- A seeded symlink is written as a regular file holding the link's target; whether it should be a link is open
  (ROADMAP M45).
- A missing include file fails the lease before any slot is touched.

Removing (sync's trim, above):

- `destroy` removes an idle, clean, merged slot and its directory, and keeps, saying why, a slot that is leased, dirty,
  in use, holds commits not merged into the default branch, or that no pool manages.

Size (above):

- A pool with no declared size stops at its bound: treehouse's `max_trees`, or 16 for canopy's.
- A declared pool with every slot busy, a dirty idle one counting as busy, refuses a lease without growing, and keeps
  its size when its idle slot cannot be reused.

Not guaranteed, though treehouse does it: `status` rewrites treehouse's state, forgets a slot whose directory is gone,
and records a worktree it finds in the pool directory as held; `destroy` runs `git fetch` and `git ls-remote` on
`origin` first; `post_create` hooks run after seeding. treehouse runs git with none of D107's flags.

### canopy's pool

canopy's own pool (ROADMAP M45) keeps every guarantee above, held to them by the same cases. `pools.backend` (§12),
private, chooses which pool makes a workspace's worktrees: `"treehouse"`, the default, or `"canopy"`. Every caller
reaches either through one interface and none learns which it has.

- **A lease goes back where it came from.** The journal records which pool made each lease, and a slot is always
  returned through that pool, whatever `pools.backend` names by then, so switching with runs in flight is safe.
  Reconcile reads the configured backend's pools, and a failure stops the tick as before; it also reads the other
  backend's where the workspace has any on disk, so a lease left there still goes back, and one it cannot read there
  is logged, not fatal. The state block's leased slots come from both.
- **Switching** is `canopy workspace sync`'s. To `"canopy"`, it moves each idle treehouse slot into `pools/`, keeping
  everything in it, ignored files and build caches too; a busy one waits for a later sync, and its lease goes back to
  treehouse meanwhile. A busy slot left in treehouse's pool counts toward canopy's declared size, so sync makes only
  the slots the move cannot supply, and the waiting slot still fits when it moves; an idle one the move refused does
  not count, since no later sync moves it either. A dry run counts the slots its move would bring in, as the real
  sync does. A run's lease can still fill canopy's pool to its size meanwhile, if no slot
  there can be reused; the waiting slot then stays in treehouse's pool, reported kept. Back to `"treehouse"`, it
  removes canopy's idle slots as its trim removes a slot, keeping one with anything to lose, and treehouse makes fresh
  slots: switching back costs only warm caches. Sync exits 1 on a slot it had to keep.
- **No `post_create`.** canopy's pool runs no hook; what one did moves to `runtime.setup_cmd` (§9, BAZEL.md).
- **Layout.** A repository's slots are `<workspace>/pools/<repo>/<N>/<repo>`. There is no hash of the remote in the
  path: a workspace's repository names are unique, and the pools are the workspace's own (D033).
- **Leases are journal rows**, taken under a lock per pool, so two leases never pick one slot. A slot is claimed in a
  transaction of its own, before the run that needs it is recorded, as treehouse's lease is; a lease whose process dies
  before its run is recorded is a `canopy:` lease no running run holds, which reconcile returns.
- **Size.** The declared size is the only bound; a pool with none declared stops at 16, treehouse's default
  `max_trees`. canopy's pool reads no config of treehouse's.
- **Lease, reuse, return, and seeding** follow treehouse's. Seeding never writes through a link in the slot. A
  collision quarantines a reused slot under the holder `quarantined: worktree seeding failed`. Reuse takes an idle slot
  only when it is clean, has no process in it, and its HEAD is an ancestor of the base or of the base it was last
  leased on. treehouse also reuses one whose HEAD has the same content as a squash merge into the base; canopy's pool
  makes a new slot instead.
- **A quarantined slot waits for the operator,** in either pool. Reconcile never returns it, and it counts as busy
  against the declared size until `canopy workspace release REPO SLOT` frees it in the pool `pools.backend` names. The
  command refuses any other slot, since a run's lease goes back with its run or through reconcile. Nothing frees one on
  its own, sync included: the file seeding collided with may be a run's work, so the operator removes it, or a lease
  that seeds it fails again. The worktrees page says so on the slot.
- **Processes in a slot** are read from `/proc` on Linux and with `lsof` on macOS, with no dependency. A return ends
  them; one that outlives SIGTERM and SIGKILL fails the return and keeps the lease. A slot whose processes cannot be
  read is `unverified`, never reused, and kept by `destroy`.
- **The host stays safe.** Every git the pool runs has D107's flags. Before any git in a slot, the slot's `.git` file
  must name a directory under the clone's `.git/worktrees/`, and its `commondir` the clone's `.git` (D118); a slot that
  fails is `damaged`, never reset, reused, or removed. A return frees such a slot without a reset.
- **No network but a lease's fetch.** `destroy` judges merged against the default branch as last fetched, never with
  `ls-remote`: sync runs it after leases that fetched, and a stale ref keeps a slot rather than losing one.
- **Recovery.** A worktree in the pool's directory with no row, such as a lease that died after making it leaves, is
  adopted as an idle slot when it is a sound worktree of the clone. An idle row whose directory is gone is forgotten at
  the next lease. `status` changes nothing.

**The shadow.** While treehouse makes the pools, every tick's reconcile also classifies each idle treehouse slot with
canopy's pool's checks and logs a `pool_shadow_mismatch` line, with the repository, the slot, and both answers,
wherever they disagree. It changes nothing, and a check that fails is logged, never raised. Each mismatch the operator
explains becomes a contract case, and canopy's checks are fixed until it passes.

### Units

A ticket's work is divided into units, one per repository it changes, each with its own PR, phase, review and CI
cursors, and attempt counts. Per ticket stay the comment cursor, the ticket's own phase (`ready`, `blocked`,
`needs_human`, and the others not about a PR), and the branch, which every unit shares (D058). A single-repository
ticket has one unit.

A ticket's units are the repositories it has been dispatched to. Each dispatch names its units with `--repo`
(repeatable, at least one), chosen by the overseer from the ticket, the summaries, and `MAP.md`. An
`implement` over several repositories is a joint change: one worker, one PR per repository, each linking the others,
for changes that cannot build or pass tests separately. `resume` normally names only the unit needing
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
- `no_branch`: `resume` for a unit with no branch.
- `attempt_limit` counts per unit: a run counts against every unit it covers.
- `cooldown`: a `resume` for CI alone, from the end of the latest run covering the unit that worked on CI (§8).
- `capacity` counts runs, not slots: a joint run over three repositories is one worker holding three slots.
- `no_slot`: leases are all or nothing; if any lease fails, slots already leased are returned before the refusal is
  recorded.

Harness attention items for runs (§14) stay per ticket, their detail naming the repositories that failed. An
`attempt_limit` refusal's item and the overseer's items about a PR name their unit.

### Runs over several repositories

- The branch is `<trust.branch_prefix><KEY>-<slug>` in every repository. The ticket's first `implement` fixes the slug;
  later implements reuse it (`bad_slug`, above).
- The run does branch setup (§8 step 2) and push verification (step 5) in each worktree, and is `unpushed` if any
  repository's branch is. A joint run's worker runs in its desk, `desks/<KEY>/`, a link per worktree named for its
  repository, removed with every slot returned when the run ends, or by reconcile when it died. A desk is made only in
  a `desks/` that is not a symlink, and removal never follows its links. canopy removes only desks it marked as its
  own; anything else under `desks/` is the operator's, and something unmarked where a desk goes refuses the run.
- Before a joint run's worker starts, the shadowing check (§13) covers each worktree, `desks/`, and the workspace root,
  since OpenCode may read config above the desk.
- The result contract's `"pr"` becomes `"prs"`, an object from repository name to PR URL or null; each URL is recorded
  as its unit's PR. `"pr_titles"` maps the same names to each PR's title, recorded by its URL (§8).
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
- `bad_split` refuses a split over fewer than two repositories, of a ticket that has a branch (split it by hand), or of
  a split's child. `--slug` is `bad_slug` and `--base` `bad_base`: a split has no branch. `policy.max_split_attempts`,
  default 1, limits `split` attempts per ticket, never per unit.
- The split worker runs with `runtime.split_cmd` as `canopy-splitter`: an agent definition with no edit, shell, web
  fetch, or subagent tools, and MCP tools whose names suggest labels, assignees, edits to existing tickets, PRs,
  branches, or files denied by pattern. The check below holds even where the runtime cannot forbid labels on create.
- It runs like a joint run, in a desk of the named repositories' worktrees, each detached at its base branch, with the
  worker's timeout and `MAP.md` in its prompt, since it may not read outside its desk. It makes no branch, pushes and
  verifies nothing, and records no unit. Its slots and desk are cleaned up as any run's are.
- It creates one child per repository with a share of the work, if each share can be built and reviewed alone;
  otherwise it creates nothing and reports `failed` saying why. Each child's body names its repository
  (`canopy-repo: web`) for people, links the parent, and says what it covers. Children that must land in order get
  the tracker's blocker relation (`web` blocked by `api`), so blocker ordering applies (§10). Children carry no queue
  label and no assignee.
- It comments on the parent listing the children and which label starts each. Its result line is
  `{"status":"done|failed","summary":"...","children":{"PROJ-13":"api","PROJ-14":"web"}}`, listing every child it
  created even when `failed`. The run accepts it only if each key is a valid ticket key (§17), new to the journal and
  not the parent, each repository is one the split named, at most once, and a `done` split names at least one child;
  otherwise the run is `unknown` and records no children. A valid result is recorded even when the run timed out after
  printing it, and is the source of a child's repository afterwards.
- The parent's phase becomes `split`: wait, with attention `split_unlabeled` naming each child still open and
  unlabeled. Any dispatch for it is `bad_split`. The overseer marks the parent `done` in the journal once every child
  is closed; canopy does not touch its tracker state.
- A child is a candidate only if its queue label was added after the split run ended. The state block carries each
  split child (parent, repository, split run, when that run ended) until parent and child are both done, and the
  overseer compares it with the tracker's label history. A label the split worker added, at creation or later, does
  not count: the overseer records `split_self_labeled` for that child, which stays out of the queue until a human
  removes the label and adds it again. On a tracker without label history (the optional row of §17's contract) the
  overseer does not split; it records `multi_repo` saying why.
- This check is the overseer's, not a harness guard, since the harness never reads the tracker (D003): the same kind
  of control as the queue-label check (§17), with the same residual (TRUST_MODEL T1).
- A child is an ordinary one-repository ticket. `canopy dispatch` for a recorded split child refuses any `--repo` but
  the recorded one (`unknown_repo`), so editing its `canopy-repo` line changes nothing, and refuses another split
  (`bad_split`). A ticket split by hand has no such record; the overseer chooses its repository as for any ticket.

### Journal

The journal records each ticket's units beside its own phase, and the state block shows both; each run's leases, one
per repository, with the pool that made each; and each split child, written only from a validated split result.
Attention items carry an optional repository and are identified by ticket, repository, and reason, so two units at
their resume limit are two items.

### Trust model changes

This section relies on TRUST_MODEL T1 (a split creates tickets, never on its own decision and never labeled), T4 (a
worker's edit permission covers the worktrees linked from its desk, which the desk canary checks), T6 (the write scope
is the run's repositories; the splitter's, creating and linking tickets and commenting on the parent), T7 (the shared
workspace file; the private state directory, D053), and §7 (branch protection in every mapped repository).

### Open

- Whether an authorized replier's approval of the split on the parent, rather than a label on each child, should make
  an unlabeled child a candidate. The request that started the split is not that approval.
- Whether a child's desk should also hold its blockers' unmerged branches, read-only by prompt, to build against.
- Whether a started ticket should ever be split. `bad_split` refuses it now; a human splits one by hand.
- Whether a follow-up PR after a unit merged, for late review feedback, should be possible inside the ticket, on an
  authorized replier's comment. D058 leaves it to a new ticket; revisit if filing those proves friction.
