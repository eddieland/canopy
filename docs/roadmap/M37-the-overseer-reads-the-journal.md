# M37. The overseer reads the journal

DESIGN §35. Needs M36's measurement, with the disagreements that were the derivation's fixed, and M48's second stage,
passed its check. This is M30's cut, taken from the journal rather than a probe, and it is where the trust model gains
its first code checks on what the overseer claims. The overseer acts through canopy's tools (§27), so every claim below
is a field of `canopy_dispatch` or `canopy_ticket-set`, not a flag.

- The state block carries the observations, after the fixed sections (M34's order): every listed ticket and every
  ticket the query returned, marked a candidate or not in code from its observed labels and state, a non-candidate by
  key and why with none of its text; per candidate, its title, state, labels, blockers, its body until its first unit,
  and the comments past its comment cursor (id, author, time, body, and whether the author is an authorized replier and
  whether the comment is a worker's, both decided in code); per unit, its PR (state, head, base, draft, mergeable),
  each named check at the head, and the reviews and review comments past its review cursor (author, trusted or not,
  decided in code, body); the rows of §7 the derivation found holding for each subject; and the tracker query's and
  the review query's results as their sources last read them whole. Each subject is `fresh`, `stale` (past
  `connect.max_age_minutes`, naming what), or `unobserved` (no source covers it). Bounded text, cut as §30 cuts it, at
  most a fixed number of new items per subject with the rest counted, labeled by source and author in code. The `vcs`
  request also names the PRs review requests wait on.
- The prompt's procedure drops its reads: no tracker search, no ticket or PR reads, no mirror, no provider skill. An
  MCP call is allowed only for a subject the block marks `stale` or `unobserved`; M39 removes that too. The duties
  check (§6) owes `canopy_queried` only on a tick whose query no source read.
- Claims become references to observations, checked in code before §8's other guards: `canopy_dispatch`'s `label` is
  refused `unauthorized` unless the tracker source observed that label on the ticket (D051 gains a code check before
  the worker's own); a `resume` for `reply` must carry a cursor to a comment by an authorized replier that is not a
  worker's, or to an operator message; a `resume` for `review` must cover an item by a trusted reviewer, or the canopy
  review it names when `canopy:review` is trusted, and another reviewer's item only with an operator message after it
  (D089's revisit; §32's approval stays the gate under feedback plans); every cursor must name an observed item and
  pass none the block left out, else `unobserved`. A dispatch is refused `stale` while a public ticket, a stacked
  dispatch's blocker's PR, or the PR of a unit a `resume` names is stale. A private ticket, a chore, a review, and an
  unobserved subject are not refused. Principle 1's "re-read before any action that matters" becomes "observed within
  `connect.max_age_minutes`, or no dispatch".
- Cursors become journal numbers: each comment, review, review comment, and check run takes one when first observed
  and keeps it across reads, and a canopy review run takes one when it ends, so the `review` cursor's time form (§7)
  goes. Existing cursors are converted in the migration, each to the number of the item it names, a `review` time to
  the newest item observed at or before it. CI is observed by head sha, context, and run id, so a re-run at the same
  head is observed, as resolving a held check needs (M35, 2026-10-13 F16); a `resume` for `ci` alone is refused
  `handled` unless it has a failure at a head and context with no failure behind the cursor, so a re-run that went red
  to red starts nothing (PRIOR_ART).
- The `mirror` tool is retired (M48 retired the heredoc, D081): each comment the tracker source observes is recorded
  once in its ticket's conversation, source `tracker` or `worker`, and the `mirror` cursor, the prompt's section, and
  the tool go.
- TRUST_MODEL T1 (labels, repliers, and reviewers checked in code; the overseer's MCP narrowed to stale and unobserved
  subjects; the mirror's residual gone), T2 (`canopy-connect-jira`'s credentials), T7 (`connect.*` private; the
  widened query's residual closed); DESIGN §4 principle 1, §6, §7, §8, §17, §22, §27, §30, with §35 cut to what is
  left; D003 edited in place, D051 and D089 gaining their code checks.
- Tests with the fakes: the state block over journals written by hand, a snapshot each for a candidate with new
  comments, a non-candidate the query returned (no text), a unit with checks and mixed reviewers, and a stale and an
  unobserved subject; each refusal above (`unauthorized` for a label not observed, a reply by someone not authorized
  or a worker, untrusted review items without an operator message; `unobserved` for a cursor naming nothing observed
  or passing an item left out; `stale` for each subject; `handled` for a red-to-red re-run) through both the tool and
  its command, and none for a private ticket, a chore, or an unobserved subject; a held check's re-run observed at the
  same head; a review submitted after a later comment still new; observed comments in the conversation once each,
  marked by source, and in a private worker's prompt as data; a tick whose query a source read closes `ok` without
  `canopy_queried`; the cursor migration over a journal with each old form.

Accept: the tests above pass, and the design (§35) is folded into the sections it names. Live: a re-measurement
(MEASUREMENTS) with tool-result tokens per tick at a tenth of the first day's median (about 14k), no MCP call on a tick
whose observations are fresh, and no action missed over a day, checked against the derivation as in M36.

Status: in progress. Designed 2026-10-21 (DESIGN §35); building waits on M36's measurement and M48's stage 2 check. The
design settles what the sketch left open: a ticket the query returned that is not a candidate reaches the overseer by
key only, closing TRUST_MODEL T7's widened-query residual; a candidate's body is in the block until its first unit; the
query's result replaces the query, so `canopy_queried` is owed only when no source read it; a subject no source covers
is `unobserved`, keeps today's live read and claims, and is never refused `stale`; a stale subject's live read can mark
done or raise attention, never dispatch; a `reply` or `review` claim is the cursor the dispatch carries, and an
untrusted review item needs an operator message after it, carried in the same dispatch; a cursor never passes an item
the block left out; the journal number is taken at first observation, so a pending review submitted late is still new;
a `ci` resume is refused `handled` on a red-to-red re-run at the same head, while a held check, never handled, stays
new; observed comments go into the conversation in code, every one; and the `vcs` request names review requests' PRs.
Open for the operator: whether a tracker with no connector keeps the live-read procedure, with its provider skill,
mirror, and label claim, or a `tracker` source is required (recommended: required; the two shipped cover the
operator's trackers, and the contract is a page of Python for another); and how many new items a subject shows before
the rest are counted.
