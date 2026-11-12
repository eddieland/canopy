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
- `model` runs the chore on a model of its own rather than `runtime.models.chore` (§13, Each agent's model), through
  a copy of `canopy-chore` made for it, `canopy-chore-<name>`, since one definition holds one model. Its command must
  run `canopy-chore`; a chore with an agent of the operator's own sets the model in that agent's definition.

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

The state block lists each chore with a `when`, when it is next due, whether it is running, and its latest run; a due
one's with its summary, and its open findings, which a `when` may decide by. Each tick the overseer runs each due
chore or records why it waits. A chore with no `when` needs no judgment, so the harness runs it when due, after the
overseer, with no context (§37), and the overseer's `chore run` or `chore wait` about one is refused `decided`.
Findings inform only decisions about the chore: chores never cause or prevent a dispatch (Open). With no chores, or
`capacity.max_chores = 0`, nothing about chores reaches the overseer.

Only a tick starts a chore (D020). The harness refuses, and records the refusal, a chore not configured for this
workspace, one already running, one whose latest run started less than `every_minutes` ago however it ended, one outside
its hours, and one past `max_chores`. A dry run checks the same guards and starts nothing (D036).

### Runs

A chore run starts detached as a worker does (§8 step 4), in `cwd`, with its timeout; no lease, branch, or push. Its log
and prompt live outside its working directory, so it cannot read back or rewrite them (§24). The prompt is the
operator's file plus a section canopy generates, which the file cannot drop: the overseer's context, the operator's
notes and notice to workers (§8), the latest run and open findings, and the result contract. Reconcile (§6 step 3)
treats chore runs as worker runs; a decision names a ticket or a chore, never both.

Result contract, the arguments of the chore agent's `result` call, or the last line of the text of a chore that runs
the operator's own command (§13), validated with pydantic (D026); anything else is `unknown`, with no findings recorded:

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
code), T6 (a chore's only output is its result, and its residual is listed there), and T7 (chores and their keys
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
worker started or ended, a plan proposed or approved by its planner, §25, an epic's plan changed under its members,
§43, follow-ups filed, §18, a check left as flaky, §23), `chores` (§19),
`reviews` (§21), `tasks` (a task's run ended, §36), `replies` (a reply read from Slack recorded or refused, below),
and `loop` (ticks failing and recovering, a sink failing, the month's spend reaching its budget or one of its alerts,
and each forced push canopy makes to kick a flaky check, §23). Each carries only bounded fields, its text on one
line. No plan event carries the plan's text. `run.ended` carries a `blocked` run's question, since the needs-human
label is not an attention item.

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
`blocked` run's question, a proposed plan, a kick's forced push, and the loop or a sink failing. Holding does not wake
the loop, and a failed delivery starts no window.

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
  link gets through. A web UI page canopy sent is linked under the sink's own word, `open`, only if it is a plain URL;
  a GitHub PR's link shows only the `owner/repo#N` its own URL spells.

Lint keeps the network out of the harness, as D015 keeps processes in one module: `urllib.request`, `http.client`, and
`socket` are banned everywhere in `src/canopy`, and so is any import of the Slack sink, of `canopy-http`, or of httpx2.

### Replies from Slack

Lightly two-way, with no listener: a listener must follow TRUST_MODEL T8 (D055), so Slack's Events API, which needs
inbound internet access, stays out. Reading a thread is an outbound call, as posting is, so a `slack` source (§30)
reads the replies in the sink's ticket threads on the loop's polls, and a reply from a Slack id the operator listed is
their message on the ticket, as `canopy reply` records one (§22). The sink keeps each ticket's threads a week, so a
reply in yesterday's still reaches it. A ticket with no thread is answered by mentioning canopy's bot in the channel,
then the ticket's key: `@canopy PROJ-123 use the staging config`. Sinks that take `replies` hear what came of it, so
the sink acknowledges a mention in the ticket's thread and answers a refused reply under the operator's own message,
once each; a reply in a thread needs no acknowledgement. Only replies on tickets: plans, starts, and the other verbs
stay in canopy.

### Trust model changes

- T2: the harness makes no outbound call except through configured commands, and its opt-in OTLP export of spans
  and metrics (D132), and reads no token. The Slack sink does
  both, but runs only as a configured sink, and lint keeps network modules and the sink out of the harness.
- T6: notifications carry agent- and org-member-written text off the machine. Controls: only bounded fields; Slack
  escaping. Residual: a steered agent picks text shown in the channel, and a link can carry data.
- §7: point a sink only where the audience may read what it quotes; keep the secret file the operator's alone, and
  give a bot token only `chat:write`, and a `slack` source's one history scope. Channel readers see what the loop
  does; only the Slack ids a `slack` source lists steer it, by replying (T1).

### Open

- Routing finer than groups; digests at fixed times of day; reminders for items open long.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

A review is an adversarial read of one PR at one commit by a fresh agent run, without the author's transcript, told to
assume the change is wrong until the code shows otherwise. It reports a verdict and findings to canopy's journal, posts
nothing (D114) but what the operator publishes of one on a PR the loop does not own (§34), and never approves, requests
changes, pushes, or merges: human review stays the gate (§3). It reviews, none needing a ticket, the loop's own PRs
with `review.agent_prs` on, once checks pass and before a human is asked, sending findings to a worker by `resume`; PRs
matching `review.query`; and PRs the operator asks for (Review requests); those two reviewed and nothing else.

Why nothing is posted: a review on the PR speaks for the operator to everyone, and an adversarial reader is wrong often
enough that the operator wants its findings first; kept in the journal, it needs no write tool and cannot be forged.
Its text is shown only as data, and its verdict leaves the machine only as a notification (§20), so no automation can
let a PR skip a human reviewer. Every review key is private (§12) but `policy.max_reviews_per_pr` and §34's
`policy.max_revisions_per_draft`, shared limits the repository may only tighten (T7). With no source of reviews or no
review capacity, nothing about reviews reaches the overseer. `review.query` authorizes, unlike `tracker.query` (§17):
without an author filter it reviews others' PRs in the operator's name (TRUST_MODEL §7).

### Running a review

Only a tick starts a review (D020), but for an eval (Scoring the reviewer). The PR's URL is an opaque string the
harness never parses, and only an `own` review, which names its ticket, can send findings to a worker. The harness
refuses, and records, a review while reviews are off, of a PR in no known repository, naming a ticket that did not open
the PR, of a PR whose review or ticket's worker is running, of a commit with a `done` review (per persona, §31), or
past the per-PR limit and grants (§22), the daily limit, review capacity, or `max_workers`, which counts reviews; a
dry run checks the same (D036). With `review.settle_minutes`, a head is reviewed only once it has been the PR's head
that long, so a PR pushed to often is reviewed once it goes quiet.

The state block carries review limits, running reviews, open requests, settling heads, and the recent outcomes of the
PRs the overseer may act on. With `agent_prs` on, §7 puts `review_pending` and `review_findings` (D089) before
`green_unreviewed`, which a clean review or a PR at its limit moves on to; a review never counts toward
`changes_requested`. A `resume` carries only its ticket's own findings neither dismissed nor held, each persona's under
`[personas] reviewers` (§31), and a prompt override that drops them fails to render. Other PRs the overseer only
reviews, or records why one waits. `review_failed` and `review_limit` are attention items; findings are not.

The review checks out the commit detached in a leased slot, returned afterwards even on a signal (§8), with every
tracked symlink that resolves outside it deleted. The reviewer runs in a private directory of canopy's linking to the
checkout, **not in the checkout**, so the runtime loads no configuration from the PR; it can be sandboxed (§24). Its
agent, `canopy-reviewer`, ships in canopy's definitions directory (§13), not the repository's (T7): no edits,
subagents, or bash, reads only inside the checkout and, through read-only git tools, its history (§27), and MCP read
tools only. A review that runs the PR's tests uses the operator's own copy (§19), so runs the PR's code (§7).

The prompt carries the notice to workers (§8) and asks only for what the diff itself gets wrong, so a `resume` is never
sent to fix code its PR did not touch. An `own` review also gets its ticket's approved plan (§25), as data (T1), in a
copy checked against the approval as a worker's is, or none, which its prompt says, if the file changed: a step left
undone or a change no step plans is then a finding like any other. It gets the PR's latest `done` review too, its
undismissed findings with the worker's answers, as data: what still holds and was not declined is reported again.
Rejected: a second agent verifying each finding, doubling spend; notes for later reviews, telling the next what to skip.

Result contract, the arguments of the reviewer's `result` call (§13), validated (D026); anything else is `unknown`:

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high",
 "summary":"a paragraph, line breaks sparingly","body":"what to tell the PR's author beyond the findings, or nothing",
 "pr_title":"the PR's title as it stands",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line","detail":"what and why",
               "rebuts":null}]}
```

`verdict` is `findings` exactly when there are findings, and `impact` is `low` only where `review.low_impact` says in
plain language that it may be. The reviewer judges impact from the PR's text, which can talk it down (T1), so the
harness records `high` a review whose diff touches `.github/workflows/`, or a path the repository's `high_impact_paths`
in the map (§18) adds (T7), and never lowers it; `high` only ranks attention (§14). `pr_title` is the author's text,
for display only (§8); `body` is for the PR's author through a draft (§34).

### Answers and rebuttals

A `resume` handed findings answers each in its result's `review_answers`, `fixed` or `declined` with its reason, kept
only for a `done` review of its own ticket. A declined finding comes back only as a rebuttal naming it in `rebuts`,
which the harness holds for the operator under `review_rebuttal`: it reaches no worker until the operator sends it. A
later review's finding that is not `blocking`, on lines no change since the PR's first reviewed commit touched, is late,
held the same way under `review_late`. So an author and a reviewer that disagree, or a reviewer finding more of code
already read each round, reach a person instead of the per-PR limit.

### Review requests

The operator asks for one review of a coworker's PR at its head, and again after a push for the new head. A request is
a journal fact, at most one open per PR, ended by a `done` review in each persona it names (§31), the PR closing, or
the operator. Its notes and model reach its reviewer, and an override that drops the notes fails to render; it starts
first in a tick and never waits to settle, since the operator asked by hand. The harness answers one on a PR that is
no ticket's in code (§37); one on the loop's own PR is the overseer's. Work on a coworker's PR is refused, so a
review never turns into work on someone else's branch, and so is a request inside a run: it authorizes a review as
`review.query` does, so an agent steered by a PR's text could otherwise aim the operator's spend at any PR (T1).

### Dismissing and sending findings

A dismissed finding stays listed but leaves what a `resume` hands the worker, and a review whose findings are all
dismissed moves on as clean; a dismissal says why, so dismissals measure the reviewer's noise, which would justify a
verifier's spend. Sending is the operator's go-ahead on an `own` review's undismissed findings while its ticket has the
PR: an operator message names them by number, never quoting them, since the reviewer's text is data (T1) and the
message an instruction, and the next tick dispatches a `resume` with them, `canopy:review` trusted or not (D089). Both
are refused inside a run, so no agent can hold a finding back from a worker or start work in the operator's name.

### The diff

The slot goes with the review and the web UI cannot ask GitHub (principle 5), so the review keeps, best effort and for
the operator only, the diff of exactly the commit the reviewer read, from its merge base with the branch the PR merges
into. Diff drivers and textconv are off, since a commit's `.gitattributes` can name them (D107), and the diff is the
PR's text: rendered as text, never served as a file.

### Scoring the reviewer

`canopy review eval` scores the reviewer on the operator's cases: PRs at a commit, each with a confirmed bug or known
clean, each reviewed as a PR's first review. The score gates nothing, and the journal holds nothing of an eval, so none
reaches a worker, a draft, or attention. A case authorizes a review as `review.query` does, so only the operator runs
one, never in a tick or a run. Rejected: review runs for an eval, which would count against PRs' limits and make drafts.

### Open

- How a finding is followed from one commit's review to the next, so a dismissal or a send could outlast its run.
- Whether OpenCode confines the reviewer to its checkout link. The opt-in reviewer canary settles it; if not, the
  reviewer reads the PR only through MCP.
