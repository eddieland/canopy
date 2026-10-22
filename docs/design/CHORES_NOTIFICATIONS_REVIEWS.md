# Chores, notifications, and reviews

Part of the canopy design, normative like all of it: recurring chores, notifications away from the terminal, and
adversarial reviews of PRs. Sections are numbered across the whole design; the [README](README.md) has the map.
Previous: [Trackers and workspaces](WORKSPACES.md). Next: [Conversations](CONVERSATIONS.md).

- [19. Chores](#19-chores)
- [20. Notifications](#20-notifications)
- [21. Reviews](#21-reviews)

## 19. Chores

A chore is recurring work the operator defines and the overseer delegates: an agent run about no queue ticket, with no
worktree and no push, that reports findings to the attention list (for example, a build-health check over CI, other
people's PRs included). The operator's config defines the chore and its fastest recurrence; the overseer decides when;
guards in code hold the limits (§4). A chore is neither a cron job, which has no guards, journal, or judgment, nor a
check the overseer runs inline.

### Definition

Chores are private (§12); one in a workspace file is a config error (TRUST_MODEL T7). A chore names the operator's
prompt file, and these keys turn behavior on:

- `every_minutes` is the shortest time between two run starts: a guard, not a schedule. `days`, `hours`, and `timezone`
  say when a run may start, checked in code.
- `when` is plain language for the overseer: when a run is worth it, pointless, or urgent. Being operator-written, it is
  an instruction; nothing a chore reads is.
- `max_findings` caps the findings a run lists, so the few that matter most reach the operator; the rest are counted.
- `cwd` defaults to a private directory per chore; the shadowing check (§13) covers it and every directory above it.
  `workspaces` (§18) limits where a chore runs.

`capacity.max_chores` caps chore runs at once, apart from `max_workers`.

`canopy chore install NAME` sets up one of the example chores canopy ships in a workspace: its prompt, and the agent it
comes with if any, in the state directory, which its table in the private file names. They stay as installed when
canopy is upgraded. The command owns them, so installing again replaces them whole with the shipped ones, and leaves
every other line of the file as it was or writes nothing.

canopy ships `canopy-chore` (§13): no edits, no subagents, no bash, one tool of canopy's, which reads its own chore's
history, and no MCP write tools where the runtime can deny them by name. A chore using the operator's own read-only
tools gets its own copy, in the operator's runtime config (never the repository's), with bash allowed for exactly those
tools. Their credentials are the tools' (§4, principle 5); canopy never sees them and knows nothing of any CI system.
The example chores that read canopy's own journal come with such a copy, allowing exactly the read-only canopy commands
its prompt runs.

### Delegation

The state block lists each chore with a `when`, when it is next due, whether it is running, its latest run, and its
open findings. Each tick the overseer runs each due chore or records why it waits. A chore with no `when` needs no
judgment, so the harness runs it when due, after the overseer, with no context (§37), and the overseer's `chore run`
or `chore wait` about one is refused `decided`. Findings inform only decisions about
the chore: chores never cause or prevent a dispatch (Open). With no chores, or `capacity.max_chores = 0`, nothing about
chores reaches the overseer.

Only a tick starts a chore (D020). The harness refuses, and records the refusal, a chore not configured for this
workspace, one already running, one whose latest run started less than `every_minutes` ago however it ended, one outside
its hours, and one past `max_chores`. A dry run checks the same guards and starts nothing (D036).

### Runs

A chore run starts detached as a worker does (§8 step 4), in `cwd`, with its timeout; no lease, branch, or push. Its log
and prompt live outside its working directory, so it cannot read back or rewrite them (§24). The prompt is the
operator's file plus a section canopy generates, which the file cannot drop: the overseer's context, the operator's
notes and notice to workers (§8), the latest run and open findings, and the result contract. Reconcile (§6 step 3)
treats chore runs as worker runs; a decision names a ticket or a chore, never both.

Result contract, one JSON line, last line of the agent's text (§13), validated with pydantic (D026); anything else is
`unknown`, with no findings recorded:

```json
{"status":"ok|failed","summary":"a paragraph, line breaks sparingly",
 "findings":[{"id":"flaky/checkout-service/test_retry","title":"one line","detail":"a paragraph","link":"https://..."}],
 "more_findings":0}
```

`ok` means the check ran, and no findings means nothing needs a human; `failed`, that it could not check. A finding's
`id` is stable across runs for the same problem. Text is bounded, a `link` is a plain `https://` URL, and
`more_findings` only counts what was left out. An optional field that is null or empty is read as left out.

### History

`canopy chore history` lists a chore's runs, or prints one whole, and records nothing. A chore's run reads them through
its tool, `canopy_chore_history`, which takes the command's bounds and says what it prints (§27); a definition of the
operator's own allows that tool by name. A chore's run reads its own chore's runs only; the overseer, workers, and
reviews are refused, and the operator reads any. What it prints is what runs reported, as data. Rejected: more runs in
the prompt, a cost every run pays for what few use.

### The operator's part

A note (`canopy reply` to the chore, or the web UI) is how the operator answers a finding without editing the prompt
file. Every later run carries the latest notes, a later one winning. They are the operator's words, so they are
instructions; the overseer's context is not. Notes reach neither the overseer nor the attention list.

Dismissing a finding keeps it off the attention list while the chore goes on reporting it. It is spent once an `ok` run
leaves the id out, so a recurrence is listed and notified again. It changes only what the operator is shown; to stop the
chore reporting it, write a note.

Trying a chore is a real run through the same code as a delegated one, recorded with no tick, so its findings become the
open ones and the next run waits from it. No time or capacity guard applies, but a chore already running is refused.

Dismissing and trying are refused inside a run, and the overseer's bash cannot unset `CANOPY_TICK_ID`: the overseer and
agents can neither hide a finding from the operator nor try a chore.

### Findings on the attention list

Open findings are the latest `ok` run's, listed per chore as `chore:<name>` and notified per §14 by chore and finding
id; a non-`ok` run leaves them standing and raises `chore_failed`. The latest `more_findings` is shown beside them, so a
cut list never reads as the whole. Deleting a chore's table resolves its items.

### Trust model changes

Chores touch T1 (findings are data everywhere), T3 (`every_minutes`, one run at a time, and `max_chores` are controls in
code), T6 (a chore's only output is its result line, and its residual is listed there), and T7 (chores and their keys
are private). Under §7, the operator answers for any tool a chore's definition allows; canopy assumes chore tools only
read.

### Open

- Whether a chore should ever write (D010 kept that out). Likely first: a ticket for a finding, with no queue label.
- Whether findings should inform ticket decisions: only to hold work back or raise attention, and opt-in per chore.

## 20. Notifications

Notifications reach the operator away from the terminal (REQUIREMENTS N2; rationale in D035). A destination is a
**sink**, a command that reads one message on stdin. canopy ships a desktop sink and a Slack sink; others are the
operator's programs. This generalizes `notify.cmd` (§14), which stays and behaves as it did.

### Sinks

- Sinks are private (§12), like every `notify.*` key (TRUST_MODEL T7). At most 5, since each can hold the tick lock.
- `cmd` follows `notify.cmd`'s rules (§12): argv, no shell. Exit 0 means delivered; anything else, timeout included,
  means retry next tick.
- Each sink sets its `format` (`json` or `text`), the event groups it takes, and optional batching and digest (below).
- `canopy notify test [SINK]` sends a test message and changes no delivery state. It refuses when `CANOPY_TICK_ID` or
  `CANOPY_RUN_ID` is set, so no agent can page.
- `notify.cmd` is shorthand for a `text` sink taking attention alone, so switching re-notifies nothing. Setting both
  is a config error.

### Events

A closed set, written by the harness from the journal, in groups: `attention` (an item opened or resolved), `runs` (a
worker started or ended, a plan proposed or approved by its planner, §25, follow-ups filed, §18), `chores` (§19),
`reviews` (§21), `tasks` (a task's run ended, §36), and `loop` (ticks failing and recovering, a sink failing). Each
carries only bounded fields, its text on one line. No plan event carries the plan's text. `run.ended` carries a
`blocked` run's question, since the needs-human label is not an attention item.

Attention is a diff of state per sink (§14): each sink hears of each open item once, and a sink that was down gets the
net change. The other kinds are point events in an outbox, written in the same transaction as the fact they report,
with a cursor per sink. A failing streak is reported once.

### Delivery

§6 step 7, after `attention.md` is written, each sink in turn gets one message: its attention diff, its new events, and
a digest if one is due. Only exit 0 records what the sink was told; the third failure in a row records
`loop.sink_failing`. A message is bounded, the rest counted with a pointer to `attention.md` and `canopy status`. A new
sink starts with no backlog. Sinks run under the tick lock, so a hung sink delays the next tick by its timeout.

### Batching

A sink with `batch_minutes` sends at most one message per window, so a busy loop is not a message every few minutes.
A sink quiet through the window sends at once. Urgent goes at once, with everything held: a new attention item, a
`blocked` run's question, a proposed plan, and the loop or a sink failing. Holding does not wake the loop, and a failed
delivery starts no window.

### Digest

A sink with `digest_every_minutes` gets a summary every interval: ticks, runs, what the runs that started in it cost by
kind (§11), the open attention list, and the workers running. It is sent even when nothing happened: a missing digest
shows ticks stopped, which canopy cannot report itself. No model writes it; a report needing judgment is a chore (§19).
With `digest_min_usd`, a due digest waits until the runs since the last one cost at least that much: the sink hears of
spend, at most once an interval, and gives up the heartbeat.

### Formats

`text` is lines for a person; attention alone is exactly §14's message, so `notify.cmd` output is unchanged. `json` is
one object holding the same diff, events, and digest as fields, each ticket key with its title (§13), and the text
too. Its `version` changes only on an incompatible change; sinks ignore unknown fields. A tick the loop runs while
serving the web UI (§22) gives each item and event its page there, at `serve.url` if set; `text` links nothing.

Presentation is the sink's. The fields are the contract: a sink that can show more than lines builds its own message
from them, as the Slack sink does with Block Kit, and the text is canopy's one rendering, for sinks that forward a
string. So the harness never learns a channel's markup, and a new event kind needs fields, not only a line.

### The desktop sink

`canopy-notify-desktop` ships inside canopy (D035) and runs only as a configured sink. It passes title and body to
`notify-send` or a fixed `osascript` script as arguments, never as a shell command or script, so agent or org-member
text runs nothing.

### The Slack sink

`canopy-notify-slack` is its own program (§5), importing nothing from canopy.

- It posts to an incoming webhook, or with `--channel` through a bot token. The URL or token is read from a file that
  must be the operator's, unreadable by group and others; it is never in canopy's config, argv, journal, or logs. A
  token must be a bot token, since a user token acts as the operator with all its scopes. A post counts as delivered
  only when Slack's reply says `ok`.
- With `--threads` it threads posts by ticket or PR, a new thread each day, each started by a post of the same shape
  naming what it is about, with every item a reply under it; chores' results stay in the channel. The threads are the
  sink's own state, never in canopy's journal; a retry after a partial delivery posts only the rest.
- Journal text is escaped for Slack markup and every text object is `verbatim`, so no `@here`, mention, or disguised
  link gets through. A web UI page canopy sent is linked under the sink's own word, `open`, only if it is a plain URL.

Lint keeps the network out of the harness, as D015 keeps processes in one module: `urllib.request`, `http.client`, and
`socket` are banned everywhere in `src/canopy`, and so is any import of the Slack sink.

### Two-way, later

Not built. A listener must follow TRUST_MODEL T8 (D055), so Slack's Events API, which needs inbound internet access,
stays out. Today an authorized reply on the ticket resumes the worker: Slack is the pager, the ticket the conversation.
Replies read in Slack would need each ticket's thread, Slack ids among authorized repliers, and a T1 change (§22).

### Trust model changes

- T2: the harness makes no outbound call except through configured commands and reads no token. The Slack sink does
  both, but runs only as a configured sink, and lint keeps network modules and the sink out of the harness.
- T6: notifications carry agent- and org-member-written text off the machine. Controls: only bounded fields; Slack
  escaping. Residual: a steered agent picks text shown in the channel, and a link can carry data.
- §7: point a sink only where the audience may read what it quotes; keep the secret file the operator's alone, and
  give a bot token only `chat:write`. Channel readers see what the loop does but cannot steer it.

### Open

- Routing finer than groups; digests at fixed times of day; reminders for items open long.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

A review is an adversarial read of one PR at one commit by a fresh agent run, with no transcript of the author's run,
told to assume the change is wrong until the code shows otherwise. It reports a verdict and its findings to canopy's
journal, and posts nothing: no comment on the PR or the ticket, no GitHub review (D114), but what the operator
publishes of one on a PR the loop does not own, word for word (§34). It never approves, requests changes, pushes, or
merges. Human review stays the gate (§3). Three kinds of PR get reviews, none needing a ticket: the
loop's own, with `review.agent_prs` on, once checks pass and before a human is asked, findings going back to a worker
through `resume`; PRs matching `review.query`, reviewed and nothing else, never pushed to, fixed, or ticketed; and PRs
the operator asks for one at a time (Review requests), reviewed as a query match is.

Why nothing is posted: a review on the PR speaks for the operator to everyone, and an adversarial reader is wrong often
enough that the operator wants its findings first; kept in the journal, it needs no write tool and cannot be forged. Its
verdict leaves the machine only as a notification (§20), so no automation can let a PR skip a human reviewer on it; that
waits on a bot identity (ROADMAP, deferred).

Every review key is private (§12) except `policy.max_reviews_per_pr` and §34's `policy.max_revisions_per_draft`,
shared limits the repository may only tighten (TRUST_MODEL T7). With no source of reviews or no review capacity,
nothing about reviews reaches the overseer and no review starts; a note asking a revision is a source of one (§34).
`review.query` authorizes, unlike `tracker.query` (§17): without an author filter it reviews other
people's PRs in the operator's name, which is the operator's choice (TRUST_MODEL §7). `review.low_impact` says in plain
language which changes the reviewer may call `low`; without it, none. Reviews touch TRUST_MODEL T1 (what the reviewer
writes is data; `review.query` and requests authorize), T3 (review limits are controls in code), T4 (nothing runs from
the checkout), T6 (no write tool), T7, T8 (requests are web channel writes), and §6 (never push to a PR the loop only
reviews).

### Running a review

Only a tick starts a review (D020). The PR's URL is an opaque string the harness never parses, and only a review that
names its ticket (an `own` review) can send findings to a worker. The harness refuses, and records the refusal, a review
while reviews are off, of a PR in no known repository, naming a ticket that did not open the PR, of a PR whose review or
ticket's worker is running, of a commit with a `done` review (in the same persona, when the operator chose several for
the PR, §31), or past the per-PR limit (runs however they ended, plus
any the operator grants, §22), the daily limit, review capacity, or `max_workers`, which counts reviews. A dry run
checks the same guards and starts nothing (D036).

The review starts detached, as a worker does (§8 step 4), checks out the commit detached in a leased slot, and deletes
every tracked symlink that resolves outside the checkout. The reviewer runs in a private directory of canopy's holding a
link to the checkout, **not in the checkout**, so the runtime loads no configuration from the PR. Afterwards, on a
signal too, the slot is returned (§8 step 6). It can be sandboxed (§24). canopy ships `canopy-reviewer` in the
definitions directory (§13), not the repository's (TRUST_MODEL T7): no edits, no subagents, no bash, reads only inside
the checkout and, through canopy's read-only git tools, its history (§27), and MCP read tools only, every tool that
writes denied by name. A review that runs the PR's tests uses the
operator's own copy (§19), so runs the PR's code (§7).

The prompt carries the notice to workers (§8) and asks only for what the diff itself gets wrong, so a `resume` is never
sent to fix code its PR did not touch. Rejected: a second agent verifying each finding, doubling a review's spend.

It also carries the PR's latest `done` review, its summary and the findings the operator did not dismiss, as data to
check at the new commit: what still holds is reported again, since each review's result stands alone, and the review
still reads the whole change. Rejected: notes reviewers write for later reviews, which would tell the next one what to
skip.

Result contract, the last line of the reviewer's text (§13), validated (D026); anything else is `unknown`:

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high",
 "summary":"a paragraph, line breaks sparingly","pr_title":"the PR's title as it stands",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line","detail":"what and why"}]}
```

`verdict` is `findings` exactly when there are findings, and `low` without `review.low_impact` is recorded as `normal`.
`pr_title` is the PR author's text, for display only (§8).

### The overseer's part

The state block carries review limits, running reviews, recent outcomes, and open requests. With `agent_prs` on, §7
gains two phases before `green_unreviewed`: `review_pending`, checks passing with no approval and no `done` review of
the head, under the per-PR limit, where the overseer starts a review; and `review_findings`, where it dispatches a
`resume` with that review's undismissed findings or records `needs_author`. Findings are `review_findings` only when
`trust.trusted_reviewers` lists `canopy:review`; otherwise they are `untrusted_review` and wait for the operator (§7,
D089). A clean review, or a PR at its limit, moves on to `green_unreviewed`; a review never counts toward
`changes_requested`. A `resume` carries only undismissed findings of its ticket's own `done` review, and a prompt
override that drops them fails to render. For other PRs, the overseer reviews each whose head has no `done` review or
records why it waits, and decides nothing else about them. `review_failed` and `review_limit` are attention items;
findings are not. Under `[personas] reviewers` (§31) a head is reviewed once each persona has a `done` review of it:
until then the state block names the personas it is owed, and after, it shows the head's reviews as one, and a
`resume` for one of them carries the undismissed findings of each.

### Review requests

The operator asks for one review of a coworker's PR at its head; asking again after a push reviews the new head. A
request is a journal fact, at most one open per PR, ended by a `done` review, by the overseer finding the PR merged,
closed, or in no cloned repository, or by the operator. A request may carry the operator's notes, which its reviewer's
prompt carries; a prompt override that drops them fails to render. A request may name several personas (§31): one
`canopy review run` starts a review in each still owed one, side by side, each counting against the per-PR limit and
keeping its own draft, and the request ends once each has a `done` review. A requested review is the overseer's first
start of a tick, ahead of every worker and every other review, since the operator asked for it by hand. Starting work on
a coworker's PR is refused, so a review never turns into work on someone else's branch. Requests are refused inside a
run: a request authorizes a review as `review.query` does, so an agent steered by a PR's text could otherwise aim the
operator's spend at any PR (T1).

### Reading reviews

Reviews are read from the journal only, apart from worker runs; a review's text is shown as data, made printable.

### Dismissing and sending findings

A dismissed finding stays listed but leaves what a `resume` hands the worker. A review whose findings are all dismissed
moves on as a clean one. Sending findings is the operator's go-ahead on an `own` review's findings while its ticket has
the PR: an operator message on the ticket names them by number, never quoting them, since the reviewer's text is data
(T1) and the message an instruction. The next tick dispatches a `resume` with them (§7, D089), whether or not
`canopy:review` is trusted. A dismissed finding, or one on a PR not the loop's own, cannot be sent. Both are refused
inside a run, so no agent can hold a finding back from a worker or start work in the operator's name.

### The diff

Since the slot goes with the review and the web UI cannot ask GitHub (principle 5), the review keeps the diff of exactly
the commit the reviewer read, best effort and readable only by the operator. Diff drivers and textconv are off, since a
commit's `.gitattributes` can name them (D107). It is the PR's text: rendered as text, never served as a file. It runs
from the commit's merge base with the branch the PR merges into, as the vcs source last read the PR, and the
reviewer's prompt names that branch; a PR it has not read falls back to the pool's base branch. For this, the vcs
source reads a requested PR from the tick after its request.

### Open

- How a finding is followed from one commit's review to the next, so a dismissal or a send could outlast its run.
- Whether OpenCode confines the reviewer to its checkout link. The opt-in reviewer canary settles it; if not, the
  reviewer reads the PR only through MCP.
