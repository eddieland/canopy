# The overseer reads the journal

Part of the canopy design, normative like all of it: the overseer deciding from what the connectors observed instead of
reading the tracker and GitHub itself, and the harness checking in code what was the overseer's word. Sections are
numbered across the whole design; the [README](README.md) has the map. Previous: [Published
reviews](PUBLISHED_REVIEWS.md). Next: [One-off tasks](TASKS.md).

## 35. The overseer reads the journal

Being built (ROADMAP M37), ahead of §30's measurement at the operator's word. Built: the observations in the state
block, the prompt's procedure that decides a fresh subject from them, the claims of a dispatch and the cursors of
`canopy_ticket-set` checked in code, and comments reaching the conversation in code (§22), the `mirror` tool gone.
`handled` and cursors as journal numbers wait, and neither needs the overseer's tools (§27), whose verbs the commands
share.
Until each is built, §4 principle 1, §6, §7, §8, §17, §22, and TRUST_MODEL describe canopy as it is; this section says
what changes, and the PR that builds the last of it cuts this one to what is left.

Re-reading the tracker and GitHub every tick is most of the overseer's spend (MEASUREMENTS 2026-10-15), and §30's
connectors already read the same facts into the journal. So the overseer decides from what they observed, and the
harness, which can now see a ticket's labels and who wrote a comment, checks in code what the overseer used to claim.
Judgment stays the overseer's: which repository, a slug and a title, a worker's context, what a comment or reply asks.

### The observations in the state block

- Every ticket the block lists, and every ticket the tracker query returned, is marked a candidate or not in code, from
  its observed labels and state (§17). One that is not is listed by key and why, and none of its text reaches the
  overseer, so a widened query shows it nothing (TRUST_MODEL T7).
- A candidate carries its title, state, labels, and blockers; its body until its first unit exists, since the
  repository and slug are chosen from it; and its comments past its `comment` cursor, each with its id, author, time,
  and body, and two marks set in code: whether the author is an authorized replier, and whether it is a worker's
  (D069).
- A unit carries its PR's state, head, base, draft, and mergeable state; each named check at the head, a human check
  marked (§30); each person's latest verdict, since an approval before the cursor still approves; and the reviews and
  review comments past its `review` cursor, each marked trusted or not in code (D089).
- Each subject carries the rows of §7 the derivation found holding (§30): the harness's reading, which the overseer may
  overrule, since §7 has no order yet and a row moves into code only on evidence (D008, §37).
- The tracker query's result and the review query's (§21), as their sources last read them whole. A fresh tracker
  query's result is recorded by the harness, so `canopy_queried` is owed only on a tick whose query no source read (§6).

Text is the observation's, cut and marked as §30 cuts it. A subject shows at most a fixed number of new items, oldest
first, and counts the rest, which stay new. Source and author are labeled by the harness, never by a model. The
observations go after the block's fixed sections: they change every tick, and the fixed ones are what the provider
caches (§6 step 4).

Each subject is `fresh`, observed within `connect.max_age_minutes`; `stale`, past it, naming what is old, as the
derivation does; or `unobserved`, when no source covers it, such as every ticket of a tracker with no `tracker` source.
§30's `vcs` request also names the PRs review requests wait on (§21), so ending one reads an observation too.

### The overseer stops reading

The prompt's procedure drops its reads: no tracker search, no ticket, PR, check, or review read, no mirroring, and no
provider skill. Built so far: those reads, for a fresh subject, and mirroring for every subject; the skill stays for the
stale and unobserved ones. The overseer calls the tracker's or GitHub's MCP only about a subject marked `stale` or
`unobserved`. That is the prompt's rule, not a guard, but spend by tool (§11) counts each call. A stale subject's live
read can mark a closed ticket done or raise an attention item, never start a run (below). An unobserved subject keeps
today's procedure, provider skill and claims included (Open). A later step takes the MCP servers away (ROADMAP M39).

### Claims checked in code

What was the overseer's word becomes a reference to an observation. `canopy_dispatch` checks each before §8's other
guards, and a refusal is a decision, as every guard's is (§8):

- Its `label` must be one the tracker source observed on the ticket; else `unauthorized`. The worker still reads the
  labels again (D051), since an observation can be a tick old.
- A `resume` for `reply` must carry a cursor to a comment by an authorized replier that is not a worker's, or to an
  operator message, past the ticket's cursor of that kind; else `unauthorized`.
- A `resume` for `review` must cover, past the unit's `review` cursor and up to the one it carries, an item by a
  trusted reviewer, or the canopy review it names when `canopy:review` is trusted, and another reviewer's item only
  with an operator message after it, carried by its `message` cursor; else `unauthorized` (D089's revisit). With
  feedback plans on, §32's approval is the gate instead, as it is today.
- Every cursor, on a dispatch or `canopy_ticket-set`, must name an item observed for its subject, and never pass one the
  block left out for its bound; else `unobserved`.
- A dispatch is refused `stale` while a subject it rests on is stale: a public ticket, a stacked dispatch's blocker's
  PR (§10), and the PR of each unit a `resume` names. A private ticket, which its start record authorizes (§22), a
  chore, a review, and an unobserved subject are not refused, and an unobserved one's claims stay claims. A subject
  whose source keeps failing stays refused until the source recovers, and the operator sees each refusal as a decision
  (§30, Open).

Principle 1's "before any action that matters, re-read live state" becomes "observed within `connect.max_age_minutes`,
or no dispatch". The default keeps what step 3 read fresh through the tick's dispatches (§30).

### Cursors

Each comment, review, review comment, and check run takes the next journal number when a source first observes it, and
keeps it across later reads of its subject; a canopy review run takes one when it ends. A cursor is such a number, and
"newer than the cursor" means first observed after it: one order for every kind, so the `review` cursor needs no time
form (§7). Rejected: the source's ids, which no tracker orders, and times, which a late submission backdates.

CI is observed by head, context, and run, so a re-run at the same head is seen (§8). A `resume` for `ci` alone is
refused `handled` when its only failure repeats one at the same head and context (PRIOR_ART, CI newness).

### Trust model changes, when built

- T1: labels, authorized repliers, and trusted reviewers are checked in code against observations, before the worker's
  own check, so a steered overseer cannot start a run on one never observed; its MCP is narrowed, by prompt, to stale
  and unobserved subjects. Residual: the guards trust what a connector printed, and a label removed since its read
  authorizes until the worker's check.
- T2: `canopy-connect-jira`'s credentials (§30) join the GitHub programs' line.
- T7: `connect.*` joins the private keys: a source runs a command with the operator's credentials, and
  `connect.max_age_minutes` decides when a dispatch is refused. The widened query's residual closes.
- D003 is edited in place: the harness can now check who wrote a comment a connector observed. D051 and D089 gain their
  code checks.

### Open

- Whether a tracker with no connector keeps the live-read procedure, with its provider skill and label claim,
  or a `tracker` source is required. Recommended: required. The two shipped cover the operator's trackers, and the
  contract is a page of Python for another. Required, it changes §3's and principle 5's "any tracker with an MCP
  server", and §17. Until it is settled, such a tracker keeps the live reads: its tickets are `unobserved`.
- How many new items a subject shows before the rest are counted, set from the measurement's ticks. Ten until then,
  the conservative choice: a busy subject waits a tick rather than swelling every block.
