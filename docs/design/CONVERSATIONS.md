# Conversations

Part of the canopy design, normative like all of it: the journal's conversation, private tickets, its channels, and the
web UI. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Chores,
notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md). Next: [Flaky CI](FLAKY_CI.md).

## 22. Conversations

Private tickets and the journal's conversation (ROADMAP M18), tracker comments in the journal (M19), the web UI's
pages and actions (M20), its chores (M23), and its ticks (M24) are built. Rationale in D072 to D076 and D081.

The journal is the one record of every ticket's conversation: what workers reported and asked, what people replied,
and where each came from. A **channel** is a way into or out of that record: the tracker, the CLI, the web UI, and
Slack later. Channels differ in how they reach the operator and how they prove who wrote a reply. The overseer and
workers never see which channel a message came from, so adding a channel changes no prompt.

A ticket is **public** when one of `tracker.labels` authorizes it, as today, and **private** when the operator starts
it in canopy (below). A started ticket is private whatever labels it carries: the start record wins. A private
ticket's conversation never touches the tracker: the operator can deliver a ticket a client filed without the agent's
reports, its questions, or the operator's answers appearing on it.

### Messages

A `messages` table, one row per message:

- its subject (below): a ticket now, a PR with M14; the journal id (`AUTOINCREMENT`, so ids never repeat); and the
  time canopy recorded it.
- `source`: `worker` (from a run's result line), `operator` (from a channel that authenticated the operator), or
  `tracker` (a tracker comment the overseer mirrored, M19).
- `kind`: `report` or `question` for a worker's, `reply` for the operator's, `comment` for a mirrored one.
- `channel`: `run`, `cli`, `web`, `slack`, or `tracker`.
- For a worker's message, its run. For a mirrored one, the tracker's comment id, author account id, and time, unique
  per subject and comment id.
- The body, bounded: a worker's text as its result contract bounds it; the operator's at 4000 characters; a mirrored
  comment's at 2000, marked truncated when cut.
- `answers`: the id of the message a reply answers, when the channel knows it.
- For an operator's message, a submission id, unique per subject, so a retried submission records nothing new. The
  web form carries one generated when the form is rendered. The CLI derives it from the subject, the message being
  answered, and the body, so rerunning the same `canopy reply` after an uncertain result is the same submission.

Who writes:

- `_run` records a run's `report` (its summary and PRs) and, for a `blocked` run, its `question`, in the transaction
  that closes the run's row, for every ticket. The harness already has both from the result line (§8), so no agent
  gains a write.
- Operator input goes through one function in `core/conversation.py` that every channel calls, with the guards in one
  place: the key is valid (§17), the ticket was started, the body is within its bound.
- Mirrored comments are recorded by the overseer (M19, below), a worker's marked comments among them. Migration 0004
  added their columns and the mirror cursor.
- Migration 0003 backfilled a `report`, and a `question` for a `blocked` run, from every ended run's `result_json`,
  so tickets worked before M18 have a conversation too.

Agents never write a message directly. No worker command records one, and the overseer records only mirrored tracker
comments, which authorize nothing.

### Authority stays with the source

The journal is what the operator reads. Authority comes from where a message originated:

- **Public ticket.** Authorization and replies are as §7 and §17 say: the overseer's live read of the tracker. A
  mirrored comment is the overseer's claim, like `--label`; it never makes a ticket `human_replied`, authorizes a
  split, or counts as "try again" after a failed run. The operator may also reply in canopy (D089): an operator
  message is canopy's own fact, as on a private ticket, and is how the operator answers an untrusted reviewer (§7). It
  stays in the journal and never reaches the ticket.
- **Private ticket.** The journal is the source. Its start record and the operator's messages are canopy's own facts,
  written after a channel authenticated the operator, so the harness checks them in code without reading the tracker
  (D003). Tracker comments on a private ticket are data, whoever wrote them.

This is principle 1's split applied to conversation: for a private ticket the journal owns the conversation, and for
a public one the tracker does and the journal holds a copy.

### Private tickets (M18)

The operator's commands are top-level verbs that take a reference to a subject, anything canopy works on or reports
about, so the same verbs serve tickets now, PRs with M14, and what comes later (References, below; D075):

| Command | Does |
|---|---|
| `canopy start REF` | work it privately, in place of a queue label |
| `canopy stop REF [--now]` | no new dispatches; a running run finishes unless `--now` ends it |
| `canopy reply REF [TEXT]` | answer it, with TEXT or stdin |
| `canopy forget REF` | forget its branch and PRs, so its next `implement` starts over (below); public tickets too |
| `canopy grant REF KIND [--repo NAME] [--runs N]` | allow one unit N more runs of KIND, default 1 (below); public tickets too |
| `canopy grant URL review [--runs N]` | allow the PR at URL N more review runs, default 1 (below, §21) |
| `canopy show REF` | its phase, PRs, recent runs, and conversation, oldest message first |

`canopy status` lists what was started, with each subject's phase, beside the attention list and runs; there is no
separate `list`.

- `start` is private by construction: canopy cannot label a ticket (D003), so a ticket started in canopy keeps its
  conversation in the journal. The command says so when it runs, and when the next tick will pick the ticket up. A
  later `--public` could start a ticket whose conversation stays on the tracker; none is planned.
- `stop` without `--now` is graceful: it says which run is still going and that it will finish. With `--now` it also
  ends that run: its process group is killed and its slots returned and desk removed as reconcile does for a
  crashed run (§6), and the run is marked `stopped`, a status that raises no attention item and counts toward attempt
  limits like any ended run. `stop` refuses a ticket that was not started: a public ticket stops when its queue label
  is removed.
- `stop` does not delete the start record; it marks it stopped. A stopped ticket stays private and is dispatched
  by nothing, whatever labels it carries, until `canopy start` again: a queue label left on it never turns it
  public.
- The start record is the authorization. Only the operator's commands write it, short of T1's residual (below).
- A started ticket is private even when it also carries a queue label, or gains one later. The harness chooses the
  worker in code: `canopy dispatch` for a started ticket always renders the private prompt and runs the private
  definition, whatever the overseer passed.
- `stop` and `dispatch` cannot interleave. `dispatch` checks the start record and inserts the run's row in one
  write transaction, and `stop` marks the record stopped in one: whichever commits first wins, and `stop` reports any
  run the other committed. `_run` reads the record again before it starts the worker and ends the run `stopped` if the
  record is stopped.
- The state block marks each started ticket and carries its operator messages newer than its message cursor. A
  stopped ticket is not among its tickets: the block names it in `stopped`, by key, and the overseer records no
  decision for it, where it once recorded a `wait` every tick for as long as the ticket stayed stopped. The key stays
  in the block so that a queue label left on the ticket does not make the overseer take it for a public one.
- `canopy dispatch` needs no `--label` for a started ticket. It checks the start record in code, a guard where a public
  ticket's `--label` is a claim (D051). `--kind split` on a private ticket is refused `private`: a split creates tickets
  in the tracker.
- The worker prompt has a private variant: no label check, since the harness checked the start record; never comment
  on, label, or edit the ticket; the result line's `summary` and `question` are the report. The agent definition is
  `canopy-worker-private`: `canopy-worker`, its MCP tools denied by name included (D084), with every tool of the
  tracker's MCP server denied by wildcard and only its read tools allowed by name, and the tracker CLIs canopy knows
  (`gh`, `acli`, `jira`) denied in its bash rules.
  - The server is `tracker.mcp_server` and its tools `tracker.read_tools`, both user-only, with a default for each
    shipped provider's usual MCP server (`config.DEFAULT_TRACKER_TOOLS`): `atlassian` with Jira's read tools for
    `jira`, and `github` for `github`, whose server is also the one PRs go through, so its list adds the PR tools a
    worker needs and leaves out every tool that writes to an issue. Both are rendered into the definition's
    permission block as `"<server>_*": deny` and then `"<server>_<tool>": allow` for each, so a write tool no list names
    fails closed, where denying write tools by a name pattern would leave an unexpected one open. OpenCode names an
    MCP tool `<server>_<tool>`, matches permission keys as wildcards on that name, lets the last matching rule win, and
    hides a tool whose last rule denies it outright (read in its source, 1.18.35); a live check of a private run is
    the operator's half of M18's acceptance.
  - Atlassian's Rovo MCP server lists only its primary tools unless its URL asks for `?tools=all`, and runs the rest
    through `execute*` tools that read or write by argument. OpenCode cannot see the argument, so those are denied:
    with the default URL a private worker reads the ticket with `getJiraIssue` and `searchJiraIssuesUsingJql` only.
  - With no read tools for the provider, `canopy start` refuses (`no_read_tools`) rather than run a worker that
    cannot read the ticket. A wrong list fails closed: the worker cannot read, ends `failed`, and posts nothing.
  - D044's guard grows for private runs: the harness refuses one when the worktree's OpenCode config has any
    `permission` or `tools` entry naming the tracker server's tools, since a repository rule merged after canopy's
    could reopen a write tool. The operator's own global config is the operator's to keep consistent (§13).
- Phases (§7) read the journal for the ticket's own phases: `needs_human` when the latest run ended `blocked` and no
  operator message came after it; `human_replied` when an operator message is newer than the ticket's message cursor
  (`last_message_id`), a cursor of its own over journal ids, never the comment cursor, which stays the tracker's. The
  action is `resume` with `--cursor message=<message id>`, its context pointing at the message. The PR phases are
  unchanged.
- The harness raises `awaiting_reply` every tick for a private ticket whose latest question has no operator message
  after it, with the question as its detail, as for the run reasons (§14). A public ticket's question still reaches the
  operator as
  `run.ended` (§20), whose `message` field is the id of the message the run recorded, its `question` for a `blocked`
  run and its `report` otherwise, so a channel can say what a reply answers.
- After `crashed`, `worker_failed`, and the other run reasons (§14), "try again" on a private ticket is an operator
  message after the run ended.
- `canopy reply` takes a started ticket, or a public one a tick has seen (it has a journal row); any other is refused
  `unknown`. On a public ticket the state block carries its operator messages newer than its message cursor under
  `operator`, and every public `implement`, `fix-ci`, and `resume` prompt carries the latest 20
  (`{{OPERATOR_MESSAGES}}`, at most 30,000 characters), each labeled the operator's: an instruction. The workers'
  questions come with them, labeled data, so a reply to message N names something the worker can read; the rest of the
  conversation is on the tracker (D093). The overseer's `--context` points at a message by id, never quotes it. A reply
  on a ticket with no branch yet rides its `implement`, and one after a failed run is "try again". Its authorized
  repliers' comments on the ticket still work as before (§7). `show` drops control characters from every message.
- A public worker can write to the ticket and its PRs, so keeping the operator's messages off them is its prompt's
  rule, not a guard (TRUST_MODEL T6). Text the ticket's readers must never see belongs on a private ticket.
- `start`, `stop`, `reply`, `forget`, and `grant` refuse when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set. `_run`,
  `_chore`, and `_review` set `CANOPY_RUN_ID` for their agents.
- The private worker runs with `runtime.private_worker_cmd`, a template of its own as `split_cmd` is. Its prompt
  carries `{{CONVERSATION}}`: the ticket's latest 20 messages, oldest first, at most 30,000 characters, each labeled
  the operator's (an instruction) or an earlier worker's (data). That is how a resumed worker reads the operator's
  reply; the overseer's `--context` points at the message id and never quotes it.
- A `canopy reply` answers the ticket's latest question, if any, and is idempotent on its submission id. Its body is
  stripped, and refused empty or over 4000 characters (`bad_body`) rather than cut.
- `canopy start` on a ticket the overseer marked done clears the done flag: the operator asked for it again. On a
  ticket with a public run still going, it says so: that run may still write to the ticket, and `_run` ends any public
  run that had not started its worker yet `stopped`.

### Forgetting a ticket's work

`canopy forget REF` has canopy drop a ticket's work so the loop starts it over (D086). It takes a ticket, public or
private, from the operator's shell or the web UI's Forget (below), and:

- refuses `unknown` for a ticket the journal has no row for, `running` while a run works it (wait for it, or end a
  started ticket's with `canopy stop --now`), and `split` for a ticket a split made children of: they are tickets of
  their own, and forgetting the parent would not undo them.
- clears the ticket's branch, phase, `needs_human_since`, and done flag, and deletes its units, with their branches,
  PRs, phases, and review and ci cursors. The next `implement` names a new branch with its `--slug`; from then on
  `bad_slug` (§8) binds to that one.
- records `forgotten_at` with the ticket's newest run and message ids, and the loop's reads skip what came before
  them: `last_run` in the state block, the run reasons on the attention list (§14), a private ticket's waiting question
  (`awaiting_reply`) and new operator messages, and a private worker's `{{CONVERSATION}}`. A reply after it answers
  nothing. A forgotten ticket reads to the overseer as one never dispatched, so its prompt is unchanged.
- keeps the rest. `runs` and `run_slots` stay, so the attempt limits and the fix-ci cooldown count every run, before
  and after (D030); a ticket at its implement limit needs `canopy grant` (below) or the limit raised in config, and
  `forget` says so. The comment
  and mirror cursors stay, so tracker comments already handled stay handled. The message cursor stays, and the boundary
  overrules it. The start record stays: a started ticket stays started, a stopped one stopped. `show` prints the whole
  history and when the work was forgotten.
- holds the dispatch lock, which a dispatch holds from its plan through its run's insert, so a dispatch that read the
  old branch cannot record it again after `forget` commits.
- touches nothing outside the journal. The old PR and the branch on origin are the operator's to close and delete, and
  the command names them: until they are gone the overseer still finds the `agent/<KEY>-*` branch (§7's `ready` needs
  none on origin) and dispatches to continue it, refused `no_branch`. A ticket stacked on the old branch (§10) loses
  its base when that branch is deleted, so forget a blocker only once nothing is stacked on it.

### Granting attempts

`canopy grant REF KIND` lets the loop keep working a ticket one of whose units is at its attempt limit (§8),
without raising the limit for every ticket. It takes a ticket, public or private, from the operator's shell only, and:

- takes `implement`, `fix-ci`, or `resume`. A split's limit is the ticket's, and only config raises it.
- names the unit with `--repo`, which may be left out when the ticket has had runs in one repository only. A repository
  it has had no runs in is refused `unknown_repo`, as is a ticket with no runs, and a ticket with no journal row
  `unknown`. A forgotten ticket's runs still name their repositories, so it can be granted though it has no units.
- adds a row to `attempt_grants`: the unit, the kind, `--runs` (default 1), and when. Rows are never changed or
  deleted. The unit's limit for the kind is `policy.max_<kind>_attempts` plus the sum of its grants of that kind, so
  lowering the policy lowers it too.
- resets no count: every run, before and after, still counts (D030). The command prints the unit's runs and its new
  limit. The state block shows the unit's `granted` counts beside its `attempts`, and the overseer compares against
  their sum (§6 step 4); a dispatch's attempt limit and the worker's `{{MAX_ATTEMPTS}}` include them.
- dispatches nothing. The next tick decides from the ticket's phase as usual, so the trigger a refused dispatch left
  (§8: cursors advance only once a worker starts) is still new, and a ticket whose last run failed still waits for a
  reply (§14).

`canopy grant URL review` does the same for a PR at `policy.max_reviews_per_pr` (§21), whose head the loop may not
review again. A PR's review limit is the PR's own, not a unit's, so it:

- takes the PR's URL, as `canopy review show` and the `review_limit` item name it, and no `--repo`. Review runs are keyed
  by that URL, so `REPO#N` is refused `bad_ref`, as is a URL canopy has never reviewed `unknown`. A ticket key with
  `review`, or a PR with any other kind, is refused `bad_kind`.
- adds a row to `review_grants`: the URL, `--runs` (default 1), and when. Only added to. The PR's limit is
  `policy.max_reviews_per_pr` plus the sum of its grants; no other PR's changes.
- resets no count (D030). The state block shows the PR's `granted` beside its `review_runs`, and `canopy review run`'s
  `review_limit` guard and the reviewer's `{{MAX_ATTEMPTS}}` include it. It reviews nothing: the next tick decides.

The web UI grants too (asked for by the operator, 2026-10-13: a ticket stuck at its limit sent them to the terminal),
through the same `policy.grant` and `grants.grant`, so with the same guards, and one run a click, where the stuck thing
is shown: a ticket's page and its attention item list each of its units' kinds at their limit, and the review limit of
each of its units' PRs canopy has reviewed, each with `allow one more`; a PR's page, and an item about a PR no ticket
owns, its review limit. A limit under its runs shows nothing, so the button appears only once the loop is held by it.
It needs no confirmation: one more run of a kind the loop already ran is the least a grant can do, the overseer still
decides whether to use it, and every guard on the run still holds. `--runs N` stays the CLI's.

### References

A reference names a subject by its shape, so no kind needs a flag and no form can be read as another's: a ticket key
(§17) has no `:`, `#`, or `/`.

| Reference | Subject | Verbs |
|---|---|---|
| `PROJ-123` | a ticket | all (M18), and the overseer's `mirror` (M19) |
| `api#42`, or the PR's URL | a PR | `grant` (its reviews, by URL); all, once PR-scoped work exists (M14) |
| `chore:NAME` | a chore (§19) | `reply` (its notes), `dismiss` (one of its findings), `show` |
| `run:ID` | a run | `show` |
| `review:ID` | a review run (§21) | `dismiss` (one of its findings); `canopy review show ID` shows one |

A verb a kind does not support is refused `unsupported`, naming the verbs it does. Messages and start records are keyed
by subject (its kind and id), not by ticket key, so a new kind adds a row here, not a table. Every form is parsed and
validated in code, as ticket keys are (§17).

### Tracker comments in the journal (M19)

The journal holds a copy of each ticket's tracker comments, so the operator reads every ticket's conversation in one
place, public or private (D081).

- Each tick, for every candidate, the overseer records each comment past the ticket's mirror cursor, oldest first:
  `canopy mirror REF --comment ID --author ACCOUNT --at TIME`, with the text on stdin, or `--body TEXT`. It requires
  `CANOPY_TICK_ID` like `dispatch` (D020) and takes a ticket reference; any other kind is refused `unsupported`.
- The text goes through a quoted heredoc, never an argument: the shell expands nothing in it. Its delimiter is the
  state block's `mirror.body_delimiter`, `CANOPY_BODY_` and 16 random hex digits drawn fresh each tick, so no comment
  can be written to end the heredoc early and run what follows. OpenCode checks a heredoc command's permission against
  its whole text, so the overseer's `canopy *` rule admits it (read in its source, 1.18.35); a body the shell parser
  reads as a command substitution is refused by the rule, failing closed, and the overseer then mirrors the comment
  as `(text not mirrored)`.
- Bounds, checked in code: a comment id as plain as a cursor id (`bad_comment`); the author an account id of at most
  200 printable characters without whitespace (`bad_author`); the time ISO 8601, read as UTC without an offset, and
  stored in the journal's own format (`bad_time`); the text stripped and not empty (`bad_body`; the prompt mirrors a
  comment without text as `(no text)`), cut at 2000 characters and marked truncated. At most 100 `mirror` calls a tick
  (`mirror_limit`), counted from the tick's `mirror` decisions, so a long history spreads over several ticks. Every
  refusal is recorded as a `refused:<guard>` decision.
- Idempotent on the subject and comment id (a unique index): a comment recorded again records nothing new, whatever
  text is passed the second time. Each call records a `mirror` decision in the same transaction, naming the message,
  or the message it already was, so the decisions show each comment mirrored once. The loop's tick block leaves
  `mirror` decisions out, as it does `wait`, and the tick's summary counts them.
- The harness reads the workers' marks (D069) itself: a comment that starts with `trust.comment_prefix` and ends with
  `trust.comment_suffix`, whichever are set, and whose last line is not a quote, is recorded with `source` `worker`;
  any other with `source` `tracker`. A worker's comment is recorded because its text can differ from the result line
  or come from a run whose result line never parsed. Either way it authorizes nothing: phases, `awaiting_reply`, and
  the loop's wake read operator messages only, and a private worker's prompt labels a mirrored comment as data, with
  its author's account id.
- The mirror cursor (`last_mirrored_id`) is its own, apart from the comment cursor the phases use, and only
  `canopy mirror` moves it, to the comment it records; `--cursor` cannot name it. It starts empty, so the first mirror
  of a ticket, including one worked before M19, covers its whole comment history once; worker comments the comment
  cursor had passed are recorded then. The state block carries it in each ticket's `cursors`.
- A dry run records the mirror too, as a record of what the overseer saw, but moves no cursor and changes no phase.
- `canopy show` lists a mirrored comment with its source, comment id, author, and time, and whether it was cut.
- The mirror lags the tracker by up to one tick. A comment edited or deleted after it was mirrored is not updated.
  PR review comments are not mirrored; they join the journal with PR subjects (M14).

### Waking the loop

During the wait (§6, the loop), each step checks the journal for the operator's acts: a message to a ticket recorded
since the last tick began; a ticket started or stopped (`starts`), or attempts or a PR's reviews granted
(`canopy grant`), since the last tick read the journal (or began, when it read nothing). A note to a chore (§19) does
not wake it: the chore's next run reads it. Nor does a config reload (§6). Any of those acts ends the wait and runs the
next tick, at most once a minute, whether idle pacing is on or not; the tick records what woke it in `ticks.woken_by`
(`message`, `starts`, `grant`) and is not idle. Every channel wakes it the same way, whether the act came from another
process (`canopy start`) or the loop's own server thread (D073). Capacity, attempt limits, and cooldowns hold as for any
tick. Before M28 only a message woke it, so a start from the web UI waited for the timer or a "tick now" (MEASUREMENTS
2026-10-12, F3).

### Channels

| Channel | In | Out | Proves the operator by |
|---|---|---|---|
| tracker | comments, mirrored (M19) | worker comments on public tickets | `trust.authorized_repliers`, read by agents |
| cli | `canopy start`, `stop`, `reply` (public tickets too), `forget`, `grant`, `dismiss` | `canopy show`, `canopy status` | the operator's shell (T1 below) |
| web (M20) | reply, start, stop, forget, grant; notes to chores (M23), dismissing chores' and reviews' findings; pause, resume | pages | the listener secret (TRUST_MODEL T8) |
| slack (later) | thread replies | §20's sink | Slack user ids the operator lists |

Outbound, every channel uses §20's events: a sink posts them, and the web UI reads the same journal.

### The web UI (M20)

Served by `canopy loop` from a thread (D073):

- On unless `--no-serve` or `serve.enabled = false`. `serve.bind` (loopback by default, or a private address) and
  `serve.port`. Every `serve.*` key is user-only (T7).
- It requires the operator's listener secret (T8, below). Without one the loop says why and how to make one, logs it,
  and serves nothing; the loop goes on. It serves plain HTTP, also on a private address: T8's "relies on the network"
  residual stands (D076).
- Each request opens its own journal connection, never takes the tick lock, and writes only through the functions the
  CLI uses: `conversation.start`, `stop`, `reply`, `forget`, and `dismiss` with channel `web` (a note to a chore is a
  `reply` on its subject, as `canopy reply chore:NAME` is), for a stop with `now`, the same `runs.halt.end` as
  `canopy stop --now`, for a grant `runs.policy.grant` and `reviews.grants.grant` as `canopy grant`, one run each,
  and `pause.pause` and `pause.resume` as `canopy pause` and `canopy resume` (§6). Reload on
  the settings page asks the loop to read its config again, as SIGHUP does (§6); it writes nothing, and the files stay
  the operator's to edit. A forget
  cannot be undone from the UI, so its request carries the ticket's key as the operator typed it, and the server refuses
  `not_confirmed` before reading anything when it does not match, so no client skips the challenge; one more click, as
  Stop now asks, is too easy to give by mistake. Its outcome
  names the branch and PRs canopy no longer tracks, as the CLI's does; the attempt-limit note is the CLI's alone.
  `serve` is a feature and cannot import `runs`, `reviews`, or `loop`, so the loop hands it that function and the
  attention list's (`loop.attention.listed`), a way to ask for a reload (`loop.reread`), and the grants with the
  limits they raise (`runs.policy`, `reviews.grants`), when it starts the server (`serve.backend`); a reload hands
  the server the new config, which each request reads as it opens. The one process it runs is
  `treehouse status --json`, for the worktrees page (below): it changes no lease, but it takes the pool's lock.
- A server failure is logged and the server restarted after 1 second, doubling to at most 60; it never ends the loop.
  Stopping the loop stops it, waiting at most 2 seconds for open streams.
- Pages: the attention list (the home page; most severe first rather than grouped by reason, beside the selected item's
  conversation and reply form, with the running runs under the list, below counters of running runs, questions waiting,
  and the list, `ui/DESIGN.md`), runs (running, then the 50 that ended last, each with a page and its session's
  transcript, below), worktrees (each pool's slots, below), tickets, each with its conversation and the decisions about
  it, pull requests (below), chores (below), ticks (below), and search (below). The side rail shows the runs working now
  and the spend of the last 24 hours and the last 30 days on every page, under the nav, so what the loop is doing and
  what it costs stay in view wherever the operator is.
  Actions: the CLI's verbs, reply, start, and stop (with or without `now`), granting one more run to what is at its
  limit (below), a note to a chore, dismissing a chore's finding or listing it again, and pausing and resuming
  the loop from the header on every page, which shows how long it has been paused, and reloading the loop's config
  from the settings page. OpenCode's session attach (M15) is
  not in the UI: a run's page shows its session id and, once it ends, its transcript (below), and attach joins once
  M15 runs workers against OpenCode's server.
- FastAPI on uvicorn (D074), serving a single-page app built from `ui/` (D079) and the JSON and SSE API it reads.
  uvicorn's `Server` runs in the thread, installs no signal handlers there (the loop's own handle Ctrl-C, §6), logs
  nothing to the terminal, and stops when the loop sets its `should_exit`. Request bodies and path parameters are
  validated with pydantic models and `conversation.parse_ref`, as everything else parsed from outside is (D026).
- Every value from the journal is escaped: tracker comments and agent output are untrusted text in a page that holds
  the operator's session. React escapes text it renders, and nothing renders journal text as HTML
  (`dangerouslySetInnerHTML` is never given it). No inline script built from data. Message bodies are sent with control
  characters dropped, as `canopy show` prints them. Run, chore run, and tick summaries and decisions' rationales are
  sent the same way, their line breaks kept, and a page lays them out (`RichText` in `ui/`): line breaks, lists,
  headings, `code`, and **strong**, read from the text by a small parser of canopy's own into React elements, not a
  Markdown library, which would render HTML and labelled links that need switching off. Any other markup, a labelled
  link's included, stays characters.
- An http or https URL in journal text (a message body, a run's or tick's summary, a rationale, an attention item's or
  finding's detail) is shown as a link whose text is the URL as written, opening in a new tab with no referrer (D113).
  No other scheme is linked, and nothing else in the text becomes markup but the layout above; a URL inside `code`
  stays text. A row that is itself a link (an attention item in the list) links nothing inside it.
- It lives in `src/canopy/serve/`, a features-layer package, the only one that imports `fastapi`, `starlette`, or
  `uvicorn`; `tests/canopy/test_layers.py` fails on an import of them anywhere else, as for click in `cli/`. The ban on
  `socket`, `http.client`, and `urllib.request` (§20) stays absolute: canopy's code opens no socket itself. It listens
  and calls out to nothing, so T2's "no outbound call" stands.

Signing in:

- The listener secret is `listener-secret` in the user config directory (`~/.config/canopy/`): one line of at least 32
  characters, in a regular file, not a symlink, owned by the operator, with no group or other permission bits.
  `canopy secret` writes one, 32 random bytes in URL-safe base64, and prints it; it never replaces one without
  `--rotate`. The loop reads it once, when it starts serving.
- The browser gets it from the operator: the sign-in page asks for it once, in a password field a password manager
  can keep. `POST {base}/api/session` compares it in constant time; a wrong one is answered after a second and logged.
- A right one sets a session cookie, `canopy_session_<port>`: `HttpOnly`, `SameSite=Strict`, path `{base}/`, for 30
  days. A cookie, not the secret held by the page, since `EventSource` sends no headers. Its value is its issue time and
  a random nonce, signed with the secret (HMAC-SHA256). The server keeps no
  session state, so a session outlives a loop restart, and a new secret signs every browser out. Signing out clears
  the cookie in that browser.
- The per-session token is a second HMAC over the same issue time and nonce. `GET {base}/api/session` gives it to a
  signed-in page, which sends it as `X-Canopy-Token` on every write.
- Every API route but `{base}/api/session` answers 401 without a valid session. A write (any method but GET and HEAD)
  also needs the token and an `Origin` header naming an allowed host: a same-origin request. The custom header makes
  a cross-origin write need a CORS preflight, which the server never grants.
- The app's own files (`index.html` and its assets) are served without a session: they hold no journal data, and the
  sign-in page is one of them.

The API, under `{base}/api`:

| Route | Does |
|---|---|
| `GET /session`, `POST /session`, `DELETE /session` | whether this browser is signed in, with its token; sign in; sign out |
| `GET /meta` | canopy's version, whether the data is mock, `tracker.ticket_url` (or none), and each repository's branch link template |
| `GET /attention` | the attention list, as `canopy status` shows it |
| `GET /runs` | running runs, then the 50 that ended last: ticket title, kind, status, PRs, summary, session, cost, worktrees |
| `GET /runs/{id}` | one run, as `GET /runs` shows it; 404 for no such run |
| `GET /runs/{id}/transcript` | its session's events, read back from its log (below); 404 for no such run |
| `GET /tick` | the latest tick, as `canopy status`'s first line shows it, or none; and the acknowledged message |
| `GET /ticks` | the latest 50 ticks, newest first: status, times, summary, overseer cost, how many decisions |
| `GET /ticks/{id}` | one tick: what `canopy decisions ID` prints; 404 for no such tick |
| `GET /ticks/{id}/transcript` | its overseer's session, read back from its output (below); 404 for no such tick |
| `GET /spend` | what the last 24 hours and the last 30 days each cost: worker, split, chore, and review runs and each tick's overseer, by start (§13) |
| `GET /tickets` | the journal's tickets, most recent activity first, at most 200: title, phase, private or public, waiting |
| `GET /tickets/{key}` | one ticket: what `canopy show` prints, its limits (each kind of each unit it has had runs in, then its units' PRs' review limits), its latest 100 messages, its latest 20 decisions, and its total cost |
| `POST /tickets/{key}/start` | `canopy start` |
| `POST /tickets/{key}/stop` | `canopy stop`, with `now` for `--now` |
| `POST /tickets/{key}/replies` | `canopy reply`, with the form's submission id |
| `POST /tickets/{key}/grants` | `canopy grant KEY KIND [--repo NAME]`, for one run: `implement`, `fix-ci`, or `resume` |
| `GET /chores` | each configured chore, as `canopy status` lists it: its runs, due time, window, and open findings |
| `GET /chores/{name}` | one chore defined for this workspace: what `canopy show chore:NAME` prints; 404 for any other |
| `POST /chores/{name}/replies` | `canopy reply chore:NAME`: a note its next runs read, with the form's submission id |
| `POST /chores/{name}/dismissals` | `canopy dismiss chore:NAME ID`, or with `undo` its `--undo`: the finding off the attention list until it clears (§19) |
| `GET /chores/{name}/runs/{id}` | one run of that chore: its row, its whole summary, the harness's note, and its findings; 404 for no such run of it |
| `GET /chores/{name}/runs/{id}/transcript` | its session's events, read back from its log (below); 404 for no such run of that chore |
| `GET /search?q=` | the journal's tickets, messages, chore runs, decisions, and ticks that hold every word of `q`, at most 20 a source (below) |
| `GET /reviews` | canopy's latest 100 review runs, newest first: PR, commit, ticket, status, verdict, impact, findings, cost (§21) |
| `GET /reviews/{id}` | one review run: its summary, findings anchored on its diff, each marked whether dismissed, the diff, and the PR's other runs; 404 for no such run |
| `POST /reviews/{id}/dismissals` | `canopy dismiss review:ID N`, or with `undo` its `--undo`: no worker or tick acts on finding `N` (§21) |
| `GET /pull-requests` | the PRs the journal knows, most recent activity first, at most 100: ticket, branch, phase, the run working it, its latest review |
| `GET /pull-request?url=` | one PR: the runs that pushed to it, its review runs and limit, the latest 20 decisions naming it, and its total cost; 404 for one nothing names |
| `POST /pull-request/grants?url=` | `canopy grant URL review`, for one review run |
| `GET /worktrees` | each pool's slots from `treehouse status --json`, with the running run or review holding each |
| `GET /loop` | whether the loop is paused: since when, and through which channel (§6), or not |
| `POST /loop/pause`, `POST /loop/resume` | `canopy pause`, `canopy resume`: whether it already was, and the state left |
| `GET /events` | the event stream, below |

A message is acknowledged once a tick that read it closes `ok`: `GET /tick` and `tick.updated` carry the newest message
the latest `ok` tick read (§6 step 3), or none before the first. The attention list is that tick's, so until then a
reply has not reached the loop's decisions or the list: the conversation marks each of the operator's messages after it
as waiting for the next tick, and an `awaiting_reply` item whose ticket waits on no question now as answered. A tick
that read a message but did not close `ok` acknowledges nothing, as it leaves the attention list standing.

A guard's refusal is a 409 whose `detail` names the guard and gives its reason, as the CLI prints them. A reply carries
a submission id the form drew when it was rendered, sent again unchanged when the operator retries, and stored as
`web:<id>`, so a retried submission records nothing new.

The OpenAPI schema (`python -m canopy.serve openapi`) says all of this as well, so the UI's generated types carry it
as JSDoc. Each route has its resource's tag, a summary, a description, and every error it answers with the model of
its body: a 403 on every route (the guard, or a write's token and `Origin` checks), a 401 on all but `/session`, a 404
for no such thing, a 409 for a guard's refusal, and FastAPI's validation error for every 422, a search of too many
words included. Every model, field, path parameter, and named type is described; `test_serve.py` checks each.

The event stream: each open stream holds its own journal connection and reads SQLite's `data_version` four times a second.
It reads on a thread of its own, never on the server's event loop: a tick commits each decision it records, every open
stream reads the lists again on each commit, and on a journal with months of history those reads, on the event loop,
held up every other request while the overseer worked. When another connection has committed since, or the loop has
read its config again (§6), it reads the attention list, the runs, the tickets, the chores, the spend, the latest tick,
and the pause again, and sends each that changed, whole: `attention.updated`, `runs.updated`,
`tickets.updated`, `chores.updated`, `spend.updated` (when a cost changed; the windows move with the clock),
`tick.updated`, `loop.updated`, and `ticket.changed` naming each ticket whose summary changed. It reads them all in one
read transaction, so they are one snapshot: a commit landing between two of its queries cannot send a ticket's new
summary in a list still in the order from before it. A reload commits nothing, yet the chores and the attention list
are read through the config, so the stream holds the loop's config as the server's requests do, taking the new one at
its next read: a chore added and reloaded shows on an open page without a refresh.
A new stream starts with every list, the spend, the latest
tick, and the pause, so a pause from the loop's terminal or the CLI shows as one from
the web does. The UI writes a list into its query with `setQueryData` and refetches a changed ticket
only if a page shows it; a chore's page is read again on every `chores.updated`, whose list carries each chore's
newest note, so a note changes it, and a chore run's page when that list moves the run's status. The latest tick
carries how many decisions it has recorded, so `tick.updated` is sent as a running tick records them, and on it the UI
reads again the ticks list, a tick's page, and a ticket's page, each only if a page shows it. The journal has no
notifications, so reading one pragma every quarter second is the cheapest way to learn of a change, and quick enough
that a change shows as it happens; nothing in the browser polls.
A browser reconnects a dropped stream itself, but not always: it gives up on a refusal, such as a proxy's 502 while the
loop restarts, and iOS Safari often stops retrying after the page was in the background. So the UI opens a new stream
when one has been down 5 seconds, waiting twice as long after each try up to a minute; at once when the device is back
online or the page is shown with its stream down; and when the page is shown after 30 seconds hidden, since the system
may have cut the stream without telling it. A new stream starts with every list, so nothing is lost but the ticket a
page shows, which it reads again. An age on a page (`5m ago`) counts on a clock that ticks every second.

The chores pages (M23): a chore's finding reaches the attention list, and the operator answers it in the browser as
`canopy reply chore:NAME` does in the terminal.

- `GET /chores` lists the chores `canopy status` lists: those configured for this workspace, none while
  `capacity.max_chores` is 0. Each has its `every_minutes`, `days`, `hours`, `timezone`, and `when`; its running run,
  or else its latest ended one; its `due_at` (§19, the `not_due` and `outside_hours` guards' earliest start, by the
  server's clock); its open findings, each with when its unbroken sequence of `ok` runs began and whether the
  operator dismissed it; its newest note's id; and its spend (asked for by the operator, 2026-10-13): for the last
  24 hours and the last 30 days, by start as `GET /spend` counts, how many of its runs started, how many of them
  reported a cost, what they cost (§13), and a run's average, 99th percentile, and most over those that reported one,
  the percentile by nearest rank, so under 100 runs it is the dearest. A window carries its length and not its
  start, which moves with the clock and would change the list the stream sends on every read.
- `GET /chores/{name}` is one chore defined for this workspace, configured or not, as `canopy reply chore:NAME` takes
  a note to one: that summary, its latest 10 runs with status, summary, number of findings, session, cost, and log
  path, and the latest 10 notes, oldest first, which are what its next run's `## Run` section carries. A name no chore
  could have is refused `bad_ref`; one not defined here is a 404.
- `POST /chores/{name}/replies` takes the reply form's body and submission id, as a ticket's does, behind the same
  session token and `Origin` check, and records a note with channel `web`. Nothing in the web UI runs a chore: the
  overseer decides when one runs (§19), and `canopy chore try` stays in the CLI.
- `POST /chores/{name}/dismissals` takes a finding's id and `undo`, behind the same checks, and dismisses the finding
  as `canopy dismiss` does, or takes the dismissal back, with channel `web` (§19). A finding selected on the attention
  list has a small `dismiss` beside its age; on the chore's page each open finding has one in its head line, or,
  dismissed, a mark and `list again`.
- A chore run's summary is the harness's note or the agent's summary, cut at 300 characters, and a finding's title and
  detail are the agent's: untrusted text, rendered as text with control characters dropped.
- A chore run's page (asked for by the operator, 2026-10-13: a list's summary hid the rest of what a run said) is its
  row, the whole of its summary (a result bounds it at 2000 characters) and the harness's note apart from it, the
  findings an `ok` run reported, and its session's transcript (below). `GET /chores/{name}/runs/{id}` finds a run only
  under its own chore, and keeps the runs of a chore since deleted from the config, as the journal does.
- The chores page is in the navigation, and each chore has a page; each run's id on it opens the run's page. On the
  attention list, a chore's item, a finding or `chore_failed`, opens the chore's notes and the note form beside the
  list, as a ticket's opens its conversation. A note no run of the chore has started since is marked as waiting for
  its next run: notes wake nothing and no tick reads them (§19), so a tick's acknowledgement says nothing about them.

The ticks pages (M24): the `decisions` table is the overseer's reasons for what the loop did and the evaluation corpus
for prompt changes (§6), and "why has the loop not picked this up" is answered where the ticket is.

- `GET /ticks` lists the latest 50 ticks, newest first, each as the header's tick is shown, with its overseer's
  session and cost and how many decisions it recorded. `GET /ticks/{id}` is one tick and its decisions in the order
  they were recorded; an id that is not a positive integer is refused (422), and no such tick is a 404.
- A decision names its subject as `canopy decisions` does: a ticket, a unit as its ticket and repository
  (`ABC-1 (web)`), a repository, `chore:NAME`, `pr:URL` for a PR no ticket owns, or `-` for the whole tick; with its
  ticket, repository, chore, and PR apart, and its action and rationale.
- A rationale is the overseer's text: untrusted, its control characters dropped and its line breaks kept, where
  `canopy decisions` prints it on one line. It was cut at 2000 characters when recorded (§6).
- A ticket's page lists the latest 20 decisions about it, its units' included, newest first, each with its tick.
- A ticket's page shows its total cost (asked for by the operator, 2026-10-14), as the runtime reported it (§13): every
  run of it, however long ago, and every review run that names it, with how many of each it counted and how many
  reported nothing. Not the overseer's: a tick decides for the whole workspace, so its cost is no ticket's.
- The tick's page names where the overseer's output is, `.canopy/ticks/<id>.log`, when the file exists, and shows its
  session's transcript under the decisions (below), and the file's end as written under that (The tick's output,
  below).
- The ticks page is in the navigation, and the header's latest tick links to its page. Reads only.

The pull requests pages (ROADMAP M32, asked for by the operator, 2026-10-13): a PR is a subject of its own, so what
the journal holds about one, spread over a ticket's units, its runs, the reviews (§21), and the decisions, is
gathered on its page.

- A PR is known by a ticket's unit (one of the loop's own, reviewed or not) or by a review run (either kind, §21).
  `GET /pull-requests` lists each once, most recent activity first: the newest of the unit's ticket's last sighting and
  the PR's review runs' starts and ends. Each has its URL, the ticket that owns it (a unit's, or else the one a review
  named, as a forgotten ticket's review still does) with its title, its repository, the unit's branch and phase, the
  run of its ticket working now, how many review runs it had, and its latest. Decisions are not a source for the
  list: they are many and not indexed by PR, and the list is read again on every tick and every ticket change.
- `GET /pull-request?url=` is one PR, named by its URL as a query parameter, since the URL is opaque (§21) and holds
  slashes; only a plain `https://` URL of at most 300 characters is looked up, anything else is a 422. A PR only
  decisions name (a `review.query` match no review has run on yet) has a page too, so it shows why (`wait`, a refusal).
- Its page: the PR's fields and a link out to it; the runs that pushed to it, its ticket's runs whose result names it,
  and any of its ticket's runs still working, which has no result yet; its review runs, each opening its review's page
  with its findings on its diff; and the latest 20 decisions naming it. A decision about a PR no ticket owns links to
  its page, and so does a review's page.
- A PR's page shows its total cost, as a ticket's does: every run it lists, past the 20 shown, and every review run of
  it. A run that pushed to two PRs, one per repository, counts on each one's page, and once on its ticket's.
- Reads only, and not on the event stream: the UI reads them again on `tick.updated` and `ticket.changed`. Nothing
  here writes to a PR. Everything shown is journal text the other pages already serve, so T8 is unchanged.

The transcripts (M27): what a session did, its tool calls above all, without leaving the browser for
`opencode export`.

- `GET /runs/{id}/transcript` reads the run's log, `GET /chores/{name}/runs/{id}/transcript` the chore run's, and
  `GET /ticks/{id}/transcript` the tick's output, on each request (`core/transcript.py`). Of the events in it (§13),
  only those of the session the journal recorded for the run or tick are read; any other line (stderr, a setup
  command's output, the harness's markers, another session's events) is left out. The file itself is served only as
  a tick's output (below), never a run's or a chore run's log.
- Each event is validated (D026). A `text` or `reasoning` event is the agent's text; a `tool_use` event is one tool
  call, printed once it completed or failed, with its name, title, input (as indented JSON), output or error, and how
  long it took; a `step_finish` is one model call's reason, cost, and tokens, together and by kind (input, cache read,
  cache write, output, reasoning); an `error` is the runtime's. A `step_start` starts a model call: it is not shown,
  but every entry after it carries that call's number, from 1. Any type canopy does not know is left out, and an
  event of a known type that does not validate is counted, not shown.
- A model call shows what the runtime prints of it. What it wrote and ran are the text and tool calls above it; its
  reasoning only with OpenCode's `--thinking`, which the default templates leave out. What it was sent is below.
- Bounded: at most 32 MiB of the file, to its last whole line; at most 2000 entries and 2 million characters in all;
  each text, output, and error cut at 20,000 characters, and an input at 5,000. A cut says so. Control characters are
  dropped, line breaks kept. A log that is a symlink, a FIFO, or anything but a regular file is not read: it is opened
  without following links and without blocking.
- A transcript says why it has nothing: no session (a template without `--format json`), no log, or none of its
  events yet. A run's events reach its log only when it ends, since its stdout is captured whole (§8), as a chore
  run's do (§19); a running run's page says so. A subagent's calls are its own session's (§13), so a `task` call
  shows as one tool call with its answer.
- A tool call's line says what it did and how it ended, so a tick reads without opening each call: a shell call's
  command, not the description the agent gave it, and the call's other short values when the runtime gave it no title
  (an MCP read's `owner=acme repo=web pullNumber=88`, where its first value alone was `get`); its error, or an output
  of one short line, under it. OpenCode reports a shell call completed whatever its exit, so a canopy command the
  harness refused, which prints `Error: <verb> refused (<guard>)` and exits 1, would show as done: the UI reads that
  line from a canopy command's output and marks the call refused, with its guard. Only canopy's own lines are read so;
  another command's output is what it printed.
- It is not on the event stream: a log can be large, and it changes only as its run or tick ends. The UI reads a run's
  again when `runs.updated` moves that run's status, a chore run's when `chores.updated` moves its, and a tick's when
  `tick.updated` moves that tick's.
- A run's page is its fields as the runs list has them, over its transcript; each run's id in a list of runs opens it.
- Everything in a transcript is agent output: untrusted, rendered as text; a tool call's input, and an output that is
  JSON, have their keys, strings, and values colored. It holds whatever a tool read or printed, a
  file's contents or a command's output, which is more than the journal does (TRUST_MODEL T8).
- Rejected: running `opencode export <id>` from the server (a second runtime process behind the listener, and
  OpenCode's storage format to follow); copying events into the journal (unbounded rows for a view); serving a run's
  log, or its tail. Revisit when a running run should show its events as they come, which needs its stdout streamed
  to its log, or when a second runtime prints another shape.

Model calls (taken on request, 2026-10-13): to explore what each model call was sent and what it did, not only what
it cost.

- A call is sent everything before it: the agent's definition and the runtime's own system prompt and tools, the
  prompt canopy gave the runtime, and every earlier call's output and what its tools returned. So what is new in a
  call's input is, for the first, the prompt, and for each later one, what the call before it asked its tools for.
  The log holds all of that but the prompt, which canopy keeps beside it, and the part ahead of the prompt.
- The prompt is the `{prompt}` the agent command was given: `<id>.prompt` beside the log, as a run's or a chore run's
  prompt already was, and a tick's state block, which the tick now writes to `ticks/<id>.prompt` before its
  overseer starts, mode 600. A transcript carries it whatever its status, read on each request as a log is (a regular
  file opened without following links), at most 1 MiB of it, control characters dropped, with `truncated` past that;
  no file, or one canopy refuses, is none.
- The UI's transcript groups its entries by call when the operator asks (By call, ui/DESIGN.md): each call a
  line, opening to its input (the prompt, or what the call before it got back from its tools, each tool's output in
  full) and its output (its text, reasoning, tool calls, and errors), each with its tokens. An entry before the first
  `step_start`, such as an error starting the session, stays a row of its own.
- What no file records is said, not guessed: the agent's definition, OpenCode's system prompt, and its tool
  definitions. With OpenCode 1.19.0 against a model server that recorded each request (2026-10-13), those were about
  95% of a short session's third request, by characters. `opencode export <id>` holds the session's messages, one
  assistant message per call with the same parts the log prints, and the prompt as its first user message, but none
  of that either; nor does OpenCode's DEBUG log. Recording it needs a proxy between the runtime and the provider,
  which no milestone lists.
- Rejected: `opencode export` on request, again. Beside what the log and the prompt hold, it would add only a running
  session's calls before its run ends, for a runtime process behind the listener.

The tick's output (taken on request, 2026-10-13): the transcript keeps only the overseer's session, so what the
runtime printed on stderr, and any line that is not one of its events, sent the operator back to the file, most of all
for a tick whose overseer failed.

- `GET /ticks/{id}/output` reads the end of the tick's output file as written on each request (`transcript.tail`): its
  stdout, the `--- stderr ---` line the tick writes, and its stderr (§6). The same checks as a transcript's: a
  regular file, opened without following links and without blocking. At most its last 1 MiB, from the first whole
  line in it, which is far more than an overseer prints on stderr; control characters dropped, line breaks kept. It
  says the file's size and whether it was cut, or `no_output` when there is no file (the tick kept none, or is still
  running). No such tick is a 404.
- Its end, not its start: stderr and the session's last events are where a failed tick says why, and the transcript
  has the session from its start.
- An Output panel under the transcript, hidden until the operator shows it, so a tick's page reads the file only when
  asked. It opens scrolled to its end. Everything in it is agent output, rendered as text; a line of JSON, which is
  most of it, has its keys, strings, and values colored, as written. A Pretty toggle lays each line of JSON out over
  several, indented, changing only the space between its tokens; each tick's panel remembers it, in the browser.
  Not on the event stream;
  it is marked stale with the tick's transcript, as the tick ends.
- A tick's output only. A run's log is the worker's and its setup commands' (§8), and stays its transcript (above)
  until the operator asks for the rest.

The worktrees page (taken on request, 2026-10-08): for each repository in the workspace, in map order, its pool's
slots as `treehouse status --json` reports them, read when the page asks. Each slot is one line: its state (below;
treehouse's own status on hover), its number (its path on hover), its lease holder, the branch it has checked out (or
detached; a run's slot is detached, D109, and shows the run's branch), linking to its page on the host when the
repository has a branch link (§18), the processes treehouse found running in it,
and since when; an idle slot is its state and number alone, and a note gets a second line. A lease is matched to a
running run or review by its lease id, as reconcile matches them, so a slot names the ticket, run kind, and run that
hold it. The page groups slots in five states it colors: `working` (held by a run or review the journal shows
running), `held` (leased or in use by anything else: the operator's own shell,
`canopy-sync`, or a `canopy:` lease no running run holds, which it notes the next reconcile returns), `dirty` (unleased
with uncommitted changes), `idle` (available), and `broken` (damaged, unverified, or a status canopy does not know). A
pool with no clone, or whose treehouse fails, shows why in its place; the other pools still show. Branch and process
names are shown as text with control characters dropped, and at most 20 processes per slot. A path inside the workspace
is shown from its root (`.treehouse/web-3f9c2a1b/1/web`), here, in the runs page's worktrees, and for a run's log and
a tick's output. When a pool's slots
share a directory, the pool's header names it once. The pool's declared size (`capacity`, §18) is shown with its slot
count, and a pool holding more slots than that says how many, and that `canopy workspace sync` removes idle ones. Above
the pools, counters of every pool's slots working, held, needing a look (dirty or broken, and any pool it could not
read), and free; each pool's header has a square per slot in its state's color.

The pools are read at once, a thread each and at most 8, so a workspace of many repositories waits on its slowest pool
rather than on all of them in turn. `treehouse status` changes no lease, but it takes the pool's state lock and may
rewrite the pool's state file as it heals it, as reconcile's reads do every tick, so a slow read holds up a lease in
that pool for as long as it takes.

It is not on the event stream: the journal does not hold a slot's branch or processes, and a `treehouse status` per
pool once a second per open page would cost more than the page is worth. The UI reads it again when a `runs.updated`
event changes which running runs hold which worktrees (a run's cost moving does not), when the operator asks, and
every 10 seconds while a page shows it in a visible tab: what runs in a slot, whether it is dirty, and the slots
a sync adds or removes never reach the journal, and a run's own refresh comes as it is recorded, before its worker has
checked out its branch. Only an operator's read shows on the Read again button.

Search (M31, asked for by the operator, 2026-10-13): one box that finds a ticket, or the run or tick that said
something, without knowing which page holds it.

- `GET /search?q=` reads the journal on each request (`core/search.py`). The query is 2 to 200 characters of at most
  8 words, or a 422. A hit holds every word as a substring of one field, ASCII letters in either case (SQLite's
  `LIKE`, with `%`, `_`, and `\` taken literally).
- It searches, in this order: tickets, by key, branch, and their units' branches and PR URLs; messages, every
  ticket's conversation and every chore's notes, so a run's report (its summary, or the harness's note, and its PRs)
  and its question; chore runs, by summary, the harness's note, and their findings' titles and details; decisions, by
  rationale; and ticks, by summary. A ticket's branch is `<prefix><KEY>-<slug>`, its slug from the ticket's title
  (§8), so the slug is how a title's words are found.
- Each source gives its 20 newest hits and says when it has more. A hit names where it is: the ticket, the chore, the
  run that reported a message, the tick of a decision. Its snippet is one line of at most 160 characters around the
  first match of any word, control characters dropped and whitespace collapsed, cut with `…`; the UI marks the words
  in it, as text.
- Not searched, since none can be done well yet:
  - Ticket titles. The journal holds none: the tracker does, and world facts are re-read from their source (§11).
    Recording one needs the overseer to report it, a prompt change; the branch's slug stands in.
  - Transcripts. A run's log holds up to 32 MiB and is read whole on each request (above); reading every log for
    every query is not reasonably efficient, and indexing them copies agent output into the journal, rejected above.
  - Review runs. No page shows one yet, so a hit would have nowhere to open.
- Without an index, a scan reads newest first and stops at a source's 21st hit, so a common word answers at once. A
  query nothing matches reads each searched column whole: about 1.6 ms per MB of text (56 MB of messages in 90 ms,
  on SQLite 3.45). Rejected for now: SQLite's FTS5.
  Substring matching needs its trigram tokenizer, whose index is about three times the text, kept by triggers on five
  tables in a migration, on a SQLite built with it. Revisit when a real journal's empty search takes more than a
  quarter of a second.
- Reads only, and not on the event stream: hits are read again when the query changes, not when the journal does.
  It serves only journal text the other pages serve, behind the same session, so T8 is unchanged.
- The search box sits atop the nav on every page; `/` focuses it from anywhere but a text field, and Escape leaves it.
  Typing opens `/search?q=` once the operator pauses for 250 ms, replacing the history entry as the query grows, and
  Enter opens it at once. A clear button empties the box without leaving the page. The page groups hits by source,
  each a row that links to the page holding it.

How it serves, built in M20's foundation and true of every page:

- Under one path prefix (`serve.base_path`; `--base-path` for `python -m canopy.serve`; empty by default), so a proxy
  can mount it anywhere: the API at `{base}/api`, the app's hashed files at `{base}/assets/`, and `index.html` for
  every other GET or HEAD. The prefix is written into `index.html` as `<base href>`; the build uses relative URLs and
  the router reads its basepath from it, so one build serves under any prefix. The prefix comes from config, never
  from a request header.
- The fallback to `index.html` never answers under `{base}/api` (an unknown API path is a JSON 404) or for a path
  with a file extension (a missing asset is a 404, not a page). `index.html` is sent `no-cache`, so an upgrade never
  shows a stale UI; hashed assets are cached as immutable.
- Every response refuses framing and MIME sniffing and sends no Referer. `index.html` carries a CSP that allows only
  this origin, plus the inline theme script by its hash, computed from the file served.
- The Host header must name a loopback host or the bind address, on any route: that stops DNS rebinding. An `Origin`
  header on an API route must name one of those too: that stops another site's page from calling the API or opening
  the stream. Ports are not compared, so an SSH forward to another local port works.
- The event stream is FastAPI's SSE: `Cache-Control: no-cache`, `X-Accel-Buffering: no` so a proxy or forward does not
  buffer it, and a keepalive comment after 15 idle seconds. Nothing compresses it.
- The page makes no request to another origin: fonts and icons are bundled.
- `python -m canopy.serve --mock` serves the same API over a journal it seeds from fixtures in a temporary directory,
  for the UI's development server and its end-to-end tests. The fixtures are a workspace of three repositories, one
  not cloned, with a run holding slots in two pools and a pool past its declared size. Writes go to that journal.
  Without `--secret-file` it signs nobody in and asks for no session; only mock mode allows that, and it binds loopback
  only.

### Trust model changes

M18's and M19's are in TRUST_MODEL T1 and T6, with the operator's approval note in each milestone's PR. M20's are in
T8: the listener secret's file and sign-in, the session cookie and its token on writes, the allowed hosts, escaping,
and the residuals they leave, needing the operator's approval note in M20's PR.

The overseer prompt's changes, private tickets' phases from the state block and no `--label` for them (M18), and
mirroring each new comment (M19), are in the prompt.

Model calls (2026-10-13) changed T8: the listener reads a session's prompt beside its log too. Their PR carries the
operator's approval note.

Replies on public tickets and trusted reviewers (D089) changed T1: an operator message authorizes a public ticket's
`resume`, as an authorized reply does, and an untrusted reviewer's feedback starts no run without one. Their PR carries
the operator's approval note.

### Open

- Whether a private worker should have no tracker MCP server at all. It would then need the ticket's text from
  elsewhere; the overseer's `--context` holds 2000 characters.
- Whether a private ticket's PR body and branch should name the ticket key.
- Deleting a ticket's conversation, for client data the operator must not keep. `forget` keeps it.
- A forgotten ticket's attempt counts are not in the state block, which shows them per unit, so the overseer learns a
  limit from the `attempt_limit` refusal rather than before dispatching.
- Mirrored comments edited or deleted after the mirror.
- PR review comments in the journal, alongside ticket comments, once PRs are subjects (M14).
- Slack replies: a bridge holding a Socket Mode connection that runs `canopy reply` (a uv workspace member, like
  the Slack sink, so the harness stays free of network code), or the overseer reading Slack through MCP (§20). Either
  needs a T1 change naming Slack user ids.
