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

Chores are user-only (§12); one in a workspace file is a config error (TRUST_MODEL T7).

```toml
[runtime]
# the default
chore_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-chore --format json
    --title={title} {prompt}'''

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
timeout_minutes = 20
cwd = "~/src/build-tools"
workspaces = ["acme"]     # optional; default every workspace
```

- A chore name matches `[a-z][a-z0-9-]*`.
- `prompt` (required) is the operator's file, absolute or starting with `~` like every `paths.*` value.
  `examples/chores/build-health.md` is one to start from: it checks CI through the GitHub MCP server's read tools, so
  it runs under the shipped `canopy-chore`. `examples/chores/README.md` lists more chores to write, and what not to.
- `cmd` follows §12 (`{prompt}` exactly once, no shell); default `runtime.chore_cmd`. A chore using the operator's own
  tools needs its own agent definition (below), so `cmd` is usually set.
- `every_minutes`, at least 15, is the shortest time between two run starts. A guard, not a schedule.
- `days`, `hours`, and `timezone` (optional) say when a run may start, checked in code. `days` lists `mon` to
  `sun`, empty for every day; `hours` is `HH:MM-HH:MM`, ending after it starts on the same day (`24:00` is the end
  of the day); `timezone` is an IANA name, by default the machine's local time. They bound only a run's start: one
  running when the window closes runs to its end or timeout.
- `when` (optional) is plain language for the overseer: when a run is worth it, pointless, or urgent. Without it the
  overseer runs a chore whenever due. Being operator-written, it is an instruction; nothing a chore reads is. Clock
  times belong in `days` and `hours`, which cost no judgment and no `wait` decision every tick.
- `timeout_minutes` defaults to 15. `cwd`, absolute or starting with `~`, defaults to `<state_dir>/chores/<name>/`,
  created readable only by the operator. The shadowing check (§13) covers `cwd` and every directory above it before
  the agent starts: OpenCode config there that defines one of canopy's agents makes the run `crashed`.
- `workspaces` names workspaces by their map's `[workspace] name` (§18). Empty (the
  default) means every workspace whose loop reads the user file. A chore in two workspaces runs in each, each with its
  own journal.

### Off unless configured

- No `[chores.*]` tables: the state block has no `chores` key (the overseer prompt skips its chore paragraph), no chore
  decisions are recorded, and `canopy chore run` refuses as `unknown_chore`. Ticket handling is unchanged.
- `capacity.max_chores = 0` turns every chore off the same way without deleting any.
- Deleting a chore's table turns it off. Only configured chores reach the attention list, so its findings and
  `chore_failed` item go at the next render and are notified as resolved (§14). Its `chore_runs` rows stay.
- Chores never affect what the overseer does with tickets: they cannot cause or prevent a dispatch.

### Agent definitions and tooling

canopy ships `canopy-chore` in the definitions directory (§13): no edits, no subagents, no bash, and no MCP write tools
where the runtime can deny them by name. It can read the tracker and GitHub, including other people's PRs.

A chore using the operator's deterministic tools gets its own definition, copied from `canopy-chore` into the
operator's runtime config (for OpenCode `~/.config/opencode/agent/`, never the repository's `.opencode/agent/`), with
bash allowed for exactly those tools:

```yaml
permission:
  edit: deny
  task: deny
  bash:
    "*": deny
    "buildq *": allow        # the operator's read-only CLI for the build queue
```

The operator installs the tools, on `PATH` (`uv tool install`) or in a checkout `cwd` points at. CI credentials belong
to the tools or the runtime's MCP servers (§4, principle 5); canopy never sees them and knows nothing of Jenkins or any
CI system.

### Delegation

- The state block's `chores` lists per configured chore: name, `every_minutes`, `when`, `due_at` (earliest time the
  `not_due` and `outside_hours` guards allow a run: `every_minutes` after the latest start, moved to when the window
  next opens), whether running, latest run (id, status, start, end, summary), and open findings (id, title,
  link) from its latest `ok` run, which a later non-`ok` run does not replace.
- Each tick the overseer decides each chore past `due_at` and not running. It runs it with
  `canopy chore run <NAME> [--context '<text>']`, or records `canopy chore wait <NAME> --rationale "<text>"` when
  `when` says not now. Chores not due need nothing.
- `--context` follows §8: at most 2000 characters pointing at what to look at, never quoting untrusted text. Empty
  renders as "None."
- Findings inform only decisions about the chore, never about tickets (see Open).

`canopy chore run` requires `CANOPY_TICK_ID` like `dispatch` (D020) and refuses, recording `refused:<guard>`, on the
first of:

- `unknown_chore`: no such chore in the user config, not for this workspace, or `max_chores` is 0.
- `running`: a run of this chore is running.
- `not_due`: less than `every_minutes` since this chore's latest run started, however it ended.
- `outside_hours`: now is outside the chore's `days` and `hours`, in its `timezone`.
- `chore_capacity`: `capacity.max_chores` chore runs are running.

A dry run checks the same guards, counting chores it already ran as running, records `dispatch:chore` with rationale
`dry run: not dispatched` or the refusal, and starts nothing (D036). A live run's rationale is `chore run <id>` plus
any context. `canopy chore wait` refuses an unconfigured chore and records nothing. Chore decisions (`dispatch:chore`,
`wait`, `refused:<guard>`) are `decisions` rows with the chore in the `chore` column and no ticket key. `dispatch.lock`
serializes chore runs with dispatches.

### Runs

`canopy chore run` inserts a `chore_runs` row, renders the prompt, and spawns `python -m canopy _chore <run_id>`
detached, like `_run` (§8 step 4). `_chore` claims the run by pid, drops `CANOPY_TICK_ID`, runs the command in `cwd`
with the timeout, records the agent's pid, parses the result, and closes the row. Output goes to
`<state_dir>/chore-runs/<name>/<run_id>.log`. No lease, branch, or push, so nothing to return or verify. Run files are
kept by chore, and out of `<state_dir>/chores/<name>/`: that is the agent's working directory, which a sandbox lets it
write (HOST_ISOLATION), and its own log and prompt are not its to read back or rewrite. A run's prompt is found beside
the log its row names, so a run started before this layout reads its prompt where it was written.

The prompt is the operator's file plus a generated `## Run` section holding one JSON object: chore name, current time,
run id, the overseer's context, the operator's notes (below), the latest ended run (id, status, end time, summary), the
latest `ok` run's open findings (id, title, link), so ids can be reused, and the result contract. It is written to
`<state_dir>/chore-runs/<name>/<run_id>.prompt`, readable only by the operator.

Result contract, one JSON line, last line of the agent's text (§13):

```json
{"status":"ok|failed","summary":"one paragraph",
 "findings":[{"id":"flaky/checkout-service/test_retry","title":"one line","detail":"a paragraph","link":"https://..."}]}
```

- `ok`: the check ran; no findings means nothing needs a human. `failed`: it could not check, and the summary says why.
- A finding's `id` is stable across runs for the same problem, matches `[A-Za-z0-9][A-Za-z0-9_.:/-]*`, at most 200
  characters, unique within a run. `title` is one line cut at 200, `detail` cut at 2000, `link` absent or a plain
  `https://` URL of at most 500. `summary` is cut at 2000. At most 20 findings.
- Validated with pydantic (D026). Anything else is `unknown`, with no findings recorded.

`chore_runs` status is `running`, `ok`, `failed`, `unknown`, `timeout`, or `crashed`. Reconcile (§6 step 3) treats
them like worker runs: a dead `_chore` pid gets the agent's process group killed and the run `crashed`. Chore runs do
not count against `max_workers`.

### Notes from the operator

`canopy reply chore:<NAME> '<text>'`, or the note form on the chore's page in the web UI (§22), records a note to a
chore: a message on its subject (§22), from the operator, refused `unknown` for a chore not defined for this workspace
It is how the operator answers a finding without editing the prompt file: "leave out flaky/checkout/test_retry until
2026-10-15, the fix is merging".

- Every later run's `## Run` section, a try's included, carries the latest 10 notes as `operator_notes` (id, time,
  text), oldest first. The prompt tells the agent to follow them as it follows the operator's file, a later note
  winning over an earlier one. They are the operator's words, so they are instructions; the overseer's context is not.
- Nothing clears a note, since one meant "until" a date must outlast a run; it falls out after 10 newer ones. A note
  saying "until" a date is the agent's to compare
  against the run's `now`. To take one back, write a newer note.
- Notes reach neither the overseer's state block nor the attention list, and do not wake the loop.
- `canopy show chore:<NAME>` lists them after the open findings, and the web UI's chore page beside them.

### Trying a chore

`canopy chore try <NAME> [--context '<text>'] [--no-record]` is the operator's, for writing a chore and for running one
now. It runs the chore in the foreground, in the `canopy chore try` process itself, through the same code as `_chore`:
its command in its `cwd` with its timeout and the shadowing check, its result line validated. It prints the agent's
text, its stderr and exit code, the validated result, what it cost when the runtime reported it, and the status, and
exits 0 only on `ok`.

- It is a real run. It inserts a `chore_runs` row with no tick (`tick_id` NULL), writes its prompt and log files, and
  closes the row as `_chore` does, so its findings become the open findings, a failure raises `chore_failed`, sinks
  get its `chore.ended`, its cost counts, and the chore's next run is `not_due` counting from it. It records no
  decision, as there is no tick.
- `--no-record` writes nothing: no `chore_runs` row, no prompt file, no notification, no cost. The prompt has `run_id`
  null, and the next tick sees no change. It is for drafting a prompt of a chore with open findings, which a recorded
  try of a half-written prompt would clear.
- Operators expected a run they started by hand to show up where the loop's runs do; one that vanished read as lost.
  So recording is the default, and leaving the journal alone is what the operator asks for.
- No guard on time or capacity applies, so a chore being written does not wait out `every_minutes` or its hours, and
  it works with `capacity.max_chores = 0`, so a chore can be written before the loop runs any; its findings reach the
  attention list once `max_chores` is above 0 (Off unless configured, above). It still needs a chore defined for this
  workspace.
- A recorded try refuses `running` while a run of the chore is running, and takes `dispatch.lock` to insert its row,
  so it never overlaps one the overseer started. `--no-record` does not refuse. Reconcile treats a try's row as any:
  its pid is the `canopy chore try` process, and a try killed with SIGKILL is marked `crashed` at the next tick.
- It refuses `inside_run`, like `start` and `reply` (§22), and the agent sees `CANOPY_RUN_ID=chore-<run id>`, or
  `chore-try` unrecorded. The overseer's bash allows only `canopy ...`, which cannot unset `CANOPY_TICK_ID`, so the
  loop cannot try a chore.

### Findings on the attention list

- Open findings are those of the chore's latest `ok` run; one disappears when a later `ok` run omits its id (§14). A
  non-`ok` run leaves them standing.
- A latest run ended `failed`, `unknown`, `timeout`, or `crashed` also raises a `chore_failed` item, after reconcile
  as for worker runs (§14), cleared by a later `ok` run.
- `attention.md` gets a section per chore after the ticket items, headed `chore:<name>`, one line per finding: title,
  link, age, id. Age runs from the first of the unbroken sequence of `ok` runs reporting the id. `canopy status` lists
  them the same way plus a line per configured chore: running, or latest run and next due time.
- Notification follows §14, keyed by chore and finding id. Line: `+ chore:<name> <id>: <title> <link>`. Its
  `notifications` row holds `chore:<name>` in `ticket_key` (no ticket key has a colon, §17) and the id in `reason`. A
  `chore_failed` row also holds `chore:<name>`; its line is `+ chore:<name> chore_failed: <detail>`.

### Journal

- `chore_runs`: id, tick id (NULL for a run `canopy chore try` recorded), chore name, pid of `_chore` (or of the
  try), pid of the agent, started and ended times, status, `result_json` (validated result, text cut to limits), log
  path, and what the runtime reported (§13): `session_id`,
  `cost_usd`, and tokens by kind, as `runs` has them, NULL when it reported nothing. Separate from `runs`, whose
  ticket, slot, lease, and branch columns do not apply. `canopy show chore:<NAME>` shows the latest run's session and
  cost, and the web UI's spend counts chore runs.
- `decisions.chore`: nullable; a row carries a ticket key or a chore name, never both.

### Trust model changes

Approved with M9:

- T1: chores read text from outside the operator's queue (other people's PRs, build logs). Findings are data
  everywhere: attention list, notification, state block.
- T3: `every_minutes`, `running`, and `capacity.max_chores` are controls in code; §6: never run a chore more often than
  its `every_minutes`, or more than `capacity.max_chores` at once.
- T6: a chore's only output is its result line; the shipped definition has no write tools. Residual: a steered chore
  can put up to 20 findings of its choosing before the operator and into `notify.cmd`, and a link can carry data.
- T7: chores, `runtime.chore_cmd`, and `capacity.max_chores` are user-only.
- §7: the operator is responsible for any tool allowed in a chore's definition. canopy assumes chore tools only read.

### Open

- Whether a chore should ever write (acting on others' work, which D010 kept out). Likely first: a ticket for a
  finding, without a queue label like a split child (§18), so a human decides.
- Whether findings should inform ticket decisions once chores have a track record (a flaky-check finding raising
  attention instead of dispatching `fix-ci`). Only to hold work back or raise attention, never to make a ticket a
  candidate, and opt-in per chore.
- Whether `workspaces` should become a per-workspace table in the user file.
- Whether a repository should offer chores operators opt into by name, as it offers its tracker query.

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

[notify.sinks.phone]
cmd = "curl -sS --fail --data-binary @- https://ntfy.sh/my-private-topic"
format = "text"
```

- Sinks are user-only (§12), like every `notify.*` key (TRUST_MODEL T7).
- A sink name matches `[a-z][a-z0-9-]*`. At most 5 sinks, since each can hold the tick lock for its timeout.
- `cmd` follows `notify.cmd`'s rules (§12): split into argv, no shell, no `{prompt}`. It runs in the workspace root
  with the message on stdin and a 60-second timeout. Exit 0 means delivered; anything else, timeout included, means
  retry next tick. Stdout is ignored; the tail of stderr is logged.
- `format` is `json` (the default) or `text`.
- `events` lists the groups the sink receives: `attention`, `loop`, `runs`, `chores`, `reviews`. Default
  `["attention", "loop"]`.
- `digest_every_minutes` is optional and at least 60 (Digest, below).
- `notify.cmd = "X"` is shorthand for a sink named `default` with `cmd = "X"`, `format = "text"`,
  `events = ["attention"]`, and no digest. Setting both `notify.cmd` and `[notify.sinks.default]` is a config error.

An event is recorded only when some sink takes its group; with no `notify.cmd` and no sinks, publishing is §14
without the notification.

### Events

A closed set, written by the harness from the journal. Text fields are cut to the limits shown, on one line.

| Group | Kind | When | Fields |
|---|---|---|---|
| `attention` | `attention.opened` | a listed item the sink was not told of | ticket, title, reason, detail (500), since |
| `attention` | `attention.resolved` | an item the sink was told of left the list | ticket, title, reason |
| `runs` | `run.started` | dispatch started a worker | ticket, title, run, kind, branch, attempt, limit |
| `runs` | `run.ended` | a run's row closed | ticket, title, run, kind, status, branch, pr, prs, summary, question, message |
| `chores` | `chore.ended` | a chore run's row was closed (§19) | chore, run, status, summary, how many findings |
| `reviews` | `review.ended` | a review run's row was closed (§21) | pr, ticket, title, run, status, verdict, impact, how many findings |
| `loop` | `loop.failing` | the latest 3 ticks all ended other than `ok` | count, latest status and tick, its log |
| `loop` | `loop.recovered` | the first `ok` tick after `loop.failing` | how many ticks failed |
| `loop` | `loop.sink_failing` | a sink has failed 3 deliveries in a row | sink, the tail of its stderr |

`summary` and `question` are cut at 300 characters, each PR URL at 500. `pr` is the run's first PR, `prs` every PR a
joint run reported. In the `json` format a run's kind is `run_kind` (`kind` is the event's). `question` is set only for
a `blocked` run; the needs-human label is not an attention item, so `run.ended` is how a sink hears of the question.
`message` is the journal id of the message the run recorded (§22): its question for a `blocked` run, its report
otherwise, so a channel can say what a reply answers.

Attention is a diff of state per sink (§14): `notifications` has a `sink` column, so each sink hears of each open
item once, and a sink that was down gets the net change. The other kinds are point events in an outbox table,
`notify_events`, written in the transaction that records the fact: dispatch inserting the run; whatever closes a run's
row (`_run`, or reconcile marking it `crashed`) or a chore run's (`_chore`, its reconcile); the publish step for
`loop.*`. Ids never repeat (`AUTOINCREMENT`), so pruning cannot reuse an id a cursor passed. Each sink's cursor in
`notify_sinks` is the last event id it delivered. `loop.failing` and `loop.sink_failing` are recorded once per
streak.

Because `notify.cmd` is the sink `default`, switching between the two re-notifies nothing. Without a `default` sink,
its rows go at the first publish like any removed sink's, and each named sink hears of every open item once.

### Delivery

§6 step 7, after `attention.md` is written, for each sink in name order:

1. Gather the sink's attention diff if it takes `attention`, its events after its cursor in the groups it takes, and a
   digest if one is due. If there is nothing, skip the sink, moving its cursor past events of groups it does not take.
2. Render one message in the sink's format and run the command.
3. On exit 0, record the diff in `notifications` for this sink, move the cursor to the newest event gathered, set the
   digest time, and reset the failure count. Otherwise change nothing else, log `notify command failed` with the
   sink's name, and count the failure; the third in a row records `loop.sink_failing` once, in the same transaction.
   A sink that takes `loop` hears of its own failing when it recovers.

Bounds:

- At most 20 attention lines and 20 events per message. The rest are counted in a closing line pointing at
  `attention.md` and `canopy status`, and count as delivered.
- Events over 24 hours old when a sink next succeeds are counted, not listed.
- A new sink's cursor starts at the newest event (no backlog); its first delivery lists every open attention item.
- A removed sink loses its `notify_sinks` and `notifications` rows at the next publish. Events every sink has passed
  are deleted after 7 days, except the newest `loop.failing` or `loop.recovered`, kept to tell a week-long streak from
  a new one. `loop.recovered` counts every failed tick of the streak.
- Sinks run in turn under the tick lock: each hung sink delays the next tick by up to 60 seconds.

### Digest

- A sink with `digest_every_minutes` gets a digest at its first delivery, then at the first delivery that long after
  the previous one.
- It covers the time since the previous digest (the first, one interval back), from the journal only:
  ticks by status; runs started, by kind; runs ended, by status, with each `done` run's ticket and PR and each `blocked`
  run's ticket; the open attention list, counted by reason, with the oldest item's age; the workers running now.
- It is sent even when nothing happened ("24 ticks ok, nothing ran, nothing needs you"): a missing digest shows ticks
  stopped, which canopy cannot report itself.
- No model writes it. A report needing judgment is a chore (§19), reaching sinks as `chore.ended` (`chores` group).

### Formats

`text` is lines for a person. Attention alone is exactly §14's message, so `notify.cmd` output is unchanged. Event
lines, then digest lines, follow the attention lines, then the closing path line. Without attention changes a message
starts `canopy: N events`, or `canopy digest` for a digest alone. Event lines start `>` for a run started, `<` for a
run or chore run ended, `!` for the loop's own events, `*` for a test.

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

`attention` is null for a sink that does not take it; `added` and `resolved` items also carry their `repo`. Each
event carries its fields and `line` (its text-format line); the digest its counts and `lines`. Every ticket key, in
`added` and `resolved`, an event's `ticket`, and the digest's `done` and `blocked`, has a `title` beside it: the
ticket's title as it is at delivery (§13), or null before the overseer names it. It is for display, so a reader knows
a ticket without looking its key up; `text` and `line` show the key alone, keeping §14's message as it was.
`omitted` counts what the bounds left out. `version` changes only on an incompatible change; sinks ignore unknown
fields. `text` serves a sink that only forwards a string.

Presentation is the sink's. The fields are the contract, and a sink that can show more than lines builds its own
message from them in its channel's native form, as the Slack sink does with Block Kit; `line`, `lines`, and `text`
are canopy's one rendering, for sinks that only forward a string and as a fallback. So the harness never learns a
channel's markup, and a new event kind needs fields a sink can present, not only a line. A sink shows a kind it does
not know by its `line`.

### The desktop sink

`canopy-notify-desktop` is a script in canopy's own install (`canopy.notify.desktop`), stdlib only (D035). It runs only
as a configured sink command, never inside the harness.

```toml
[notify.sinks.desktop]
cmd = "canopy-notify-desktop"
events = ["attention", "loop", "runs"]   # runs: a blocked worker's question arrives as run.ended
```

- It reads a `json` message's `text` field, or a `text` message as is. Body: the lines without the closing path line,
  at most 12 lines and 1000 characters. Title: `canopy`, or `canopy: <repository directory name>` from `json`.
- Linux: `notify-send --app-name=canopy -- TITLE BODY`. macOS: `osascript` with a fixed script reading title and body
  from its arguments. Neither is built into a shell command or script, so agent or org-member text runs nothing.
- Exit 0 when the tool succeeded, 1 when it failed, 2 when it is not installed or stdin is empty.
- From a release's single executable it runs with `SCIE_BOOT=canopy-notify-desktop` (§5). So that `cmd` can name
  it, README's install puts a script of that name on `PATH`; `--help` prints it:

  ```sh
  #!/bin/sh
  exec env SCIE_BOOT=canopy-notify-desktop /path/to/canopy "$@"
  ```

### The Slack sink

`canopy-notify-slack` is its own distribution, a uv workspace member (D041): `packages/canopy-notify-slack/`, module
`canopy_notify_slack`, stdlib only (`urllib.request`, `json`), importing nothing from `canopy`. `canopy` depends on it
and lists the `canopy-notify-slack` script in its `[project.scripts]`, so installing `canopy` puts it on `PATH`. A
release's single executable carries it too, run with `SCIE_BOOT=canopy-notify-slack` (§5); README's install puts
a script of that name on `PATH` so that `cmd` can name it, and `--help` prints it:

```sh
#!/bin/sh
exec env SCIE_BOOT=canopy-notify-slack /path/to/canopy "$@"
```

- It reads `json` on stdin, posts one message to a Slack incoming webhook, and exits 0 on 2xx, else 1 with Slack's
  reply on stderr. A rate-limited post is retried next tick like any failure.
- The webhook URL comes from a file: `--webhook-file PATH`, default `$XDG_CONFIG_HOME/canopy/slack-webhook`
  (`~/.config/canopy/slack-webhook`). The file must be a regular file (checked before it is opened), belong to the
  operator, be unreadable by group and others, and hold one `https://hooks.slack.com/` URL whose parsed host is that
  host; otherwise the sink exits 2 saying which. The URL is never in canopy's config, argv, journal, or logs.
- With `--channel ID` it posts with a token instead, for a workspace that disallows incoming webhooks or an app
  serving several channels: `chat.postMessage` to `https://slack.com/api/`, the token
  as a bearer header, `{"channel": ..., "text": ...}` as the body. The token comes from `--token-file PATH`, default
  `$XDG_CONFIG_HOME/canopy/slack-token`, under the webhook file's checks, and must be one `xoxb-` bot token (a user
  token acts as the operator with all its scopes). The channel must be an id or a name, `#?[A-Za-z0-9._-]{1,80}`.
  Success is a 2xx reply whose JSON has `"ok": true`, since the Web API answers 200 to a refused post
  (`not_in_channel`). The whole reply is parsed; only what a failure prints is cut, to 500 characters. `--token-file`
  without `--channel`, or `--channel` with `--webhook-file`, is a usage error, exit 2. The token is never in canopy's
  config, argv, journal, logs, or the sink's own messages; the channel is in argv, which is the sink's `cmd`.
- With `--channel`, `--username NAME` and `--icon-emoji :CODE:` post under that name and emoji instead of the app's
  (`username` and `icon_emoji` in the body), which needs the app's `chat:write.customize` scope. The name must be
  printable, not blank, and at most 80 characters; the emoji one code, optionally with a skin tone
  (`:wave::skin-tone-3:`). Either without `--channel` is a usage error, exit 2: an app's webhook ignores both.
- Message: Block Kit built from the fields (Formats, above): a header with the repository directory name, a line of
  counts, a section per attention item (ticket, reason, detail, and since when, as a Slack date in the reader's time
  zone), the resolved items together, a section per event led by an emoji for its status (ticket, kind, run, its PRs,
  summary, a blocked run's question quoted), and the digest as fields with its done and blocked runs. A ticket shows
  as its key in bold, then its title when canopy sent one. At most Slack's
  50 blocks, the last counting what was left out. The `text` the post also carries is the message as at most 45 lines,
  which Slack shows in notifications and where blocks cannot be shown.
- Journal text is escaped for Slack markup (`&`, `<`, `>`) and every text object is `verbatim`, so Slack parses no
  `@here`, `@channel`, person, or channel name in it, and nothing can disguise a link. Each URL in it is made a link
  that shows the URL itself; one holding `|`, which would take a label, stays text.
- Setup: create a Slack app with an incoming webhook for one channel, write its URL to the file with mode 600, add the
  `[notify.sinks.slack]` table, and run `canopy notify test slack`. With a token: give the app the `chat:write` bot
  scope, install it, invite the bot to the channel, write its `xoxb-` token to the token file with mode 600, and set
  `cmd = "canopy-notify-slack --channel C0123ABCD"`. For a name and icon of its own, add the `chat:write.customize`
  scope and `--username canopy --icon-emoji :evergreen_tree:` to `cmd`.

Two checks keep the network out of the harness (as D015 keeps processes in `canopy.infra.procs`): ruff's banned-api
rule (`TID251`) bans `urllib.request`, `http.client`, and `socket` everywhere in `src/canopy`, no exceptions, and
`tests/canopy/test_layers.py` fails on any import of `canopy_notify_slack` from `src/canopy`. The harness runs the
Slack sink only as a configured command.

### Commands

- `canopy notify test [SINK]` sends a `test` message to every sink, or one, now, outside any tick, and prints each
  result. It changes no cursor or table, and refuses when `CANOPY_TICK_ID` is set, so the overseer cannot page.
- `canopy status` shows a line per sink: last delivery, consecutive failures and last error, events waiting.

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
- Reminders for items open longer than some threshold.
- Links to tickets. `tracker.ticket_url` (§17) links them in the web UI; a sink's message could link its ticket too.
- A sink secret read from a command (a password manager's CLI) instead of a file.

## 21. Reviews

A review is an adversarial read of one PR at one commit by a fresh agent run, with no transcript of the author's run,
told to assume the change is wrong until the code shows otherwise. It reports a verdict and its findings to canopy's
journal, and posts nothing: no comment on the PR or the ticket, no GitHub review (D114). It never approves, requests
changes, pushes, or merges. Human review stays the gate (§3). The operator reads reviews with `canopy review show`
until the web UI shows them as a PR review of canopy's own (ROADMAP M32).

Two kinds of PR get reviews, and neither needs a ticket:

- **The loop's own PRs.** With `review.agent_prs` on, a ticket's PR is reviewed once its checks pass, before the
  overseer asks a human for review. Findings go back to a worker through `resume`, which carries them in its prompt.
- **PRs the operator names with `review.query`.** Reviewed and nothing else: the loop never pushes to them, fixes
  them, or opens a ticket for them. The review in the journal is the whole output, for the operator alone.

Why nothing is posted: a review on the PR speaks for the operator, in their name, to everyone who reads the PR, and
an adversarial reader is wrong often enough that the operator wants to see its findings before anyone else does. Kept
in the journal, a review costs the PR's audience nothing, needs no write tool, and cannot be forged by anything that
posts as the operator, since the loop never read reviews from the PR anyway.

### Configuration

Every review key is user-only (§12), except the per-PR limit, a shared policy the repository may only tighten
(TRUST_MODEL T7).

```toml
[review]
agent_prs = true
query = 'repo:acme/api is:pr is:open author:@me -is:draft'
low_impact = """Only docs, comments, or tests change; or one dependency moves by a patch version."""

[runtime]
# the default
review_cmd = '''env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-reviewer --format json
    --title={title} {prompt}'''
review_timeout_minutes = 20

[capacity]
max_reviews = 1            # review runs at once, within max_workers; 0 turns reviews off
max_reviews_per_day = 20   # review runs started in any 24 hours

[policy]
max_reviews_per_pr = 3     # shared; the repository may only lower it
```

- `agent_prs` defaults to false. `query` is the VCS host's PR search syntax, empty by default. Reviews are on when
  `max_reviews` is above 0 and either is set.
- `review.query` authorizes, unlike `tracker.query` (§17). Without an author filter it reviews other people's PRs in
  the operator's name; allowed, and the operator's choice (TRUST_MODEL §7).
- `low_impact` is plain language for the reviewer, like a chore's `when`: which changes it may call `low`. Without it,
  the reviewer never reports `low`.
- `review_cmd` follows the command template rules (§12). A different model from `worker_cmd` is recommended.

### Off unless configured

With no `[review]` table, neither `agent_prs` nor `query` set, or `capacity.max_reviews = 0`, nothing about reviews
reaches the overseer: no `reviews` key in the state block, §7's phase table unchanged, and every `canopy review run`
refuses as `reviews_off`. A test holds this. With `agent_prs` off the phase table is also unchanged, and a loop PR
that `query` matches is reviewed like any other match: a review in the journal, no `resume`.

### Running a review

`canopy review run --pr URL --sha SHA [--ticket KEY] [--repo NAME] [--context '<text>']` requires `CANOPY_TICK_ID` like
`dispatch` (D020). `URL` is the PR's `https://` URL, an opaque string the harness never parses. `SHA` is the full head
commit the overseer read. `--ticket` links an agent PR to its ticket. Under the dispatch lock, it refuses, recording
`refused:<guard>`, on the first of:

- `reviews_off`: see above.
- `bad_pr`: `URL` is not a plain `https://` URL of at most 300 characters, `SHA` is not 40 or 64 lowercase hex
  characters, or `--ticket` is not a valid key (§17).
- `unknown_repo`: no `--repo`, or one not in the map or with no clone. The slot comes from that repository's pool.
- `running`: a review of this PR is running, or, with `--ticket`, a worker run for that ticket is.
- `reviewed`: a review of this PR at this commit ended `done`. The refusal names its verdict and impact.
- `review_limit`: this PR has had `policy.max_reviews_per_pr` review runs, however they ended. Also records the
  `review_limit` attention item.
- `daily_limit`: `capacity.max_reviews_per_day` review runs started in the last 24 hours.
- `review_capacity`: `capacity.max_reviews` review runs are running.
- `capacity`: `max_workers` runs and review runs, together, are running.

A dry run checks the same guards, counting reviews recorded in this tick as running, records `dispatch:review` with
rationale `dry run: not dispatched; would review <SHA>`, and starts nothing (D036). Worker dispatches also count a
running review toward `capacity` (§8).

Once the guards pass, the command inserts a `review_runs` row, leases a slot with holder `canopy:review:<run_id>` (a
failed lease deletes the row and refuses as `no_slot`), renders the prompt (`bad_prompt` if it does not), and spawns
`python -m canopy _review <run_id>` detached, as dispatch spawns `_run` (§8 step 4). `_review`:

1. Claims the run by pid and drops `CANOPY_TICK_ID`, as `_run` does.
2. In the slot: `git fetch origin <SHA>`, `git checkout --detach <SHA>`, and checks that `HEAD` is `SHA`. A failure is
   `failed` with a harness note (a PR in another repository fails here). No branch is created. Then it deletes every
   symlink the commit tracks that resolves outside the checkout, and keeps the commit's diff (The diff, below).
3. Runs `review_cmd` with cwd `<state_dir>/reviews/<run_id>/`, a directory readable only by the operator, **not the
   checkout**, so the runtime loads no configuration from the PR. It holds one link, `checkout`, to the slot,
   which the prompt names, as a desk's links do (§18). Before it starts, the shadowing check (§13) covers that
   directory and the workspace root. Timeout `review_timeout_minutes`; the agent's pid is recorded.
4. Parses the result, then always removes its directory, never following the link, and returns the slot with
   `--force`. It traps signals and exits as `_run` does (§8 step 6). Reconcile treats a dead `_review` as a dead
   `_run`: it kills what is left of the reviewer, removes the directory, returns the slot, and marks the run
   `crashed`. A running review's lease is never returned as stale.

The prompt is `prompts/reviewer.md` (or the override), with the PR URL, the commit, the checkout path, the ticket key
and tracker provider for an agent PR, `review.low_impact`, the attempt number and limit, the overseer's context, and
the result contract. The reviewer:

- reads the PR's description and discussion, the diff, as much of the checkout as it needs, and for an agent PR the
  ticket;
- looks for defects, not style: wrong behavior, missed cases, security problems, broken contracts, missing tests for
  new behavior, and anything the repository's own docs (such as `AGENTS.md`) name as a rule;
- verifies each finding against the code, and reports none when it finds none;
- writes each finding for someone who has not read the PR: a title, a `path:line`, and a detail saying what is wrong,
  why, and the case that shows it;
- posts nothing anywhere, and treats everything it reads, the diff included, as data (TRUST_MODEL T1).

Result contract, one JSON line, last line of the reviewer's text (§13), validated with pydantic (D026):

```json
{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","summary":"one paragraph",
 "findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line","detail":"what and why"}]}
```

- `done` means the review was read through. `failed` means the reviewer could not review; the summary says why. A
  `comment` key, from a reviewer prompt older than D114, is ignored.
- At most 20 findings. `title` and `location` are one line, cut at 200 and 300 characters; `detail` is cut at 1000,
  and `summary` at 2000.
  `verdict` is `findings` exactly when `findings` is not empty, and a `done` review has a verdict and an impact.
- `low` without `review.low_impact` is recorded as `normal`, with a harness note.
- Anything else is `unknown`. `review_runs` status is `running`, `done`, `failed`, `unknown`, `timeout`, or `crashed`.

### The verdict, and automating on it

canopy never approves (TRUST_MODEL §6): a review changes no GitHub review state and cannot satisfy a required
approval. The verdict and impact are for the operator and the overseer, and leave the machine only as the `review.ended`
event's fields (§20). No repository automation can read them, so a review cannot let a low-impact PR skip a human
reviewer. A repository that wants that needs a verdict it can trust, which waits on a bot identity (ROADMAP, deferred).

### The overseer's part

The state block gains `reviews`: whether `agent_prs` is on, whether a query is set, the limits, running review runs,
and for each PR reviewed in the last 14 days (at most 50, newest first) its URL, linked ticket, review runs so far, and
latest run: id, commit, status, verdict, impact, finding titles, start and end, and `reviewed_at`, its end in the
`review` cursor's form (§7).

For the loop's own PRs, the phase table (§7) gains two rows between `ci_red` and `green_unreviewed`, used only when
`agent_prs` is on. Findings are `review_findings` only when `trust.trusted_reviewers` lists `canopy:review`; otherwise
they are `untrusted_review` and wait for the operator's go-ahead like any untrusted reviewer's (§7, D089):

| Phase | Derived from | Next action |
|---|---|---|
| `review_pending` | checks pass, no approval, no `done` review of the head commit, under the per-PR limit | `canopy review run --ticket KEY` |
| `review_findings` | the head commit's `done` review has findings, newer than the `review` cursor | classify as review comments (§7): dispatch `resume --review-run <id>`, or `needs_author` |

A clean review, or a PR at its review limit, moves on to `green_unreviewed`, whose `needs_reviewer` item names the
latest review run. A `resume` pushes a new commit, which is reviewed again, up to the per-PR limit. The overseer knows a
review only from the state block. Nothing on the PR is one, and a review never counts toward `changes_requested`.

`canopy dispatch KEY --kind resume --review-run ID` hands the worker review run `ID`'s findings. The dispatch refuses as
`bad_review` unless the kind is `resume` and the run is this ticket's, of a repository the dispatch names, `done`, and
has findings. The worker's prompt carries them under `## canopy's review` as `{{REVIEW_FINDINGS}}`, each finding's
title, location, and detail made printable, and `None.` on any other resume. A prompt override without that
placeholder fails to render for a `--review-run` dispatch, so the findings are never dropped silently. The worker
treats them as a trusted reviewer's comments when `canopy:review` is trusted, and never posts them; there is no comment
to reply to. The `review` cursor's time for a review run is its `reviewed_at`.

For PRs from `review.query`, the overseer runs the query each tick and keeps only PRs of this repository (the one whose
PRs it reads for tickets); `_review` could not fetch another repository's commit from `origin`. The prompt says so; a
`repo:` qualifier saves the reads. For each open match whose head commit has no `done` review, it runs a review or
records `canopy review wait --pr URL --rationale "<text>"` (say, checks still running, or a draft). Nothing else is
decided about these PRs.

Review decisions are `decisions` rows with the PR's URL in the `pr` column: `dispatch:review`, `wait`,
`refused:<guard>`, and `attention:<reason>`. An agent PR's rows also carry its ticket key.

### Attention

- `review_failed`: a PR's latest review run ended `failed`, `unknown`, `timeout`, or `crashed`. Recorded every tick
  that the PR is still a candidate and nothing newer has run; `canopy review run` may retry within the per-PR limit.
- `review_limit`: recorded by the refusal, and by the overseer every tick that a candidate PR's head is unreviewed and
  it is at its limit.
- Findings are not attention items. For an agent PR they lead to a `resume`, or the existing `needs_author` or
  `needs_reviewer` items.

`canopy attention` takes `--pr URL`, in place of a ticket key for a PR with no ticket, or beside one for an agent PR.
An item with only a PR is shown as `pr:<URL>`, and its `notifications` row holds that in `ticket_key`, which no ticket
key can equal (§17). The `reviews` event group (§20) carries `review.ended`: PR, ticket, run, status, verdict, impact,
and how many findings, never their text.

### Reading reviews

`canopy review show` lists the review runs of the last 14 days, newest first: id, start, status, verdict, how many
findings, impact, PR, and commit. `canopy review show ID` prints one in full: the summary and each finding with its
detail. Text the reviewer wrote is made printable, as any message shown on a terminal is (§22). It reads the journal
only, and runs outside a tick.

### The diff

For the web UI's review page (ROADMAP M32), which shows each finding on the diff at the line it names, `_review` keeps
the reviewed commit's diff. `GET /reviews` lists the latest review runs, and `GET /reviews/{id}` serves one with its
findings anchored on its diff and the diff itself (§22); both read only. The Reviews pages show them: the list, and
a review's page with each finding's card under the line it names, under its file's header when the diff does not
show the line, or in a panel of its own; nothing on them writes yet (Open, below).

- **Taking it.** After the checkout, `_review` fetches the pool's base branch, the slot's lease's `base_branch`, which
  `review_runs.base_branch` records, as `refs/heads/<base>`, and writes `git diff` from the commit's merge base with it
  to the commit beside the run's log, `<id>.diff`, readable only by the operator. Diff drivers and textconv are off
  (`--no-ext-diff --no-textconv`), since a commit's `.gitattributes` can name them, and git runs as the harness always
  runs it (D107). It is cut at 4 MiB. It is best effort: a base branch origin does not have, or any other failed step,
  is logged, the review goes on, and its page has no diff. A PR stacked on another branch shows that branch's commits
  too, since the pool's base is not the PR's; the PR's own base is not something the harness can read (principle 5).
- **Why the harness keeps it.** The page cannot ask GitHub (principle 5), and the slot is gone once the review ends.
  The review's own checkout is the one moment the harness has the commit, so the diff is taken then, of exactly the
  commit the reviewer read.
- **Reading it** (`core/review_diff.py`) on each request: only a regular file opened without following links or
  blocking, at most 4 MiB to its last whole line, at most 500 files and 30,000 lines, each line cut at 1000
  characters, control characters but tabs made spaces. A cut says so. It is the PR's own text, rendered as text.
- **Anchoring.** A finding's `location`, `path:line` (also `path:L12` or `path:12-14`, taking the first line), falls on
  a file whose new or old path is that path, or whose path ends in `/<path>` when only one does, and on the line with
  that number on the new side, when the diff shows it. A finding on a file the diff shows, but not on a line it shows,
  sits under the file's header; one on no file in the diff, or with no diff, in a panel of its own.

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

- `review_runs`: id, tick id, PR URL, commit, ticket key (nullable), slot, lease id and holder, the base branch it was
  leased on (nullable, 0016), pid of `_review`, pid of
  the agent, started and ended times, status, `result_json` (validated, text cut to its limits), log path, and what
  the runtime reported (§13): `session_id`, `cost_usd`, and tokens by kind, as `runs` has them, NULL when it reported
  nothing. A timed-out reviewer records what its finished calls cost. Separate from `runs`, which is keyed by ticket
  and branch. The web UI's spend counts review runs.
- `decisions.pr`: nullable.
- The `review` cursor (§7) also covers review runs: a `resume` for a review's findings passes
  `--cursor review=` with the run's `reviewed_at`.

### Trust model changes

Recorded in TRUST_MODEL with M11's human approval: T1 (the reviewer reads the most hostile text; what it writes is
data; `review.query` authorizes and is user-only), T3 (`max_reviews`, `max_reviews_per_day`, `max_reviews_per_pr`,
one review per commit, and the review timeout are controls in code), T4 (the harness runs nothing from the checkout,
and the reviewer's working directory is outside it), T6 (the reviewer has no write tool; what it read leaves only
through the journal and a resumed worker's prompt), T7 (every review key user-only except
`policy.max_reviews_per_pr`), §6 (never submit a PR review; never push to or edit a PR the loop is only reviewing),
and §7 (a reviewer definition that runs commands runs the PR's code). D114 removed the review comment and its T5
marker, with the operator's approval.

### Open

- Showing a review as a PR review of canopy's own, findings on the diff's lines, in the web UI (ROADMAP M32), and
  what the operator does from there: dismiss a finding, or send it to a worker.
- A repository-offered review rubric, such as its own `low_impact`, that an operator opts into by name.
- Whether OpenCode confines the reviewer to its `checkout` link. The opt-in reviewer canary
  (`tests/canopy/test_opencode_canary.py`) settles it. If not, the reviewer runs without a checkout and reads the PR
  only through MCP.
