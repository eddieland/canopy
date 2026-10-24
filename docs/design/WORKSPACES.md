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
| Create a ticket linked to a parent (worker, optional) | follow-ups |

"Label" means the tracker's tagging primitive, whatever it is called. A `tracker` source (§30) reads the overseer's rows
into the journal, so the overseer reads them there, and the tracker itself only about a ticket the observations leave
stale or unobserved. Without blocker relations, tickets are treated as unblocked. Without label history, the worker's
question comment is the reference point for `human_replied`. If a tracker cannot do a required row, the overseer records
`skip` with rationale `tracker_unsupported: <capability>`.

### Authorization is the same everywhere

The query only finds tickets. A ticket is a candidate only if reading it shows one of `tracker.labels` present and the
ticket not closed, so a sloppy query can waste a tick but cannot authorize work. Where a tracker source observes it,
that is decided in code, and a ticket that is not a candidate reaches the overseer by key and why alone, none of its
text (§30). Replies are authorized only by `trust.authorized_repliers`, compared against the author's stable account id
(Jira `accountId`, GitHub login), never a display name, and marked in code on each comment a source observes (§7).

### Ticket keys

A key is the tracker's short, human-readable id, as the provider skill defines it: `PROJ-123` for Jira, `GH-123` for
GitHub Issues. Keys appear in branch names, lease holders, file paths, and shell arguments, so every command that takes
one rejects, in code, any key that does not match `[A-Za-z0-9][A-Za-z0-9_-]*`.

## 18. Workspaces and multi-repo tickets

canopy runs only from a workspace, even for one repository: a workspace of one repository is a map with one entry. A
workspace is a directory canopy manages and the loop runs from: the map, `canopy-workspace.toml`, also the shared
config layer; `MAP.md`, on what each repository owns and how they depend on each other; a primary clone of each
repository; the worktree pools; a desk per joint run; and canopy's state, which only the operator may read.

It relies on TRUST_MODEL T1, T4, T6, T7, and §7, branch protection in every mapped repository.

### The map

The map names each repository with a `url` and a one-line `summary`, and holds the shared config keys of §12, which may
only tighten policy. A clone is always under the workspace, so a map cannot point outside it. `summary` and `MAP.md` are
data, like ticket text, and authorize nothing, and nothing in the repositories is read as config: one tracker, one
queue. A map committed to a shared repository is exposed as any file in it is (TRUST_MODEL T7); `url` is read only by
the operator's workspace commands and for the web UI's branch links, which never carry a credential (D115). A tick
never clones or changes a remote: a mapped repository with no clone is attention `repo_missing` and cannot be
dispatched to. `canopy workspace sync` clones it, with credential prompts and git's `ext::` transport off, and never
changes an `origin` that differs from the map. It fetches each clone already there and fast-forwards its default branch
when that is checked out, clean, and behind; the checkout is the operator's, since runs start in slots, so a clone on
another branch or with work of its own is left as it is. A state directory that is a symlink, someone else's, or open
to others stops every command until removed (D053).

### Declared repositories and slots

canopy's pools live under the workspace, whatever a repository's `treehouse.toml` says, so an interactive `treehouse`
never recycles canopy's slots; no key puts them elsewhere (D033). The map declares the repositories and the operator's
private or user config each pool's size (D066), which a tick never grows. `canopy workspace sync` converges on both:
it fills each pool, so setup hooks run then rather than in a run's lease; it trims idle slots, and removes a clone the
map no longer lists, only when nothing would be lost; and it turns off git's automatic maintenance in each primary
clone, which would prune the git directory every slot shares under other slots' runs. Each tick raises
`auto_maintenance_on` for a clone whose own config does not turn it off, until a sync does.

### What a pool guarantees

What canopy takes from a pool, whichever implements it, is this list, and a caller may rely on nothing else. Each
guarantee is held by a case of the pool contract suite, run against canopy's pool, the fake, and real treehouse.

- **Leasing.** Leases held at once are different slots. A run's lease fetches `origin` first and starts at the base's
  tip, in a linked worktree of the primary clone, detached, that passes the run's check (§8).
- **Returning.** A return needs the lease's id and holder both, so it never touches the slot's next holder, and works
  after the clone is gone. It ends the slot's processes and discards changes, untracked files, and unheld commits.
- **Reuse.** A returned slot is reused before a new one is made, reset to the base's tip, keeping only its ignored
  files. A slot that is dirty, in use, or not merged into the base is never reused.
- **Seeding (§9).** A lease copies in the ignored files the include file selects, never a tracked file, and a return
  removes them. A seed target already in the slot fails the lease and quarantines the slot.
- **Removing.** Only an idle, clean, merged slot that a pool manages is removed.
- **Size.** A declared pool with every slot busy, a dirty idle one counting as busy, refuses a lease without growing.

### canopy's pool

`pools.backend`, private config, chooses whether treehouse, the default, or canopy's own pool makes the worktrees;
callers do not know which they have. canopy's pool keeps every guarantee above. A slot goes back to the pool that made
its lease, so switching with runs in flight is safe. A quarantined slot, in either pool, waits for the operator's
release, since the file seeding collided with may be a run's work. Every git canopy's pool runs has D107's flags; a
slot that does not point into its primary clone (D118), or whose processes cannot be read, is never reset, reused, or
removed.

### Upgrading past treehouse

Designed, not built (ROADMAP M45, stage 4). The release that removes treehouse finishes the move to canopy's pool with
git alone, rather than refuse to run until the operator makes it on the release before, which would mean a downgrade;
nothing in it may stop a tick. A lease the journal says treehouse made is returned by canopy as a return to its own pool
is, only for a slot under `.treehouse/` that passes D118's check and no other running run names; a failure is logged and
the slot left for sync. `canopy workspace sync` moves each idle, clean worktree left under `.treehouse/` into the pool,
recording as seeded only files identical to what seeding would write, so the next reset loses nothing; one it cannot
vouch for stays, and sync says so. `pools.backend` is warned about, then ignored.

### Units

A ticket's work is divided into units, one per repository the overseer dispatches it to, each with its own PR, phase,
review and CI cursors, and attempt counts; the comment cursor, the phases not about a PR, and the branch stay per
ticket (D058). A run over several repositories is a joint change: one worker, one PR per repository, for changes that
cannot build or pass tests separately. A later `implement` naming a new repository adds a unit, even after another
unit's PR merged, authorized by the ticket's label (D058). A repository has at most one unit per ticket; work after it
merged is a new ticket a human files (TRUST_MODEL T1). The ticket is done when every unit's PR has merged and no other
repository is left to change; independent pieces nobody asked to split get `multi_repo` attention. There is still one
worker per ticket (TRUST_MODEL §6). A run names only mapped, cloned repositories and keeps the ticket's branch;
attempt limits and the CI cooldown count per unit; capacity counts runs, not slots; and leases are all or nothing.

### Runs over several repositories

The branch has one name in every repository. Branch setup, push verification (§8 steps 2 and 5), and the shadowing check
(§13) cover each worktree; the run is `unpushed` if any is. A joint run's worker runs in a desk of links to its
worktrees (TRUST_MODEL T4); canopy makes desks only where no symlink redirects them, never follows their links on
removal, and removes only desks it marked as its own. The result line names a PR per repository (§8), and each PR links
its siblings and says which to merge first.

### Follow-up tickets

ROADMAP M46, which holds the details. A worker that finds work outside its ticket may file it as a follow-up, linked to
its ticket, with no label: a request, which authorizes nothing (TRUST_MODEL T1, D123). The operator decided (2026-10-19)
that workers notice and ask, and humans authorize: a follow-up is worked only once a human labels it or starts it, as
any ticket. canopy records the follow-ups an `implement` or `resume` run, public or private, reports in its result's
`created` (§8), at most `policy.max_follow_ups` per run, and none from a follow-up's own run or from a run that rewrote
its slot's git, checking only each key's text (D003). It then tells the operator once: the run's `follow_ups.filed`
event (§20) names each, a point event and not an attention item, since a follow-up left unlabeled is a fine answer. A
refused entry never changes the run's status; it raises `follow_up_unrecorded`. An authorized reply asking for a split
is guidance to the ticket's next run, whose worker files the pieces as follow-ups, ordered with the tracker's blocker
relation. Splitting is no longer a run kind; `split` survives only as the kind of old runs. Rejected: working a
follow-up under its parent's label, since a worker would then authorize work for itself; a standing attention item per
follow-up, which canopy could clear only on a run, a start, or done, so a declined one stayed until its parent was.

### Open

- Follow-ups: the parent's phase once its work moved to them, and whether a parent losing its label withdraws them.
- Whether a follow-up PR after a unit merged, for late review feedback, should be possible inside the ticket.
