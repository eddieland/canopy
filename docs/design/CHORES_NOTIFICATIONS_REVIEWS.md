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
check the overseer runs inline. Chores are not "tasks", which is OpenCode's subagent tool.

### Definition

Chores are private (§12); one in a workspace file is a config error (TRUST_MODEL T7).

```toml
[runtime]
# the default
chore_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json
    --thinking --title={title} {prompt}'''

[capacity]
max_chores = 1            # chore runs at once; separate from max_workers

[chores.build-health]
prompt = "~/.config/canopy/chores/build-health.md"
cmd = 'opencode run --agent build-health --format json {prompt}'
every_minutes = 120
days = ["mon", "tue", "wed", "thu", "fri"]
hours = "08:00-18:00"
timezone = "America/New_York"
when = "Skip it when the last run found nothing and nothing has merged to main since."
max_findings = 10         # optional; default 5
timeout_minutes = 20
cwd = "~/src/build-tools"
workspaces = ["acme"]     # optional; default every workspace
```

- `prompt` (required) is the operator's file. `examples/chores/` has one to start from and ideas for more.
- `cmd` follows §12 (`{prompt}` exactly once, no shell); default `runtime.chore_cmd`. A chore using the operator's own
  tools needs its own agent definition (below), so `cmd` is usually set.
- `every_minutes`, at least 15, is the shortest time between two run starts. A guard, not a schedule.
- `days`, `hours` (within one day), and `timezone` (default the machine's) are optional and say when a run may start,
  checked in code. A run still going when the window closes runs to its end or timeout.
- `when` (optional) is plain language for the overseer: when a run is worth it, pointless, or urgent; without it a
  chore runs whenever due. Being operator-written, it is an instruction; nothing a chore reads is. Clock times belong
  in `days` and `hours`, which cost no judgment and no `wait` decision every tick.
- `max_findings` (optional, 1 to 20, default 5) is the most findings a run lists, so a chore that finds a lot puts
  the few that matter most before the operator rather than all of them. Five is what a person reads at a glance; a
  chore whose findings are each small and alike can raise it to the contract's 20. The prompt asks for the most
  important first and a count of the rest; a guard in code keeps the first `max_findings` of a longer list and adds
  the others to that count. A dismissed finding still takes its place: a note is how to make room.
- `timeout_minutes` defaults to 15. `cwd` defaults to a private directory per chore under the state directory. The
  shadowing check (§13) covers `cwd` and every directory above it: OpenCode config there that defines one of canopy's
  agents makes the run `crashed`.
- `workspaces` names workspaces (§18); empty means every workspace whose loop reads the file the chore is in. A chore
  in two workspaces runs in each, journaled in each. `[chores]` comes whole from the last file that sets it, so a
  private file's chores replace the user file's.

### Off unless configured

With no `[chores.*]` tables, or `capacity.max_chores = 0`, the state block has no `chores` key, no chore decision is
recorded, and `canopy chore run` refuses as `unknown_chore`. Deleting a chore's table turns it off: its findings and
`chore_failed` item leave the attention list at the next render and are notified as resolved (§14). Chores never affect
what the overseer does with tickets: they cannot cause or prevent a dispatch.

### Agent definitions and tooling

canopy ships `canopy-chore` in the definitions directory (§13): no edits, no subagents, no bash but
`canopy chore history` (History, below), and no MCP write tools where the runtime can deny them by name. It can read
the tracker and GitHub, including other people's PRs.

A chore using the operator's deterministic tools gets its own definition, copied from `canopy-chore` into the
operator's runtime config (for OpenCode `~/.config/opencode/agent/`, never the repository's `.opencode/agent/`), with
bash allowed for exactly those tools:

```yaml
permission:
  edit: deny
  task: deny
  bash:
    "*": deny
    "canopy chore history *": allow   # its own earlier runs (History, below)
    "buildq *": allow        # the operator's read-only CLI for the build queue
```

The operator installs the tools. CI credentials belong to the tools or the runtime's MCP servers (§4, principle 5);
canopy never sees them and knows nothing of any CI system.

### Delegation

The state block lists each configured chore with its `when`, when it is next due, whether it is running, its latest
run, and its open findings. Each tick the overseer decides each chore that is due and not running: `canopy chore run
<NAME> [--context '<text>']`, or `canopy chore wait <NAME> --rationale "<text>"` when `when` says not now. `--context`
follows §8: bounded, pointing at what to look at, never quoting untrusted text. Findings inform only decisions about
the chore, never about tickets (see Open).

`canopy chore run` requires `CANOPY_TICK_ID` like `dispatch` (D020) and refuses, recording `refused:<guard>`, on the
first of:

- `unknown_chore`: no such chore in the operator's config, not for this workspace, or `max_chores` is 0.
- `running`: a run of this chore is running.
- `not_due`: less than `every_minutes` since this chore's latest run started, however it ended.
- `outside_hours`: now is outside the chore's `days` and `hours`, in its `timezone`.
- `chore_capacity`: `capacity.max_chores` chore runs are running.

A dry run checks the same guards and starts nothing (D036). `canopy chore wait` refuses an unconfigured chore. Chore
runs start under the dispatch lock.

### Runs

A chore run starts detached, as a worker does (§8 step 4), drops `CANOPY_TICK_ID`, and runs the command in `cwd` with
the timeout. No lease, branch, or push, so nothing to return or verify. Its log and prompt are in
`<state_dir>/chore-runs/<name>/`, not in its working directory, which a sandbox lets it write (§24): its own log and
prompt are not its to read back or rewrite.

The prompt is the operator's file plus a `## Run` section canopy generates: the time, the overseer's context, the
operator's notes (below) and notice to workers (§8), the latest run, the open findings so ids can be reused,
`max_findings`, the command that reads earlier runs (`history`, below), and the result contract. The notice is in
canopy's section, which the operator's file cannot drop.

Result contract, one JSON line, last line of the agent's text (§13):

```json
{"status":"ok|failed","summary":"one paragraph",
 "findings":[{"id":"flaky/checkout-service/test_retry","title":"one line","detail":"a paragraph","link":"https://..."}],
 "more_findings":0}
```

- `ok`: the check ran; no findings means nothing needs a human. `failed`: it could not check, and the summary says why.
- A finding's `id` is stable across runs for the same problem and unique within a run. Text is cut to bounds, `link`
  is absent or a plain `https://` URL, and at most 20 findings are accepted.
- `more_findings` (default 0) counts the findings the chore had past `max_findings` and left out. It is only a count:
  what they were is in no journal row, so the operator who wants them raises `max_findings` or writes a note.
- Validated with pydantic (D026). Anything else is `unknown`, with no findings recorded.

Reconcile (§6 step 3) treats chore runs like worker runs: one whose process is gone has its agent killed and ends
`crashed`. Chore runs do not count against `max_workers`.

### History

`canopy chore history <NAME>` lists a chore's runs, newest first, each with how and when it ended, whether the overseer
or the operator started it, its summary, and its findings' ids, titles, and links: ten by default, `--limit` up to 50,
and `--before <RUN>` for the page before. `--run <RUN>` prints one run whole, each finding's detail included. It
records nothing.

- A run's prompt carries the latest run and the open findings, which most runs need and every run pays for. The rest
  a run reads when it needs it: whether a problem came and went, or what a run said of a finding before it cleared.
  The `## Run` object names the command as `history`. Rejected: more runs in the prompt, a cost on every run for what
  few use.
- A chore's run reads its own chore's runs only: another chore's is refused `other_chore`, and another chore's run id
  `unknown`. `CANOPY_RUN_ID` names the run, `chore-<id>`, or `chore-try:<name>` for a try that records nothing, and
  `CANOPY_CHORE_WORKSPACE` the workspace, so the command finds the journal from a `cwd` outside it.
- The overseer is refused `inside_tick`: its state block carries what it decides a chore on, and findings inform
  nothing else (Delegation). A worker's or a review's run is refused `not_chore`. The operator reads any chore's.
- What it prints is what the runs reported: data, framed so for a run, with every hidden character named in what it
  prints whole. Dismissals and notes are not in it: they are the operator's, and the prompt carries the notes.
- `canopy-chore` allows bash for this one command; an operator's own chore definition adds the rule to use it. A
  sandboxed chore cannot: the journal is in the part of `.canopy/` its policy denies (§24), so it has its prompt's.

### Notes from the operator

`canopy reply chore:<NAME> '<text>'`, or the web UI (§22), records a note to a chore: how the operator answers a
finding without editing the prompt file ("leave out flaky/checkout/test_retry until 2026-10-15, the fix is merging").

- Every later run, a try's included, carries the latest 10, oldest first, a later one winning. They are the
  operator's words, so they are instructions; the overseer's context is not.
- Nothing clears a note, since one meant "until" a date must outlast a run; the agent compares the date. It falls out
  after 10 newer ones. To take one back, write a newer note.
- Notes reach neither the overseer nor the attention list, and do not wake the loop.

### Dismissing a finding

`canopy dismiss chore:<NAME> <ID>`, or the web UI (§22), keeps one open finding off the attention list while the chore
goes on reporting it. A note changes what later runs are told, not what the latest run reported.

- A dismissal holds while later `ok` runs report the id and is spent once one leaves it out, so a finding that clears
  and comes back is listed and notified again. Nothing needs cleaning up, and a dismissal never hides a recurrence the
  operator has not seen.
- It changes only what the operator is shown: the chore's prompt and the overseer's state block still carry it, and
  `canopy show` and the web UI list it marked. Leaving the list, it is notified as resolved, marked dismissed (§20).
  To have the chore stop reporting it, write a note. `--undo` takes it back.
- `attention.md` is rewritten at once; notifications go at the next tick.
- Refused `unknown` for a finding the chore does not have open, `bad_finding` for an id no finding can have, and
  `inside_run` as `reply` is: the overseer and agents cannot hide a finding from the operator.

### Trying a chore

`canopy chore try <NAME> [--context '<text>'] [--no-record]` is the operator's, for writing a chore and for running one
now. It runs the chore in the foreground through the same code as a delegated run, prints what the agent said and the
result, and exits 0 only on `ok`.

- It is a real run, recorded with no tick and no decision: its findings become the open findings, a failure raises
  `chore_failed`, sinks hear of it, its cost counts, and the chore's next run is `not_due` counting from it. Recording
  is the default because a run started by hand that did not show up where the loop's runs do read as lost.
- `--no-record` writes nothing, so the next tick sees no change. It is for drafting the prompt of a chore with open
  findings, which a recorded try of a half-written prompt would clear.
- No time or capacity guard applies, so it works before `every_minutes` is up, outside hours, and with
  `max_chores = 0` (its findings are listed once that is above 0). The chore must be defined for this workspace.
- A recorded try refuses `running`, and records its run under the dispatch lock, so it never overlaps one the overseer
  started. Reconcile treats it as any run: killed, it is marked `crashed` at the next tick.
- It refuses `inside_run`, like `start` and `reply` (§22), and its own agent has `CANOPY_RUN_ID` set. The overseer's
  bash allows only `canopy ...`, which cannot unset `CANOPY_TICK_ID`, so the loop cannot try a chore.
- The web UI tries a chore too (asked for by the operator, 2026-10-15), from the chore's page (§22): a recorded try,
  with the same `running` refusal and no guard on time or capacity. A request cannot wait out a chore's timeout, so a
  detached `canopy _chore` does the run, as the overseer's are, rather than the server's own process. It has no
  `--context` or `--no-record`: an unrecorded try's output has nowhere to go but a terminal, and the context is the
  overseer's to give.

### Findings on the attention list

- Open findings are those of the chore's latest `ok` run; one disappears when a later `ok` run omits its id (§14). A
  non-`ok` run leaves them standing. A dismissed one is not listed.
- A latest run ended `failed`, `unknown`, `timeout`, or `crashed` also raises `chore_failed`, after reconcile, cleared
  by a later `ok` run.
- `attention.md` and `canopy status` list them per chore, `chore:<name>`, after the ticket items, each finding aged
  from the first of the unbroken `ok` runs reporting it. Notification follows §14, keyed by chore and finding id.
- The latest `ok` run's `more_findings` is said after them, in `attention.md`, `canopy status`, `canopy show`, and the
  web UI's chore pages, so a cut list never reads as the whole. It is not an item and is not notified: it has no id
  to age or resolve by. While it is above 0, the chore's page in the web UI (§22) opens with a band saying the chore is
  over its limit, by how much, and what to do: raise `max_findings`, or write a note that narrows what it reports.

### Journal

Each chore run (its tick, if any, its status, validated result, and cost, §13), kept apart from worker runs, which
have a ticket, slot, and branch; decisions, each naming a ticket or a chore, never both; and dismissals.

### Trust model changes

Approved with M9:

- T1: chores read text from outside the operator's queue (other people's PRs, build logs). Findings are data
  everywhere: attention list, notification, state block.
- T3: `every_minutes`, `running`, and `capacity.max_chores` are controls in code; §6: never run a chore more often than
  its `every_minutes`, or more than `capacity.max_chores` at once.
- T6: a chore's only output is its result line; the shipped definition has no write tools. Residual: a steered chore
  can put up to 20 findings of its choosing before the operator and into `notify.cmd`, and a link can carry data.
- T7: chores, `runtime.chore_cmd`, and `capacity.max_chores` are private.
- §7: the operator is responsible for any tool allowed in a chore's definition. canopy assumes chore tools only read.

### Open

- Whether a chore should ever write (acting on others' work, which D010 kept out). Likely first: a ticket for a
  finding, without a queue label like a split child (§18), so a human decides.
- Whether findings should inform ticket decisions once chores have a track record (a flaky-check finding raising
  attention instead of dispatching a `resume` for it). Only to hold work back or raise attention, never to make a ticket
  a candidate, and opt-in per chore.
- Whether a repository should offer chores operators opt into by name, as it offers its tracker query.
- Whether a chore should get checkouts of the workspace's repositories, for a tool that reads files rather than
  GitHub (today the operator keeps a checkout current and points `cwd` at it). A review's private linked checkout
  (§21) and a desk (§18) are the parts. Likely first: the chore's table names the repositories, never the overseer.
  The cost is slots: a chore holding one could block a dispatch, so it would count toward `capacity` as a review does,
  and chores would then affect tickets. Also open: a chore in a workspace whose map lacks one of its repositories.

## 20. Notifications

Rationale in D035. This generalizes `notify.cmd` (§14), which stays and behaves as it did.

Notifications reach the operator away from the terminal (REQUIREMENTS N2). A destination is a **sink**, a command
that reads one message on stdin. canopy ships a desktop sink and a Slack sink; others are the operator's programs.

### Sinks

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack"            # the shipped sink; reads its webhook from a file of its own
events = ["attention", "loop", "runs"]
digest_every_minutes = 240
batch_minutes = 15

[notify.sinks.phone]
cmd = "curl -sS --fail --data-binary @- https://ntfy.sh/my-private-topic"
format = "text"
```

- Sinks are private (§12), like every `notify.*` key (TRUST_MODEL T7).
- At most 5 sinks, since each can hold the tick lock for its timeout.
- `cmd` follows `notify.cmd`'s rules (§12): argv, no shell, no `{prompt}`. It gets the message on stdin and 60
  seconds. Exit 0 means delivered; anything else, timeout included, means retry next tick.
- `format` is `json` (the default) or `text`.
- `events` lists the groups the sink receives: `attention`, `loop`, `runs`, `chores`, `reviews`. Default
  `["attention", "loop"]`.
- `digest_every_minutes` (at least 60) and `batch_minutes` (1 to 1440) are optional (below).
- `notify.cmd = "X"` is shorthand for a sink named `default` with `cmd = "X"`, `format = "text"`,
  `events = ["attention"]`, no digest, and no batching, so switching between the two re-notifies nothing. Setting both
  is a config error.

With no sink, publishing is §14 without the notification.

### Events

A closed set, written by the harness from the journal. Text fields are cut to the limits shown, on one line.

| Group | Kind | When | Fields |
|---|---|---|---|
| `attention` | `attention.opened` | a listed item the sink was not told of | ticket, title, reason, detail (500), since |
| `attention` | `attention.resolved` | an item the sink was told of left the list | ticket, title, reason |
| `runs` | `run.started` | dispatch started a worker | ticket, title, run, kind, branch, attempt, limit |
| `runs` | `run.ended` | a run's row closed | ticket, title, run, kind, status, branch, pr, prs, summary, question, message |
| `runs` | `plan.proposed` | a plan run's plan was recorded, waiting on the operator (§25) | ticket, title, run, plan; never its text |
| `chores` | `chore.ended` | a chore run's row was closed (§19) | chore, run, status, summary, how many findings |
| `reviews` | `review.ended` | a review run's row was closed (§21) | pr, ticket, title, run, status, verdict, impact, how many findings |
| `loop` | `loop.failing` | the latest 3 ticks all ended other than `ok` | count, latest status and tick, its log |
| `loop` | `loop.recovered` | the first `ok` tick after `loop.failing` | how many ticks failed |
| `loop` | `loop.sink_failing` | a sink has failed 3 deliveries in a row | sink, the tail of its stderr |

`summary` and `question` are cut at 300 characters, each PR URL at 500. `question` is set only for a `blocked` run;
the needs-human label is not an attention item, so `run.ended` is how a sink hears of the question. `message` is the
journal id of the message the run recorded (§22), so a channel can say what a reply answers.

Attention is a diff of state per sink (§14): each sink hears of each open item once, and a sink that was down gets the
net change. The other kinds are point events in an outbox, written in the same transaction as the fact they report,
and each sink keeps a cursor in it. `loop.failing` and `loop.sink_failing` are recorded once per streak.

### Delivery

§6 step 7, after `attention.md` is written, for each sink in turn:

1. Gather the sink's attention diff, its new events in the groups it takes, and a digest if one is due. If there is
   nothing, or the sink is batching and nothing is urgent, go to the next sink.
2. Render one message in the sink's format and run the command.
3. On exit 0, record what the sink was told and move its cursor. Otherwise change nothing and count the failure; the
   third in a row records `loop.sink_failing`, which the sink, if it takes `loop`, hears when it recovers.

Bounds: at most 20 attention lines and 20 events per message, the rest counted in a closing line pointing at
`attention.md` and `canopy status`; events over 24 hours old when a sink next succeeds are counted, not listed. A new
sink starts with no backlog, and its first delivery lists every open attention item. Delivered events are pruned
after 7 days, but for what tells a long failing streak from a new one. Sinks run in turn under the tick lock, so each
hung sink delays the next tick by up to 60 seconds.

### Batching

A busy loop ticks often (§6), so a burst of runs is a message every few minutes. A sink with `batch_minutes` sends at
most one message per window, unless something needs the operator now:

- After a delivery, what the sink gathers is held until the window ends, then sent as one message. A sink with no
  delivery inside the window sends at once, so the first message after a quiet spell is not late.
- Urgent goes at once, with everything held: a new attention item, a `blocked` run's question, a `plan.proposed`,
  `loop.failing`, and `loop.sink_failing`. Everything else waits.
- A held message goes at the first tick after its window; holding does not wake the loop, since a tick runs the
  overseer.
- A failed delivery starts no window, so a retry is never held.

### Digest

A sink with `digest_every_minutes` gets a digest at its first delivery and then every interval: since the previous
one, ticks by status, runs started and ended (each `done` run's ticket and PR, each `blocked` run's ticket), the open
attention list by reason, and the workers running now. It is sent even when nothing happened ("24 ticks ok, nothing
ran, nothing needs you"): a missing digest shows ticks stopped, which canopy cannot report itself. No model writes
it; a report needing judgment is a chore (§19).

### Formats

`text` is lines for a person. Attention alone is exactly §14's message, so `notify.cmd` output is unchanged.

`json` is one object:

```json
{"version": 1, "sink": "slack", "repo": "/home/me/src/api", "sent_at": "2026-09-24T19:00:00Z",
 "attention": {"added": [{"ticket": "PROJ-3", "title": "Retry failed checkouts", "reason": "needs_reviewer",
                          "detail": "https://...", "since": "..."}],
               "resolved": [{"ticket": "PROJ-4", "title": null, "reason": "ready_to_merge"}],
               "open": 4, "path": "/home/me/.canopy/attention.md"},
 "events": [{"id": 88, "kind": "run.ended", "at": "...", "ticket": "PROJ-12", "title": "Add retries", "run": 41,
             "run_kind": "implement", "status": "done", "branch": "agent/PROJ-12-add-retry", "pr": "https://...",
             "summary": "..."}],
 "omitted": 0,
 "digest": null,
 "text": "the same message in the text format"}
```

A `resolved` item says whether it was a chore finding the operator dismissed (§19). Every ticket key has the ticket's
title beside it (§13), for display; the text format shows the key alone, keeping §14's message as it was. Each event
and the digest carry their text lines too. `version` changes only on an incompatible change; sinks ignore unknown
fields.

Presentation is the sink's. The fields are the contract, and a sink that can show more than lines builds its own
message from them in its channel's native form, as the Slack sink does with Block Kit; the text lines are canopy's one
rendering, for sinks that only forward a string and as a fallback. So the harness never learns a channel's markup, and
a new event kind needs fields a sink can present, not only a line.

### The desktop sink

`canopy-notify-desktop` ships with canopy, stdlib only (D035), and runs only as a configured sink, never inside the
harness.

```toml
[notify.sinks.desktop]
cmd = "canopy-notify-desktop"
events = ["attention", "loop", "runs"]   # runs: a blocked worker's question arrives as run.ended
```

It shows the message's text, bounded, through `notify-send` on Linux or a fixed `osascript` script on macOS, passing
title and body as arguments, never as a shell command or script, so agent or org-member text runs nothing.

### The Slack sink

`canopy-notify-slack` is its own program (§5), stdlib only, importing nothing from canopy, and installed with it. It
posts one message per delivery, as Block Kit built from the `json` fields with the text as fallback.

- It posts to an incoming webhook whose URL is read from a file (default `~/.config/canopy/slack-webhook`). The file
  must be a regular file of the operator's, unreadable by group and others, holding one `https://hooks.slack.com/`
  URL; otherwise the sink refuses. The URL is never in canopy's config, argv, journal, or logs.
- With `--channel` it posts with a bot token instead (`chat.postMessage`), for a workspace that disallows incoming
  webhooks or an app serving several channels. The token file (default `~/.config/canopy/slack-token`) passes the
  same checks and must hold an `xoxb-` bot token: a user token acts as the operator with all its scopes. A post counts
  as delivered only when Slack's reply says `ok`, since the Web API answers 200 to a refused post. Like the URL, the
  token is never in canopy's config, argv, journal, or logs, nor in the sink's own messages.
- Journal text is escaped for Slack markup (`&`, `<`, `>`) and every text object is `verbatim`, so Slack parses no
  `@here`, `@channel`, person, or channel name in it, and nothing can disguise a link. A URL is shown as itself; one
  holding `|`, which would take a label, stays text.
- Setup: a Slack app with an incoming webhook for one channel, its URL in the file with mode 600, the
  `[notify.sinks.slack]` table, and `canopy notify test slack`. With a token: the `chat:write` bot scope, the bot
  invited to the channel, its token in the token file with mode 600, and
  `cmd = "canopy-notify-slack --channel C0123ABCD"`.

Lint keeps the network out of the harness, as D015 keeps processes in one module: `urllib.request`, `http.client`, and
`socket` are banned everywhere in `src/canopy`, no exceptions, and so is any import of the Slack sink. The harness runs
the Slack sink only as a configured command.

### Commands

- `canopy notify test [SINK]` sends a test message now, outside any tick, and changes no delivery state. It refuses
  when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, so neither the overseer nor a worker, review, or chore can page.
- `canopy status` shows each sink's health.

### Two-way, later

Not built. A listener must follow TRUST_MODEL T8 (D055): loopback or private network, behind the operator's secret.
Slack's Events API and slash commands need inbound internet access, so they stay out; Socket Mode connects outward and
could fit T8 once something long-running holds the connection. What fits, in order:

1. **Replies on the ticket.** Works now: messages name the ticket and carry the journal's links; an authorized reply
   on the ticket resumes the worker. Slack is the pager; the ticket is the conversation.
2. **Replies in Slack, read by the overseer** through a Slack MCP server each tick, a reply by an authorized Slack
   account counting as authorized. Needs one thread per ticket (a bot token and `chat.postMessage` instead of a
   webhook, the sink reporting each thread on stdout for the harness to record and pass into the state block), Slack
   account ids among the authorized repliers, and a TRUST_MODEL T1 change.

It attaches at the `json` format's `version` and the sink's stdout, ignored today. §22 plans the conversation these
replies would join: the journal records it, and Slack becomes one channel into it.

### Trust model changes

Approved with M10:

- T2: the harness makes no outbound call except through configured commands and reads no token. The Slack sink does
  both, but runs only as a configured sink, reads its webhook from the operator's file, and lint keeps network modules
  and the sink out of the harness.
- T6: notifications carry agent- and org-member-written text off the machine. Controls: only the table's fields, cut
  to limits; Slack escaping. Residual: a steered agent picks up to 500 characters per item shown in the channel, and a
  link can carry data (as §19 says of findings).
- §7: point a sink only where the audience may read the tickets and PRs it quotes; keep the webhook or token file
  readable only by the operator, and give a bot token only `chat:write`. Channel readers see what the loop does but
  cannot steer it.

### Open

- Routing finer than groups, such as `crashed` to a phone and `needs_reviewer` to Slack only.
- Digests at fixed times of day instead of an interval.
- Batching that folds a run's `run.started` into its `run.ended` when both are held, one line instead of two.
- Reminders for items open longer than some threshold.
- Links to tickets. `tracker.ticket_url` (§17) links them in the web UI; a sink's message could link its ticket too.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

A review is an adversarial read of one PR at one commit by a fresh agent run, with no transcript of the author's run,
told to assume the change is wrong until the code shows otherwise. It reports a verdict and its findings to canopy's
journal, and posts nothing: no comment on the PR or the ticket, no GitHub review (D114). It never approves, requests
changes, pushes, or merges. Human review stays the gate (§3). The operator reads reviews with `canopy review show`
and in the web UI.

Three kinds of PR get reviews, and none needs a ticket:

- **The loop's own PRs.** With `review.agent_prs` on, a ticket's PR is reviewed once its checks pass, before the
  overseer asks a human for review. Findings go back to a worker through `resume`.
- **PRs the operator names with `review.query`.** Reviewed and nothing else: the loop never pushes to them, fixes
  them, or opens a ticket for them. The review in the journal is the whole output, for the operator alone.
- **PRs the operator asks for one at a time** (ROADMAP M42): one review of a coworker's PR at its head, without
  writing a search into `review.query` (Review requests, below). Reviewed as a `review.query` match is.

Why nothing is posted: a review on the PR speaks for the operator, in their name, to everyone who reads the PR, and
an adversarial reader is wrong often enough that the operator wants to see its findings before anyone else does. Kept
in the journal, a review costs the PR's audience nothing, needs no write tool, and cannot be forged by anything that
posts as the operator, since the loop never read reviews from the PR anyway.

### Configuration

Every review key is private (§12), except the per-PR limit, a shared policy the repository may only tighten
(TRUST_MODEL T7).

```toml
[review]
agent_prs = true           # default false
query = 'repo:acme/api is:pr is:open author:@me -is:draft'
low_impact = """Only docs, comments, or tests change; or one dependency moves by a patch version."""

[runtime]
# the default
review_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer --format json
    --thinking --title={title} {prompt}'''
review_timeout_minutes = 20

[capacity]
max_reviews = 1            # review runs at once, within max_workers; 0 turns reviews off
max_reviews_per_day = 20   # review runs started in any 24 hours

[policy]
max_reviews_per_pr = 3     # shared; the repository may only lower it
```

- `query` is the VCS host's PR search syntax. Reviews are on when `max_reviews` is above 0 and `agent_prs` or `query`
  is set.
- `review.query` authorizes, unlike `tracker.query` (§17). Without an author filter it reviews other people's PRs in
  the operator's name; allowed, and the operator's choice (TRUST_MODEL §7). A review request authorizes the same way,
  for one PR.
- `low_impact` is plain language for the reviewer, like a chore's `when`: which changes it may call `low`. Without it,
  the reviewer never reports `low`.
- `review_cmd` follows §12. A different model from `worker_cmd` is recommended. To sandbox it, prefix it with
  `canopy-sandbox review` (§24): that policy reads the checkout through the run directory's link and writes none of it.

### Off unless configured

With neither `agent_prs` nor `query` set and no open review request, or with `capacity.max_reviews = 0`, nothing about
reviews reaches the overseer: no `reviews` in the state block, §7's phase table unchanged, and every
`canopy review run` refuses as `reviews_off`. An open request turns reviews on until the last one ends. With
`agent_prs` off, a loop PR that `query` matches is reviewed like any other match: a review in the journal, no `resume`.

### Running a review

`canopy review run --pr URL --sha SHA [--ticket KEY] [--repo NAME] [--context '<text>']` requires `CANOPY_TICK_ID` like
`dispatch` (D020). `URL` is the PR's `https://` URL, an opaque string the harness never parses; `SHA` is the head
commit the overseer read; `--ticket` links an agent PR to its ticket. The run records its purpose: `own` with
`--ticket`; `request` for a PR with the operator's open review request; `query` otherwise. The harness cannot tell
that a PR matched the query, since the overseer runs it; `query` means a PR the loop does not own and the operator did
not ask for by name. Only an `own` review's findings can go to a worker. Under the dispatch lock, it refuses,
recording `refused:<guard>`, on the first of:

- `reviews_off`: see above.
- `bad_pr`: `URL` is not a plain `https://` URL of at most 300 characters, `SHA` is not 40 or 64 lowercase hex
  characters, or `--ticket` is not a valid key (§17).
- `unknown_repo`: no `--repo`, or one not in the map or with no clone. The slot comes from that repository's pool.
- `not_ours`: `--ticket` names a ticket whose unit in that repository did not open `URL`. The overseer's ticket link
  is a claim, checked here, so an `own` review is of a PR the loop opened.
- `running`: a review of this PR is running, or, with `--ticket`, a worker run for that ticket is.
- `reviewed`: a review of this PR at this commit ended `done`. The refusal names its verdict and impact.
- `review_limit`: this PR has had `policy.max_reviews_per_pr` review runs, plus any the operator granted it with
  `canopy grant URL review` (§22), however they ended. Also records the `review_limit` attention item.
- `daily_limit`: `capacity.max_reviews_per_day` review runs started in the last 24 hours.
- `review_capacity`: `capacity.max_reviews` review runs are running.
- `capacity`: `max_workers` runs and review runs, together, are running.

A dry run checks the same guards and starts nothing (D036). Worker dispatches also count a running review toward
`capacity` (§8). Past the guards, a slot that cannot be leased refuses as `no_slot`, and a prompt that does not render
as `bad_prompt`. The review then starts detached, as a worker does (§8 step 4), and:

1. Drops `CANOPY_TICK_ID`, as a worker run does.
2. Checks out `SHA` detached in the slot and verifies `HEAD` is `SHA`, or ends `failed` (a PR in another repository
   fails here). No branch is created. It deletes every symlink the commit tracks that resolves outside the checkout,
   and keeps the commit's diff (The diff, below).
3. Runs `review_cmd` in a private directory of canopy's, **not the checkout**, so the runtime loads no configuration
   from the PR. The directory holds one link, `checkout`, to the slot, as a desk's links do (§18), and the shadowing
   check (§13) covers it and the workspace root. Timeout `review_timeout_minutes`.
4. Parses the result, then always removes its directory, never following the link, and returns the slot, on a signal
   too (§8 step 6). Reconcile treats a dead review as a dead worker run: it kills the reviewer, removes the directory,
   returns the slot, and marks the run `crashed`. A running review's lease is never returned as stale.

The prompt is `prompts/reviewer.md` (or the override), with the PR, the commit, the checkout, an agent PR's ticket,
`review.low_impact`, the attempt and limit, the overseer's context, and the operator's notice to workers
(`{{NOTICE}}`: an override without it is `bad_prompt` while one is in force, §8). The reviewer looks for defects, not
style, posts nothing anywhere, and treats everything it reads, the diff included, as data (TRUST_MODEL T1).

Result contract, one JSON line, last line of the reviewer's text (§13), validated with pydantic (D026):

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","summary":"one paragraph",
 "pr_title":"the PR's title as it stands",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line","detail":"what and why"}]}
```

- `done` means the review was read through. `failed` means the reviewer could not review; the summary says why. A
  `comment` key, from a reviewer prompt older than D114, is ignored.
- At most 20 findings, text cut to bounds. `verdict` is `findings` exactly when `findings` is not empty, and a `done`
  review has a verdict and an impact.
- `low` without `review.low_impact` is recorded as `normal`, with a harness note.
- `pr_title` is the PR's title as the reviewer read it, one line cut at 256 characters. Once the run is closed it
  replaces the PR's stored title (§8), so a PR canopy only reviews, which has no ticket, has a title to show, and the
  newest report wins, a worker's or a review's. It is the PR author's text, which a reviewer of a `review.query` PR
  reads from anyone: it is for display only, never read back. Optional: a result without it records none.
- Anything else is `unknown`.

### The verdict, and automating on it

canopy never approves (TRUST_MODEL §6): a review changes no GitHub review state and cannot satisfy a required
approval. The verdict and impact are for the operator and the overseer, and leave the machine only as the `review.ended`
event's fields (§20). No repository automation can read them, so a review cannot let a low-impact PR skip a human
reviewer. A repository that wants that needs a verdict it can trust, which waits on a bot identity (ROADMAP, deferred).

### The overseer's part

The state block's `reviews` carries the settings and limits, the running review runs, each recently reviewed PR with
its ticket, its runs so far and any granted (§22), and its latest run's outcome with the titles of its findings the
operator has not dismissed, and each open review request (below).

For the loop's own PRs, the phase table (§7) gains two rows between `ci_red` and `green_unreviewed`, used only when
`agent_prs` is on. Findings are `review_findings` only when `trust.trusted_reviewers` lists `canopy:review`; otherwise
they are `untrusted_review` and wait for the operator's go-ahead like any untrusted reviewer's (§7, D089):

| Phase | Derived from | Next action |
|---|---|---|
| `review_pending` | checks pass, no approval, no `done` review of the head commit, under the per-PR limit | `canopy review run --ticket KEY` |
| `review_findings` | the head commit's `done` review has findings the operator has not dismissed, newer than the `review` cursor | classify as review comments (§7): dispatch `resume --review-run <id>`, or `needs_author` |

A clean review, or a PR at its review limit, moves on to `green_unreviewed`, whose `needs_reviewer` item names the
latest review run. A `resume` pushes a new commit, which is reviewed again, up to the per-PR limit. The overseer knows a
review only from the state block. Nothing on the PR is one, and a review never counts toward `changes_requested`.

`canopy dispatch KEY --kind resume --review-run ID` hands the worker review run `ID`'s findings. It refuses as
`bad_review` unless the kind is `resume` and the run is this ticket's, of a repository the dispatch names, `done`, and
has findings. The worker's prompt carries them as `{{REVIEW_FINDINGS}}`; an override without that placeholder fails
to render, so the findings are never dropped silently. The worker treats them as a trusted reviewer's comments when
`canopy:review` is trusted, and never posts them. The `review` cursor (§7) covers review runs by when each ended.

For `review.query`, the overseer runs the query each tick and keeps only PRs of this repository, since a review could
not fetch another repository's commit from `origin`. For each open match whose head has no `done` review, it runs a
review or records `canopy review wait --pr URL --rationale "<text>"` (checks still running, a draft). Nothing else is
decided about these PRs. `review wait` and `attention --pr` refuse a URL `review run` would call `bad_pr` as misuse,
recording nothing.

### Review requests

A request hands canopy a coworker's PR to review without writing a search into `review.query`, which reads one
repository's PRs. It asks for one review, at the PR's head; asking again after a push reviews the new head. Watching a
PR, reviewing each new commit until it merges, is deferred as more than MVP needs.

- A request is a journal fact, like a start record (§22), at most one open per PR; asking again records nothing. It
  ends `reviewed` when a review of the PR ends `done`, or when `canopy review run` refuses `reviewed` for it (an
  existing review answers it); `merged`, `closed`, or `unknown_repo` when the overseer finds the PR merged, closed, or
  in none of the workspace's cloned repositories before a review; and `stopped` when the operator ends it.
- `canopy start URL --review`, or the web UI's pull requests page, makes one; `canopy stop URL` ends it, a review
  already running finishing. `start` on a PR without `--review` is refused `unsupported`, so a missing flag never turns
  a review into work on someone else's branch.
- Both refuse as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, as `start`, `reply`, and `grant` do: a
  request authorizes a review as `review.query` does, so an agent steered by a PR's text could otherwise point the
  reviewer, and the operator's spend, at any PR. `start` also refuses `reviews_off` when `capacity.max_reviews` is 0,
  `bad_pr` for anything but a PR's plain `https://` URL (a review run is keyed by it), and `loop_pr` for one of the
  loop's own PRs, which `review.agent_prs` covers. `stop` refuses `not_requested` without an open request.
- The overseer reads each requested PR through MCP each tick and names its repository, the one whose map `url` matches
  the PR's host, owner, and name; the harness never parses the URL (principle 5). `canopy review run` still refuses
  `unknown_repo`, and a wrong repository fails that review when its commit cannot be fetched. It runs a review or
  waits, as for a `review.query` match, or records `canopy review end --pr URL --reason merged|closed|unknown_repo`,
  which needs `CANOPY_TICK_ID` and an open request; otherwise the request would stay open, and be read, every tick. A
  steered overseer could end one early; that costs a review, never adds one, and the PR's page shows who ended it and
  why.
- A review that ends other than `done` leaves the request open for a retry within the per-PR limit. Every guard of
  `canopy review run` holds unchanged.
- What follows is what follows a `review.query` review: findings in the journal, posted nowhere (D114), no worker, no
  ticket, and `review.ended` (§20). A PR from a fork is reviewed like any other: its commit is fetched from the
  repository's `origin`, and nothing is pushed.
- Not settled: `REPO#N`, which needs a PR's URL from the repository's map (M14's references); whether a requested PR's
  review waits for its checks to pass, left to the overseer's `wait` for now.

### Attention

- `review_failed`: a PR's latest review run ended `failed`, `unknown`, `timeout`, or `crashed`. Recorded every tick
  that the PR is still a candidate and nothing newer has run; `canopy review run` may retry within the per-PR limit.
- `review_limit`: recorded by the refusal, and by the overseer every tick that a candidate PR's head is unreviewed and
  it is at its limit. Its detail ends with `canopy grant URL review` (§22), so raising `max_reviews_per_pr` for every
  PR is not the only way.
- Findings are not attention items. For an agent PR they lead to a `resume`, or the existing `needs_author` or
  `needs_reviewer` items.

`canopy attention --pr URL` names a PR with no ticket, or beside one for an agent PR. An item with only a PR is shown
and notified as `pr:<URL>`, which no ticket key can equal (§17).

### Reading reviews

`canopy review show` lists recent review runs, and `canopy review show ID` prints one in full, a dismissed finding
marked so, its text made printable (§22). It reads the journal only.

### Dismissing a finding

`canopy dismiss review:<ID> <N>`, or the web UI (§22), dismisses finding `N` of review run `ID`: a reviewer is wrong
often enough that the operator wants to rule a finding out before a worker spends a run on it.

- A dismissed finding stays listed, marked. It is left out of what `resume --review-run` hands the worker, which keeps
  the rest's numbers, and out of the state block's titles. A `resume` for a review whose findings are all dismissed
  refuses as `bad_review`, and the PR moves on as after a clean review.
- It is one run's finding: a finding has no id across commits, so a new commit's review starts fresh (Open, below).
  `--undo` takes it back.
- Refused `unknown` for a run or finding that does not exist or did not end `done` with findings, `bad_finding` for a
  number that is not 1 to 20, and `inside_run` as `reply` is: the overseer and agents cannot hold a finding back from
  a worker.

### Sending findings to a worker

`canopy send review:<ID> <N>...`, or the web UI (§22), is the operator's go-ahead on those findings of review run
`ID`. Only for an `own` review whose ticket's unit still has the PR it reviewed (`canopy forget` clears it). A review
of any other PR offers no send: no worker may push to it; publishing such a review on the PR is ROADMAP M43. It is a
reply, not a new channel: an operator message on the review's ticket, as `canopy reply KEY` would record:

```text
Address findings 1 and 3 of canopy's review run 12, of commit 9b2f4c6e1a7d. Leave its finding 2 alone.
```

- The next tick reads it as any operator message about review feedback (§7, D089): the overseer dispatches
  `resume --review-run ID`, and the worker addresses the findings the message names and leaves the rest. So it works
  whether or not `canopy:review` is trusted: untrusted, it is the go-ahead the findings wait for; trusted, it narrows
  what the worker addresses. A `resume` carries one review run's findings, so sends from two runs before a tick are
  dispatched one per tick, older first.
- The message names findings by number and never quotes them. A finding is the reviewer's text, which is data (T1);
  the message is the operator's, an instruction, so the reviewer's words never reach a prompt as the operator's.
- Refused `bad_finding` and `unknown` as `dismiss` is, `dismissed` for a dismissed finding, `not_ours` for a review of
  a PR that is not the loop's own, and `inside_run` as `reply` is: an agent that could send findings could start work
  in the operator's name. Sending the same again, from a retried form or the shell, records nothing new.
- Not settled, as for a dismissal: what was sent from one commit's review is not carried to the next commit's.

### The diff

The web UI's review page shows each finding on the reviewed commit's diff, so the review keeps that diff. The web UI
reads reviews and writes only a finding's dismissal and findings sent to a worker (above).

- **Taking it.** After the checkout, the review writes the diff from the commit's merge base with the pool's base
  branch, beside the run's log, readable only by the operator. Diff drivers and textconv are off, since a commit's
  `.gitattributes` can name them, and git runs as the harness always runs it (D107). It is size-bounded and best
  effort: a failure is logged, the review goes on, and its page has no diff. A PR stacked on another branch shows that
  branch's commits too, since the PR's own base is not something the harness can read (principle 5).
- **Why the harness keeps it.** The page cannot ask GitHub (principle 5), and the slot is gone once the review ends.
  The review's own checkout is the one moment the harness has the commit, so the diff is taken then, of exactly the
  commit the reviewer read.
- **Reading it**: only a regular file opened without following links or blocking, bounded, control characters made
  spaces, a cut saying so. It is the PR's own text, rendered as text, never served as a file. It is the one response
  sent compressed: the event stream must never be, as gzip buffers it, and this body holds no secret beside the PR's
  and the reviewer's text that a compressed size could give away.
- **Anchoring.** A finding sits at the line its `location` names when the diff shows it, else under its file, else
  apart (ui/DESIGN.md).

### Agent definition

canopy ships `canopy-reviewer` in the definitions directory (§13), not the repository's `.opencode/agent/` (TRUST_MODEL
T7):

- no edits, no subagents, no bash; reads allowed only inside the checkout;
- MCP: the tracker and GitHub, read tools only. Tools that comment or reply anywhere, submit a PR review, push or write
  files, change labels, or edit or delete are denied by name.

A review that should run the PR's tests uses the operator's own copy of the definition, with bash allowed for exactly
those commands, as a chore does (§19). That runs the PR's code on the operator's machine, a reason to keep
`review.query` to PRs whose authors they trust.

### Journal

Each review run (its PR, commit, ticket if any, purpose, slot, base branch, status, validated result, and cost, a
timed-out reviewer's included, §13), kept apart from worker runs, which are keyed by ticket and branch; decisions that
name a PR; finding dismissals; and review requests, kept once ended.

### Trust model changes

Recorded in TRUST_MODEL with M11's human approval: T1 (the reviewer reads the most hostile text; what it writes is
data; `review.query` authorizes and is private), T3 (`max_reviews`, `max_reviews_per_day`, `max_reviews_per_pr`,
one review per commit, and the review timeout are controls in code), T4 (the harness runs nothing from the checkout,
and the reviewer's working directory is outside it), T6 (the reviewer has no write tool; what it read leaves only
through the journal and a resumed worker's prompt), T7 (every review key private except
`policy.max_reviews_per_pr`), §6 (never submit a PR review; never push to or edit a PR the loop is only reviewing),
and §7 (a reviewer definition that runs commands runs the PR's code). D114 removed the review comment and its T5
marker. M42 adds: T1 (a review request authorizes a review as `review.query` does, made only through the operator's
channels and refused inside a run), T8 (making and ending one are among the web channel's writes), and §7
(`review.query`'s note on other people's PRs covers requests too).

### Open

- How a finding is followed from one commit's review to the next, so a dismissal, or findings sent to a worker,
  could outlast its run.
- A repository-offered review rubric, such as its own `low_impact`, that an operator opts into by name.
- Whether OpenCode confines the reviewer to its `checkout` link. The opt-in reviewer canary settles it. If not, the
  reviewer runs without a checkout and reads the PR only through MCP.
