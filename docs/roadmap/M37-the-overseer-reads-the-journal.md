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

Status: in progress. Designed 2026-10-21 (DESIGN §35). Started 2026-10-22 ahead of M36's measurement, at the operator's
word, since M36's connectors and derivation are built; nothing here needs M48's MCP tools, whose stage 2 was not merged,
so the claims below stay fields of the `canopy` commands until it is. Built (2026-10-22): the first bullet's
observations in the state block, after its fixed sections (`loop/observations.py`), and the second bullet's reads for a
fresh subject: the prompt decides a subject marked `fresh` from the block, takes the query's and the review query's
fresh results instead of running them, mirrors a fresh comment from the block, and calls MCP only about a subject
`stale` or `unobserved`; snapshot tests over hand-written journals for a candidate with new comments, a non-candidate
the query returned, a unit with checks and mixed reviewers, and stale and unobserved subjects. The `vcs` request already
names the PRs review requests wait on (M36). Chosen conservatively, for the operator to change: a subject shows at most
ten new items (`MAX_NEW_ITEMS`); a tracker with no connector keeps today's live reads, its tickets `unobserved`, leaving
"required" open; a candidate's comments start past the earlier of its `comment` and `mirror` cursors while the mirror
stays; a candidate canopy did not hold when its source last read it is stale, since its comments were not recorded; a
cursor naming no observed comment is passed by larger numeric ids; each person's latest verdict is shown, since an
approval before the `review` cursor still counts; and a stale or unobserved ticket shows only what is old, never its
stale text. Built (2026-10-22): the third bullet's claims on `canopy dispatch`, checked in code before §8's other guards
(`loop/claims.py`), through the command and the tool alike: `unauthorized` for a label not observed, a reply not by an
authorized replier or by a worker, and review feedback covered with no trusted item or no operator message after an
untrusted one; `unobserved` for a cursor naming nothing observed or passing what the block left out; `stale` for the
ticket, a named unit's PR, and a stacked dispatch's blocker's PR; none for a private ticket or an unobserved subject.
Chosen conservatively: cursors are checked as they are today, a `review` cursor naming an item by its time to the
second; a ticket the query found this tick is stale until the next read records its comments, so its first dispatch
waits a tick, as the block already said; the prompt is unchanged, its refusals section covering the new codes.
Built (2026-10-22): the duties check owing `canopy queried` only on a tick whose query no source read. When the query is
due and the block shows it `fresh`, the harness records its result before the overseer runs as `canopy queried` would,
touching each ticket into the journal, and each is owed a decision; the prompt neither runs nor records such a query.
Chosen conservatively: a fresh read is any within `connect.max_age_minutes`, the poll's included, so the harness
records what the block shows; a query not due is not recorded though a source read it, so `query_every_minutes` still
spaces out new tickets.
Built (2026-10-22): the cursor check on `canopy ticket set`, through the command and the tool alike, in a tick
(`claims.check_cursors`): `unobserved` for a cursor naming nothing observed or passing what the block left out; none
for a private ticket or an unobserved subject. Chosen conservatively: it is never refused `stale`, since it starts
nothing, but a stale subject's cursors move no further than what they already passed, since the block shows none of its
items; a unit with no PR is unobserved; a `review` cursor may name the end of any canopy review run of the PR; and the
operator's own `canopy ticket set`, outside a tick, is not checked.
Built (2026-10-22): `handled`, on the `ci` cursor as it is: each completed check run a source observes is kept by its
run id across reads (`observed_check_runs`), so a re-run at the same head is told from the run it repeats, and a
`resume` for `ci` alone is refused `handled` when every failure at the head is at or behind the cursor or repeats, at
the same head and context, one that is; tests through the command and the tool, and of a held check's re-run observed at
the same head. Chosen conservatively, for the operator to change: a failure with no run (a commit status) is new; a `ci`
cursor empty or not a number refuses nothing, nor does a head whose only failures are `human_checks` or that has none;
and the prompt has the overseer record `flaky_rerun` on a `handled` refusal, a new head or an operator message starting
the next.
Built (2026-10-24): the fourth bullet's mirror retired. Each comment the tracker source observes is recorded in its
ticket's conversation in code (`conversation.record_comment`, which another source's comments can reuse), once per ticket
and comment id, in the transaction that first records its observation and with the same text, source `worker` when it
carries the workers' marks (D069), else `tracker`; the `mirror` tool and command, the prompt's section and duty, the
state block's `mirror` and `mirror` cursor, and the per-tick bound go, and the block's comments start past the `comment`
cursor alone. Migration 0095 records each comment observed before it that the overseer had not mirrored, at the time it
was observed. Tests with the fakes: observed comments in the conversation once each across reads, marked by source, an
edit not followed, in a private worker's prompt as data and authorizing nothing, a mirrored comment kept, and the
migration. Chosen conservatively: a dry run records the comment, as it records the observation and as the mirror did;
a comment is recorded for every ticket the source reads, a candidate or not, private or public, since only the
operator's views and a private ticket's own worker read the conversation; a comment the overseer mirrored keeps its
message, text, and source, found by its comment id, so the mirror's residual stays for those alone; an edit after the
first read is not followed; the mirror cursor's column stays, unread, since no migration drops a column; and a tracker
with no connector records no comment, since its tool is gone.
Built (2026-10-24): `observed_check_runs` pruned by M47's pass, a run going after `journal_days` once a read shows its
PR at another head, merged, or closed; one of a PR no read recorded stays.
Built (2026-10-24): journal-numbered cursors. Each comment, review, review comment, and completed check run takes the
next number in `item_numbers` when a source first observes it, and keeps it across reads that replace its row; a canopy
review run takes one when it ends. The `comment`, `review`, and `ci` cursors are those numbers, in new columns, and
"newer" is a larger number everywhere the derivation, the block, and the claims read it; the block shows each item's
`number`, the latest review run's in place of `reviewed_at`, and what each cursor names (`cursor_items`), so a live read
of a stale subject can tell what it passed; the `review` cursor's time form is gone. Migration 0098 numbers what the
journal holds in the order each old cursor read it and converts each cursor to the number of the item it names, a
`review` time to the newest item at or before it to the second. Tests with the fakes: the migration over a journal with
each old form, a review submitted after a later comment still new, and the claims and derivation on numbers.
Chosen conservatively: a check run is numbered once observed completed, not while it runs, since only a failure is
handed to a worker; a ticket no tracker source observes keeps its `comment` cursor as the tracker's id
(`last_comment_id`), since its comments have no numbers, until "required" is settled; a cursor whose old form passed
nothing observed becomes 0, so a set `ci` cursor still passes a commit status, and one in no old form the readers read
stays empty; the old `review` and `ci` columns stay, unread; `item_numbers` is not pruned, its rows being small and a
pruned number able to come back as a new one.
Built (2026-10-24): the design folded into the sections it names. What the overseer is shown, and how fresh, is §30's;
the claims and their refusals, and cursors as journal numbers, §7's, with §8's guards pointing there; §4 principle 1,
§5's overseer, §10, §17, §22, and §27 say the overseer reads the observations and the harness checks them; §35 is cut
to its open questions. TRUST_MODEL T1, T2 (`canopy-connect-jira`), and T7 (`connect.*` private, the widened query's
residual left to "required") and D003 record what is built; D051 and D089 already had their code checks.
Left: the live re-measurement.
Open for the operator: whether a tracker with no connector keeps the live-read procedure or a `tracker` source is
required (recommended: required), and how many new items a subject shows before the rest are counted.
