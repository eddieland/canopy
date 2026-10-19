# Conversations

Part of the canopy design, normative like all of it: the journal's conversation, private tickets, its channels, and the
web UI. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Chores,
notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md). Next: [Flaky CI](FLAKY_CI.md).

## 22. Conversations

The journal is the one record of every ticket's conversation: what workers reported and asked, what people replied,
and where each came from. A **channel** is a way into or out of that record: the tracker, the CLI, the web UI, and
Slack later. Channels differ in how they reach the operator and how they prove who wrote a reply. The overseer and
workers never see which channel a message came from, so adding a channel changes no prompt.

A ticket is **public** when one of `tracker.labels` authorizes it, as today, and **private** when the operator starts
it in canopy, or, with `tracker.private` set, when its label brings it in (below). A started ticket is private whatever
labels it carries: the start record wins. A private ticket's conversation never touches the tracker: the operator can
deliver a ticket a client filed without the agent's reports, its questions, or the operator's answers appearing on it.

### Messages

The journal records each message against its subject (a ticket now, a PR with M14), with ids that never repeat: where
it came from (a worker's run, the operator through a channel that authenticated them, or a tracker comment the
overseer mirrored, M19), its kind (a worker's `report` or `question`, the operator's `reply`, a mirrored `comment`), its
channel (`run`, `cli`, `web`, `slack`, or `tracker`), and, for a reply, the message it answers when the channel knows
it. A mirrored comment keeps its tracker id, author, and time, and is recorded once per subject.

Bodies are bounded: a worker's by its result contract (§8), the operator's at 4000 characters, a mirrored comment's at
2000, marked truncated when cut. An operator message carries a submission id, unique per subject, so a retried
submission records nothing new: the web form draws one when it is rendered, and the CLI derives one from the subject,
the message answered, and the body, so rerunning the same `canopy reply` after an uncertain result is the same
submission.

Who writes:

- The harness records a run's `report` (its summary and PRs) and, for a `blocked` run, its `question`, in the
  transaction that closes the run, for every ticket. It already has both from the result line (§8), so no agent gains
  a write.
- Operator input goes through one function every channel calls, with the guards in one place: the key is valid
  (§17), the ticket was started, the body is within its bound.
- The overseer records mirrored comments (M19, below), a worker's marked comments among them.

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
| `canopy grant KEY plan [--runs N]` | allow the ticket N more plan runs, default 1 (§25); no `--repo` |
| `canopy plan KEY [--skip \| --approve]` | ask for a plan, waive it, or approve the newest as its file stands (§25) |
| `canopy start KEY --plan` | start it privately and planned: its implement waits on a plan the operator approves (§25) |
| `canopy start URL --review` | have canopy review a PR the loop does not own, once, at its head (§21, M42) |
| `canopy stop URL` | end that PR's review request; a review of it already running finishes (§21) |
| `canopy show REF` | its phase, PRs, recent runs, and conversation, oldest message first; a PR's review request and reviews |

`canopy status` lists what was started, with each subject's phase, and the open review requests, beside the attention
list and runs; there is no separate `list`.

- `start` is private by construction: canopy cannot label a ticket (D003), so a ticket started in canopy keeps its
  conversation in the journal. The command says so, and when the next tick will pick the ticket up. A `--public` start,
  whose conversation stays on the tracker, is not planned.
- `tracker.private` (private, off by default) starts labeled tickets privately (D119). The first dispatch of a ticket
  canopy never ran, authorized by its `--label` as any public ticket's, writes the start record in the transaction that
  inserts the run, with channel `label`, and the run is private. From then on it is an ordinary private ticket: no
  `--label`, no label check in its worker's prompt, and removing the label does not stop it; `canopy stop` does. The
  dispatch's decision says it started the ticket, and `canopy show` says how. A ticket already worked in public keeps
  its conversation on the tracker, and a split leaves its ticket public, since it creates tickets there; its children
  are started by their own first dispatch. With no read tools for the provider the dispatch is refused
  `no_read_tools`. The label stays visible on the ticket (REQUIREMENTS R11): the switch hides the conversation, not
  that canopy works the ticket.
- `stop` without `--now` is graceful: it says which run is still going and that it will finish. With `--now` it also
  ends that run: its process group is killed and its slots returned and desk removed as reconcile does for a crashed
  run (§6), and the run is marked `stopped`, a status that raises no attention item and counts toward attempt limits
  like any ended run. `stop` refuses a ticket that was not started: a public ticket stops when its queue label is
  removed.
- `stop` marks the start record stopped rather than deleting it. A stopped ticket stays private and is dispatched by
  nothing, whatever labels it carries, until `canopy start` again: a queue label left on it never turns it public.
  A question its last run asked then waits on nothing: the attention list and the web UI's runs working now leave it
  out, though a run still working the ticket stays listed until it finishes.
- The start record is the authorization. Only the operator's commands write it, and, under `tracker.private`, a
  labeled ticket's first dispatch, short of T1's residual (below).
- A started ticket is private even when it also carries a queue label, or gains one later. The harness chooses the
  worker in code: `canopy dispatch` for a started ticket always renders the private prompt and runs the private
  definition, whatever the overseer passed.
- `stop` and `dispatch` cannot interleave. `dispatch` checks the start record and inserts the run in one write
  transaction, and `stop` marks the record stopped in one: whichever commits first wins, and `stop` reports any run the
  other committed. The run reads the record again before it starts the worker, and ends `stopped` if it is stopped.
- The state block marks each started ticket and carries its operator messages newer than its message cursor. A
  stopped ticket is not among its tickets: the block names it under `stopped`, by key, so the overseer records no
  decision for it and a queue label left on it does not make the overseer take it for a public one.
- `canopy dispatch` needs no `--label` for a started ticket. It checks the start record in code, a guard where a public
  ticket's `--label` is a claim (D051). `--kind split` on a private ticket is refused `private`: a split creates tickets
  in the tracker.
- The worker prompt has a private variant: no label check, since the harness checked the start record; never comment
  on, label, or edit the ticket; the result line's `summary` and `question` are the report. The agent definition is
  `canopy-worker-private`: `canopy-worker`, its MCP tools denied by name included (D084), with every tool of the
  tracker's MCP server denied by wildcard and only its read tools allowed by name, and the tracker CLIs canopy knows
  (`gh`, `acli`, `jira`) denied in its bash rules, but for `gh pr view`, `gh pr checks`, `gh pr diff`, and
  `gh run view`, which read a PR and its CI and never the ticket, so a resumed worker can read the review comments it
  was pointed at and the failing checks.
  - The server is `tracker.mcp_server` and its tools `tracker.read_tools`, both private, each with a default for the
    shipped provider's usual MCP server: `atlassian` with Jira's read tools for `jira`, and `github` for `github`,
    whose server is also the one PRs go through, so its list adds the PR tools a worker needs and leaves out every
    tool that writes to an issue. Denying the server by wildcard and then allowing each read tool by name makes a write
    tool no list names fail closed, where denying write tools by a name pattern would leave an unexpected one open.
    It relies on OpenCode naming an MCP tool `<server>_<tool>`, matching permission keys as wildcards, letting the
    last matching rule win, and hiding a tool whose last rule denies it (OpenCode 1.18.35).
  - Atlassian's Rovo MCP server lists only its primary tools unless its URL asks for `?tools=all`, and runs the rest
    through `execute*` tools that read or write by argument. OpenCode cannot see the argument, so those are denied:
    with the default URL a private worker reads the ticket with `getJiraIssue` and `searchJiraIssuesUsingJql` only.
  - With no read tools for the provider, `canopy start` refuses (`no_read_tools`) rather than run a worker that
    cannot read the ticket. A wrong list fails closed: the worker cannot read, ends `failed`, and posts nothing.
  - D044's guard grows for private runs: the harness refuses one when the worktree's OpenCode config has any
    `permission` or `tools` entry naming the tracker server's tools, since a repository rule merged after canopy's
    could reopen a write tool. The operator's own global config is the operator's to keep consistent (§13).
- Phases (§7) of a private ticket come from the journal: `needs_human` when its latest run ended `blocked` and no
  operator message came after it; `human_replied` when an operator message is newer than the ticket's message cursor, a
  cursor of its own over journal ids, never the comment cursor, which stays the tracker's. The action is `resume` with
  `--cursor message=<message id>`, its context pointing at the message. The PR phases are unchanged.
- The harness raises `awaiting_reply` every tick for a private ticket whose latest question has no operator message
  after it, with the question as its detail, as for the run reasons (§14). A public ticket's question still reaches the
  operator as `run.ended` (§20), whose `message` field is the id of the message the run recorded, its `question` for a
  `blocked` run and its `report` otherwise, so a channel can say what a reply answers.
- After `crashed`, `worker_failed`, and the other run reasons (§14), "try again" on a private ticket is an operator
  message after the run ended.
- `canopy reply` takes a started ticket, or a public one a tick has seen (it has a journal row); any other is refused
  `unknown`. On a public ticket the state block carries its operator messages newer than its message cursor under
  `operator`, and every public `implement` and `resume` prompt carries the latest 20
  (`{{OPERATOR_MESSAGES}}`, at most 30,000 characters), each labeled the operator's: an instruction. The workers'
  questions come with them, labeled data, so a reply to message N names something the worker can read; the rest of the
  conversation is on the tracker (D093). The same prompts carry the latest three runs' reports (`{{PREVIOUS_RUNS}}`,
  §8), labeled data. A reply on a ticket with no branch yet rides its `implement`, and one after a failed run is "try
  again". Its authorized repliers' comments on the ticket still work as before (§7). `show` drops control characters
  from every message.
- A public worker can write to the ticket and its PRs, so keeping the operator's messages off them is its prompt's
  rule, not a guard (TRUST_MODEL T6). Text the ticket's readers must never see belongs on a private ticket.
- `start`, `stop`, `reply`, `forget`, and `grant` refuse when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set. The harness
  sets `CANOPY_RUN_ID` for every worker, chore, and review agent.
- The private worker runs with `runtime.private_worker_cmd`, a template of its own as `split_cmd` is. Its prompt
  carries `{{CONVERSATION}}`: the ticket's latest 20 messages, oldest first, at most 30,000 characters, each labeled
  the operator's (an instruction) or an earlier worker's (data). That is how a resumed worker reads the operator's
  reply. On either kind of ticket the overseer's `--context` points at a message by id and never quotes it.
- A `canopy reply` answers the ticket's latest question, if any, and is idempotent on its submission id. Its body is
  stripped, and refused empty or over 4000 characters (`bad_body`) rather than cut.
- `canopy start` on a ticket the overseer marked done clears the done flag: the operator asked for it again. On a
  ticket with a public run still going, it says so: that run may still write to the ticket, and a public run that had
  not started its worker yet ends `stopped`.

### Forgetting a ticket's work

`canopy forget REF` has canopy drop a ticket's work so the loop starts it over (D086). It takes a ticket, public or
private, from the operator's shell or the web UI's Forget (below), and:

- refuses `unknown` for a ticket the journal has no row for, `running` while a run works it (wait for it, or end a
  started ticket's with `canopy stop --now`), `split` for a ticket a split made children of: they are tickets of
  their own, and forgetting the parent would not undo them, and `already_forgotten` for a ticket with no run,
  message, branch, unit, or done mark since its last forget, which would have nothing to drop.
- clears the ticket's branch, phase, when it began needing a human, and done flag, and deletes its units, with their
  branches, PRs, phases, and review and ci cursors. The next `implement` names a new branch with its `--slug`; from
  then on `bad_slug` (§8) binds to that one.
- records the forget as an event, kept for good: when, from which channel, the ticket's newest run and message then,
  and the branch and PRs it dropped. A ticket forgotten again has a forget for each attempt, and the ticket's row
  holds the latest, the boundary every read of the loop's view uses. The loop's reads skip what came before it:
  `last_run` in the state block, the run reasons on the attention list (§14), a private ticket's waiting question
  (`awaiting_reply`) and new operator messages, and a private worker's `{{CONVERSATION}}`. A reply after it answers
  nothing. A forgotten ticket reads to the overseer as one never dispatched, so its prompt is unchanged.
- keeps the rest. Its runs stay, so the attempt limits and the CI cooldown count every run, before and after
  (D030); a ticket at its implement limit needs `canopy grant` (below) or the limit raised in config, and `forget` says
  so. The comment and mirror cursors stay, so tracker comments already handled stay handled. The message cursor stays,
  and the boundary overrules it. The start record stays: a started ticket stays started, a stopped one stopped. `show`
  prints the whole history and each forget, with what it dropped. The web UI shows the conversation as the loop reads
  it: each forget heads the messages of the attempt it ended, folded away until asked for.
- holds the dispatch lock, which a dispatch holds from its plan through its run's insert, so a dispatch that read the
  old branch cannot record it again after `forget` commits.
- touches nothing outside the journal. The old PR and the branch on origin are the operator's to close and delete, and
  the command names them: until they are gone the overseer still finds the `agent/<KEY>-*` branch (§7's `ready` needs
  none on origin) and dispatches to continue it, refused `no_branch`. A ticket stacked on the old branch (§10) loses
  its base when that branch is deleted, so forget a blocker only once nothing is stacked on it.

### Granting attempts

`canopy grant REF KIND` lets the loop keep working a ticket one of whose units is at its attempt limit (§8),
without raising the limit for every ticket. It takes a ticket, public or private, from the operator's shell or the web
UI (below), and:

- takes `implement` or `resume`, and refuses `fix-ci` (`bad_kind`), whose old runs count as resumes (§8). A split's
  limit is the ticket's, and only config raises it. A plan's is the ticket's too: `canopy grant KEY plan` takes no
  `--repo` (§25).
- names the unit with `--repo`, which may be left out when the ticket has had runs in one repository only. A repository
  it has had no runs in is refused `unknown_repo`, as is a ticket with no runs, and a ticket with no journal row
  `unknown`. A forgotten ticket's runs still name their repositories, so it can be granted though it has no units.
- records the grant: the unit, the kind, `--runs` (default 1), and when. Grants are only ever added, never changed or
  deleted. The unit's limit for the kind is `policy.max_<kind>_attempts` plus the sum of its grants of that kind, so
  lowering the policy lowers it too.
- resets no count: every run, before and after, still counts (D030). The command prints the unit's runs and its new
  limit, read in the grant's own transaction, so two grants at once each report their own. The state block shows the
  unit's `granted` counts beside its `attempts`, and the overseer compares against their sum (§6 step 4); a dispatch's
  attempt limit and the worker's `{{MAX_ATTEMPTS}}` include them.
- dispatches nothing. The next tick decides from the ticket's phase as usual, so the trigger a refused dispatch left
  (§8: cursors advance only once a worker starts) is still new, and a ticket whose last run failed still waits for a
  reply (§14).

`canopy grant URL review` does the same for a PR at `policy.max_reviews_per_pr` (§21), whose head the loop may not
review again. A PR's review limit is the PR's own, not a unit's, so it:

- takes the PR's URL, as `canopy review show` and the `review_limit` item name it, and no `--repo`. Review runs are
  keyed by that URL, so `REPO#N` is refused `bad_ref`, as is a URL canopy has never reviewed `unknown`. A ticket key
  with `review`, or a PR with any other kind, is refused `bad_kind`.
- records the grant: the URL, `--runs` (default 1), and when, only ever added. The PR's limit is
  `policy.max_reviews_per_pr` plus the sum of its grants; no other PR's changes.
- resets no count (D030). The state block shows the PR's `granted` beside its `review_runs`, and `canopy review run`'s
  `review_limit` guard and the reviewer's `{{MAX_ATTEMPTS}}` include it. It reviews nothing: the next tick decides.

The web UI grants through the same code, so with the same guards, one run a click, where the stuck thing is shown: a
ticket's page and its attention item, for each of its units' kinds at their limit and each of its units' PRs' review
limits; a PR's page, and an item about a PR no ticket owns, for its review limit. A limit with room left shows
nothing, so the control appears only once the loop is held by it. It needs no confirmation: one more run of a kind the
loop already ran is the least a grant can do, the overseer still decides whether to use it, and every guard on the run
still holds. `--runs N` stays the CLI's.

### References

A reference names a subject by its shape, so no kind needs a flag and no form can be read as another's: a ticket key
(§17) has no `:`, `#`, or `/`.

| Reference | Subject | Verbs |
|---|---|---|
| `PROJ-123` | a ticket | all (M18), and the overseer's `mirror` (M19) |
| `api#42`, or the PR's URL | a PR | `grant` (its reviews), `start --review` and `stop` (a review request), and `show`, each by URL; the rest once PR-scoped work exists (M14) |
| `chore:NAME` | a chore (§19) | `reply` (its notes), `dismiss` (one of its findings), `show` |
| `run:ID` | a run | `show` |
| `review:ID` | a review run (§21) | `dismiss` (one of its findings), `send` (some to a worker); `canopy review show ID` shows one |

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
  state block's `mirror.body_delimiter`, drawn fresh and random each tick, so no comment can be written to end the
  heredoc early and run what follows. OpenCode checks a heredoc command's permission against its whole text, so the
  overseer's `canopy *` rule admits it (OpenCode 1.18.35); a body the shell parser reads as a command substitution is
  refused by the rule, failing closed, and the overseer then mirrors the comment as `(text not mirrored)`.
- Bounds, checked in code: a comment id as plain as a cursor id (`bad_comment`); the author an account id of at most
  200 printable characters without whitespace (`bad_author`); the time ISO 8601, read as UTC without an offset
  (`bad_time`); the text stripped and not empty (`bad_body`; the prompt mirrors a comment without text as
  `(no text)`), cut at 2000 characters and marked truncated. At most 100 `mirror` calls a tick (`mirror_limit`), so a
  long history spreads over several ticks. Every refusal is recorded as a `refused:<guard>` decision.
- Idempotent on the subject and comment id: a comment recorded again records nothing new, whatever text is passed the
  second time. Each call records a `mirror` decision in the same transaction, naming the message, or the message it
  already was, so the decisions show each comment mirrored once. The loop's tick block leaves `mirror` decisions out,
  as it does `wait`, and the tick's summary counts them.
- The harness reads the workers' marks (D069) itself: a comment that starts with `trust.comment_prefix` and ends with
  `trust.comment_suffix`, whichever are set, and whose last line is not a quote, is recorded with source `worker`;
  any other with source `tracker`. A worker's comment is recorded because its text can differ from the result line
  or come from a run whose result line never parsed. Either way it authorizes nothing: phases, `awaiting_reply`, and
  the loop's wake read operator messages only, and a private worker's prompt labels a mirrored comment as data, with
  its author's account id.
- The mirror cursor is its own, apart from the comment cursor the phases use, and only `canopy mirror` moves it, to
  the comment it records; `--cursor` cannot name it. It starts empty, so the first mirror of a ticket covers its whole
  comment history once, worker comments the comment cursor had passed included. The state block carries it in each
  ticket's `cursors`.
- A dry run records the mirror too, as a record of what the overseer saw, but moves no cursor and changes no phase.
- `canopy show` lists a mirrored comment with its source, comment id, author, and time, and whether it was cut.
- The mirror lags the tracker by up to one tick. A comment edited or deleted after it was mirrored is not updated.
  PR review comments are not mirrored; they join the journal with PR subjects (M14).

### Waking the loop

During the wait (§6, the loop), each step checks the journal for the operator's acts: a message to a ticket recorded
since the last tick began; a ticket started or stopped, attempts or a PR's reviews granted (`canopy grant`), or a
notice to workers set or cleared (`canopy notice`, §8), since the last tick read the journal (or began, when it read
nothing). A note to a chore (§19) does not wake it: the chore's next run reads it. Nor does a config reload (§6). Any
of those acts ends the wait and runs the next tick, no sooner than `loop.min_gap_minutes` after the last one began,
whether idle pacing is on or not; the tick records what woke it (`message`, `starts`, `grant`, `notice`) and is not
idle. Every channel wakes it the same way, whether the act came from another process (`canopy start`) or the loop's
own server thread (D073). Capacity, attempt limits, and cooldowns hold as for any tick.

### Channels

| Channel | In | Out | Proves the operator by |
|---|---|---|---|
| tracker | comments, mirrored (M19) | worker comments on public tickets | `trust.authorized_repliers`, read by agents |
| cli | `canopy start`, `stop`, `reply` (public tickets too), `forget`, `grant`, `dismiss`, `send`, `notice` | `canopy show`, `canopy status` | the operator's shell (T1 below) |
| web (M20) | reply, start, stop, forget, grant; notes to chores (M23), dismissing chores' and reviews' findings, sending reviews' findings to a worker (M32); pause, resume, tick now; setting and clearing a notice to workers (M35); promoting, rejecting, renewing, editing, and forgetting memory (M52, M59) | pages | the listener secret (TRUST_MODEL T8) |
| slack (later) | thread replies | §20's sink | Slack user ids the operator lists |

Outbound, every channel uses §20's events: a sink posts them, and the web UI reads the same journal.

### The web UI (M20)

The web UI is the operator's view of the journal in a browser, and the CLI's verbs beside it: it shows what the loop
is doing, what it costs, and every conversation, and takes the operator's acts through the same code as the CLI.
Page-by-page and widget detail is in `ui/DESIGN.md`; what follows is what the server does and guarantees.

Served by `canopy loop` from a thread (D073):

- On unless `--no-serve` or `serve.enabled = false`. `serve.bind` (loopback by default, or a private address) and
  `serve.port`. Every `serve.*` key is private (T7).
- It requires the operator's listener secret (T8, below). Without one the loop says why and how to make one, logs it,
  and serves nothing; the loop goes on. It serves plain HTTP, also on a private address: T8's "relies on the network"
  residual stands (D076).
- Each request opens its own journal connection, never takes the tick lock, and writes only through the functions the
  CLI's verbs use, with channel `web`: `start`, `stop` (with `now`, the same end of the run as `canopy stop --now`),
  `reply` (a note to a chore is a reply on its subject, as `canopy reply chore:NAME` is, and sending a review's
  findings a reply on its ticket, §21), `forget`, `grant` (one run each), `dismiss`, `send`, `pause` and `resume`
  (§6), `notice` and its clear (§8), `plan` (§25), and `memory promote`, `reject`, `renew`, `edit`, and `forget` (§28).
  Beyond the CLI's verbs it writes only the operator's own words on a plan: the plan editor's save and comments on its
  passages (§25). Reload asks the loop to read its config
  again, as SIGHUP does (§6); it writes nothing, and the files stay the operator's to edit. Tick now asks the loop for
  a tick at once, as `t` at its terminal does (§6), and writes nothing either.
- A forget cannot be undone from the UI, so its request carries the ticket's key as the operator typed it, and the
  server refuses `not_confirmed` before reading anything when it does not match, so no client skips the challenge; one
  more click, as Stop now asks, is too easy to give by mistake. Its outcome names the branch and PRs canopy no longer
  tracks, as the CLI's does. Forgetting a memory carries its ref typed out (`memory:42`) the same way.
- The one process it runs is `treehouse status --json`, for the worktrees page (below): it changes no lease, but it
  takes the pool's lock.
- A server failure is logged and the server restarted with a growing delay; it never ends the loop. Stopping the loop
  stops it, waiting briefly for open streams.
- Pages: the attention list (the home page, beside the selected item's conversation and reply form), runs (each with a
  page and its session's transcript), worktrees, tickets (each with its conversation and the decisions about it), pull
  requests, reviews (§21), chores, ticks, search, spend, settings, and the guide (below). Every page shows the runs
  working now and the recent spend, and the loop's pause and any notice to workers. Actions: the CLI's verbs above,
  where their subject is shown. OpenCode's session attach (M15) is not in the UI: a run's page shows its session id
  and its transcript as it goes, and attach joins once M15 runs workers against OpenCode's server.
- The guide: the operator's documentation, a page each, laid out as a documentation site at `/guide` and opened from the
  rail's foot, or from a book atop each page at the part about that page. Its pages are Markdown in `ui/src/guide/`,
  bundled with the build, so the guide describes the canopy that serves it, and needs no route of the server's. Its
  config page shows `examples/`'s config files whole, bundled the same way, so the keys it lists are that canopy's. It
  is canopy's own text, not the journal's, so the parser below reads its labelled links too, to another page, a section
  of the app, or the web, still into React elements. Not at `/docs`, which the server sends to the API's documentation.
- FastAPI on uvicorn (D074), serving a single-page app built from `ui/` (D079) and the JSON and SSE API it reads. The
  server installs no signal handlers (the loop's own handle Ctrl-C, §6) and logs nothing to the terminal. Request
  bodies and path parameters are validated with pydantic models and the reference parser, as everything else parsed
  from outside is (D026).
- Every value from the journal is escaped: tracker comments and agent output are untrusted text in a page that holds
  the operator's session. Nothing renders journal text as HTML, and no inline script is built from data. Message
  bodies are sent with control characters dropped, as `canopy show` prints them; summaries and rationales the same,
  their line breaks kept. A page lays those out (line breaks, lists, headings, `code`, and **strong**) with a small
  parser of canopy's own into React elements, not a Markdown library, which would render HTML and labelled links that
  need switching off. Any other markup, a labelled link's included, stays characters.
- An http or https URL in journal text (a message body, a run's or tick's summary, a rationale, an attention item's or
  finding's detail) is shown as a link whose text is the URL as written, opening in a new tab with no referrer (D113).
  No other scheme is linked, and nothing else in the text becomes markup but the layout above; a URL inside `code`
  stays text. A row that is itself a link (an attention item in the list) links nothing inside it.
- It lives in `src/canopy/serve/`, the only package that imports `fastapi`, `starlette`, `uvicorn`, or `anyio`, as
  only `cli/` imports click. The ban on `socket`, `http.client`, and `urllib.request` (§20) stays absolute: canopy's
  code opens no socket itself. It listens and calls out to nothing, so T2's "no outbound call" stands.

Signing in:

- The listener secret is `listener-secret` in the user config directory (`~/.config/canopy/`): one line of at least 32
  characters, in a regular file, not a symlink, owned by the operator, with no group or other permission bits.
  `canopy secret` writes one, 32 random bytes in URL-safe base64, and prints it; it never replaces one without
  `--rotate`. The loop reads it once, when it starts serving.
- The browser gets it from the operator: the sign-in page asks for it once, in a password field a password manager
  can keep. Sign-in compares it in constant time; a wrong one is answered after a second and logged. The delay slows
  one client guessing in turn, not many at once, so what stops guessing is a secret no one can predict: the one
  `canopy secret` writes, or one as random if the operator writes their own.
- A right one sets a session cookie, `canopy_session_<port>`: `HttpOnly`, `SameSite=Strict`, path `{base}/`, for 30
  days. A cookie, not the secret held by the page, since `EventSource` sends no headers. Its value is its issue time
  and a random nonce, signed with the secret (HMAC-SHA256). The server keeps no session state, so a session outlives a
  loop restart, and a new secret signs every browser out. Signing out clears the cookie in that browser.
- A signed-in page gets a per-session token, a second HMAC over the same issue time and nonce, and sends it as
  `X-Canopy-Token` on every write.
- Every API route but the session's answers 401 without a valid session. A write (any method but GET and HEAD) also
  needs the token and an `Origin` header naming an allowed host: a same-origin request. The custom header makes a
  cross-origin write need a CORS preflight, which the server never grants.
- A 401 signs the page out: it shows the sign-in page. One to a write says the write was not sent, and a reply being
  written is kept in the tab until it is recorded, so signing in again loses nothing.
- The app's own files (`index.html` and its assets) are served without a session: they hold no journal data, and the
  sign-in page is one of them.

The API, under `{base}/api`, has a read for each page, the event stream, and a write for each act above. Its OpenAPI
schema (`python -m canopy.serve openapi`) documents every route, model, field, and error, so the UI's generated types
carry it as JSDoc.

A message is acknowledged once a tick that read it closes `ok`: the latest tick the API reports carries the newest
message the latest `ok` tick read (§6 step 3), or none before the first. The attention list is that tick's, so until
then a reply has not reached the loop's decisions or the list: the conversation marks each of the operator's messages
after it as waiting for the next tick, and an `awaiting_reply` item whose ticket waits on no question now as answered.
A tick that read a message but did not close `ok` acknowledges nothing, as it leaves the attention list standing.

A guard's refusal is a 409 whose `detail` names the guard and gives its reason, as the CLI prints them. A reply carries
a submission id the form drew when it was rendered, sent again unchanged when the operator retries, so a retried
submission records nothing new.

A request that waits out the journal's busy timeout, because another writer such as the loop held it that long, is a
503 saying the journal is busy and to try again, shown where a refusal is; the server logs a warning naming the route.
The stream never answers it: it only reads. A write that takes the lock once, as a reply does, wrote nothing, and a
reply's submission id makes a retry safe anyway. Any other SQLite error stays a 500. The wait is not shortened, though
each waiting write holds one of the server's request threads, reads' too, for the whole timeout.

The event stream: SQLite has no change notifications, so each open stream watches the journal for commits. When
another connection has committed, or the loop has read its config again (§6), it reads the attention list, the runs,
the tickets, the chores, the spend, the latest tick, and the pause and notice again, in one read transaction, so one
snapshot, and sends each that changed, whole: `attention.updated`, `runs.updated`, `tickets.updated`, `chores.updated`,
`spend.updated`, `tick.updated`, `loop.updated`, and `ticket.changed` naming each ticket whose summary changed. A
notice to workers lapses with no commit, so a stream also reads again once the notice it last sent has lapsed. A new
stream starts with every list, the spend, the latest tick, and the pause and notice, so a pause from the loop's
terminal or the CLI shows as one from the web does. Nothing in the browser polls, but the worktrees (below). A client
leaving a stream is not an error and logs none, and the UI opens a new stream itself when one has been down a while,
since a browser gives up on some failures.

A long history: a year of a busy loop is hundreds of thousands of rows, and every open stream reads its lists again on
every commit. So no read a page or the stream makes costs more as the journal ages; each costs what the page shows.
Each list is read newest first from an index and stops at its limit, and the lists ordered by activity weigh only each
source of activity's newest rows. Two reads still grow with the journal: the spend's all-time total, from an index
alone, and search, which scans (Search, below). A test holds each read to this.

The chores pages (M23): a chore's finding reaches the attention list, and the operator answers it in the browser as
`canopy reply chore:NAME` does in the terminal.

- The chores list is what `canopy status` lists: those configured for this workspace, none while `capacity.max_chores`
  is 0, each with its schedule, its latest run, when it is next due (§19, by the server's clock), its open findings
  (with when each one's unbroken sequence of `ok` runs began, and whether it was dismissed), and its spend over the
  last 24 hours and 30 days (§13).
- A chore's page is any chore defined for this workspace, configured or not, as `canopy reply chore:NAME` takes a note
  to one: its recent runs and its latest 10 notes, which are what its next run's `## Run` section carries. A name no
  chore could have is refused `bad_ref`; one not defined here is a 404. A chore run's page is its whole summary, the
  harness's note, its findings, and its transcript (below); a run is found only under its own chore, and a chore since
  deleted from the config keeps its runs.
- A note and a dismissal, or taking one back, are recorded with channel `web`, as `canopy reply` and `canopy dismiss`
  record them (§19).
- Try now, in the Schedule panel's foot, is `canopy chore try NAME`, recorded (§19): the chore runs now whatever its
  schedule, in a detached `canopy _chore`, and the run shows in its recent runs. It is disabled while a run of the
  chore runs, which the server refuses `running`; one whose prompt, working directory, or process fails is refused
  `not_started`. Otherwise the overseer decides when a chore runs.
- A chore run's summary and its findings are the agent's: untrusted text, rendered as text with control characters
  dropped.
- A note no run of the chore has started since is marked as waiting for its next run: notes wake nothing and no tick
  reads them (§19), so a tick's acknowledgement says nothing about them.

The ticks pages (M24): the decisions are the overseer's reasons for what the loop did and the evaluation corpus for
prompt changes (§6), and "why has the loop not picked this up" is answered where the ticket is.

- The ticks list is the latest 50, each with its overseer's session, cost, tokens, and peak context as a run's (§13).
  A tick's page is the tick, its decisions in the order they were recorded, where its output file is
  (`.canopy/ticks/<id>.log`), its session's transcript, and the file's end (The tick's output, below). It steps to
  the tick before and after it by id, dry runs included, the next found by query, so a gap is stepped over.
- A decision names its subject as `canopy decisions` does: a ticket, a unit as its ticket and repository
  (`ABC-1 (web)`), a repository, `chore:NAME`, `pr:URL` for a PR no ticket owns, or `-` for the whole tick.
- A rationale is the overseer's text: untrusted, its control characters dropped and its line breaks kept, where
  `canopy decisions` prints it on one line. It was cut at 2000 characters when recorded (§6).
- A ticket's page lists the latest 20 decisions about it, its units' included, each with its tick, and, for a ticket
  plans touch, its plan in the plan editor (§25, Reading plans).
- A ticket's page shows its total cost, as the runtime reported it (§13): every run of it, however long ago, and every
  review run that names it, with how many reported nothing. Not the overseer's: a tick decides for the whole
  workspace, so its cost is no ticket's.

The spend page (ROADMAP M33): every agent run records its cost, and the loop records whether each tick was idle (§6,
Idle pacing), so how much of the spend started no work is read from the journal rather than from a one-off analysis of
the log.

- Its breakdown is `canopy spend`'s (§11), from the same code, so the page and the command agree by construction, over
  a week or 30 days by the server's clock: spend by kind and by day, idle ticks' share and the newest idle ticks
  behind it, what woke the ticks, the tickets done and the spend per ticket done, each ticket's and PR's own cost, and
  what each tool returned into the runs' context, so the costly reads are a glance rather than an analysis session.
  Reads only.

The pull requests pages (ROADMAP M32): a PR is a subject of its own, so what the journal holds about one, spread over
a ticket's units, its runs, the reviews (§21), and the decisions, is gathered on its page.

- A PR is known by a ticket's unit (one of the loop's own, reviewed or not), by a review run (any purpose, §21), or
  by the operator's review request (M42), and listed once, most recent activity first. Decisions are not a source for
  the list: they are many, and the list is read again on every tick and every ticket change.
- One PR is named by its URL as a query parameter, since the URL is opaque (§21) and holds slashes; only a plain
  `https://` URL of at most 300 characters is looked up, anything else is a 422. A PR only decisions name (a
  `review.query` match no review has run on yet) has a page too, so it shows why (`wait`, a refusal).
- Each has its own title, as its worker or reviewer last reported it (§8, §21), which need not be its ticket's: a
  PR's title says what changed. The list shows it in place of the ticket's title once one is reported, and beside
  `none` for a PR canopy only reviews.
- Its page: the PR's fields, the runs that pushed to it and any of its ticket's runs still working, its review runs,
  the latest 20 decisions naming it, and its total cost: a run that pushed to two PRs, one per repository, counts on
  each one's page, and once on its ticket's.
- Nothing here writes to a PR. The pages write two things to the journal, through the same code as the CLI and so with
  the same refusals: a grant of one more review (above), and a review request (M42, §21), made and ended among the web
  channel's writes (TRUST_MODEL T8).

The transcripts (M27): what a session did, its tool calls above all, without leaving the browser for
`opencode export`.

- A run's, a chore run's, and a tick's transcript is read from its log, or the tick's output, on each request. Only
  the events (§13) of the session the journal recorded for it are read; any other line (stderr, a setup command's
  output, the harness's markers, another session's events) is left out. Each event is validated (D026): a type canopy
  does not know is left out, and one that does not validate is counted, not shown. The file itself is never served,
  but as a tick's output (below).
- Bounded: at most 32 MiB of the file, to its last whole line; at most 2000 entries and 2 million characters in all;
  each text, output, and error cut at 20,000 characters, and an input at 5,000. A cut says so. Control characters are
  dropped, line breaks kept. A log that is a symlink, a FIFO, or anything but a regular file is not read: it is opened
  without following links and without blocking.
- A transcript says why it has nothing: no session (a template without `--format json`), no log, or none of its
  events yet. A worker run's, a chore run's, and a tick's events reach its log as the agent prints them (§6, §8, §19),
  so a running one's transcript is what it has done so far, read again as its cost or decisions move. A model
  call's reasoning shows only with OpenCode's `--thinking`, which every default template passes, so a transcript says
  why a call made the tool calls it did, not only that it made them; a provider that redacts its reasoning shows none.
  A subagent's calls are its own session's (§13), so a `task` call shows as one tool call with its answer.
- A run or chore run that ended `failed`, `crashed`, or `unknown` names in its Run panel what its session ended on:
  the transcript's last runtime error, else its last failed or refused tool call, which shows its row. Why it ended is
  most of why its page is opened, and the transcript has it last. Not a `timeout`, `unpushed`, or `stopped` run: the
  clock, a branch, or the operator ended those, and a last error would only look like the cause.
- OpenCode reports a shell call completed whatever its exit, so the UI marks a canopy command refused, with its
  guard, by reading canopy's own `Error: <verb> refused (<guard>)` line from its output; no other command's.
- Not on the event stream, since a log can be large: the UI reads a transcript again when the stream moves its run's
  status, latest tool call, or cost, or its chore run's or tick's status.
- Everything in a transcript is agent output: untrusted, rendered as text. It holds whatever a tool read or printed,
  a file's contents or a command's output, which is more than the journal does (TRUST_MODEL T8).
- Rejected: running `opencode export <id>` from the server (a second runtime process behind the listener, and
  OpenCode's storage format to follow); copying events into the journal (unbounded rows for a view), which the
  latest tool call on a running run's row is not: one bounded line, overwritten; serving a run's log, or its tail.
  Revisit when a second runtime prints another shape.

Model calls: to explore what each model call was sent and what it did, not only what it cost.

- A call is sent everything before it: the agent's definition and the runtime's own system prompt and tools, the
  prompt canopy gave the runtime, and every earlier call's output and what its tools returned. So what is new in a
  call's input is, for the first, the prompt, and for each later one, what the call before it asked its tools for.
  The log holds all of that but the prompt, which canopy keeps beside it, and the part ahead of the prompt.
- The prompt is the `{prompt}` the agent command was given: `<id>.prompt` beside a run's or chore run's log, and for a
  tick its state block, written to `ticks/<id>.prompt` before its overseer starts, mode 600. A transcript carries it,
  read as a log is, at most 1 MiB, control characters dropped; no file, or one canopy refuses, is none.
- What no file records is said, not guessed: the agent's definition, OpenCode's system prompt, and its tool
  definitions, most of a short session's third request. `opencode export <id>` and OpenCode's DEBUG log hold none of
  it either. Recording it needs a proxy between the runtime and the provider, which no milestone lists; a recorder
  run by hand split it per agent once (MEASUREMENTS 2026-10-17, SCENARIOS S40).
- Rejected: `opencode export` on request, again. Beside what the log and the prompt hold, it would add only a running
  session's calls before its run ends, for a runtime process behind the listener.

Context by call: where a session's context went, call by call, drawn by the UI from the transcript it already reads.
The runtime counts a call's tokens whole, never per entry, so an entry's part of a step up between two calls is its
share of the step's characters: an estimate, marked `≈`, that sums to the step. The prompt's part of the first call is
its characters over four, never more than that call was sent; the rest is the runtime's own. Rejected: counting each
entry with a tokenizer. The tokenizer is the model's, which canopy does not know and the runtime does not report, and a
step's sum is already exact; a closer split is not worth a dependency per provider.

The output: the transcript keeps only the agent's session, so what the runtime printed on stderr, a run's setup
commands' output, and any line that is not one of its events sent the operator back to the file, most of all for a
tick whose overseer failed or a run that failed before its first event.

- The server reads the end of a tick's output file or a worker run's log as written, on each request: a tick's
  stdout, the `--- stderr ---` line the tick writes, and its stderr (§6); a run's setup commands' output and its
  worker's stdout, stderr, and exit, each under the line `_run` writes (§8). The same checks as a transcript's, at most
  its last 1 MiB from the first whole line in it, control characters dropped and line breaks kept. It says the file's
  size and whether it was cut, or `no_output` when there is none (the tick kept none, or its overseer has not
  started); a running one's holds what it has printed so far, its stderr once it ends. Its end, since that is where a
  failed tick or run says why, and the transcript has the session from its start.
- Everything in it is agent output, rendered as text.
- A tick's and a worker run's only. A chore run's log is its agent's alone (§19), so its transcript says all of it
  but stderr, and a review's adds its diff, which its page shows (§21).

The worktrees page: for each repository in the workspace, its pool's slots as `treehouse status --json` reports them,
read when the page asks. A lease is matched to a running run or review by its lease id, as reconcile matches them, so a
slot names the ticket, run kind, and run that hold it. Each slot is in one of five states: `working` (held by a run or
review the journal shows running), `held` (leased or in use by anything else: the operator's own shell,
`canopy-sync`, or a `canopy:` lease no running run holds, which the next reconcile returns), `dirty` (unleased with
uncommitted changes), `idle` (available), and `broken` (damaged, unverified, or a status canopy does not know). A pool
with no clone, or whose treehouse fails, shows why in its place; the other pools still show. Branch and process names
are shown as text with control characters dropped, and at most 20 processes per slot. A pool holding more slots than
its declared size (`capacity`, §18) says so, and that `canopy workspace sync` removes idle ones. A dirty slot says
what it blocks, since the pool never reuses it and counts it busy (§18), and that discarding its changes clears it:
no canopy command does, since they may be someone's work.

The pools are read at once, so a workspace of many repositories waits on its slowest pool rather than on all of them
in turn. `treehouse status` changes no lease, but it takes the pool's state lock and may rewrite the pool's state file
as it heals it, as reconcile's reads do every tick, so a slow read holds up a lease in that pool for as long as it
takes.

It is not on the event stream: the journal does not hold a slot's branch or processes, and a `treehouse status` per
pool once a second per open page would cost more than the page is worth. The UI reads it again when the running runs'
worktrees change, when the operator asks, and every 10 seconds while a page shows it in a visible tab, since what runs
in a slot, whether it is dirty, and the slots a sync adds or removes never reach the journal.

Search (M31): one box that finds a ticket, or the run or tick that said something, without knowing which page holds
it.

- The server reads the journal on each request. The query is 2 to 200 characters of at most 8 words, or a 422. A hit
  holds every word as a substring of one field, ASCII letters in either case, every character taken literally.
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
    A transcript's page finds lines in its own, in the browser.
  - Review runs. No page shows one yet, so a hit would have nowhere to open.
- Without an index, a scan reads newest first and stops at a source's 21st hit, so a common word answers at once; a
  query nothing matches reads each searched column whole. Rejected for now: SQLite's FTS5. Substring matching needs
  its trigram tokenizer, whose index is about three times the text, kept by triggers on five tables in a migration, on
  a SQLite built with it. Revisit when a real journal's empty search takes more than a quarter of a second.
- Reads only, and not on the event stream: hits are read again when the query changes, not when the journal does.
  It serves only journal text the other pages serve, behind the same session, so T8 is unchanged.

How it serves, true of every page:

- Under one path prefix (`serve.base_path`, empty by default), so a proxy
  can mount it anywhere: the API at `{base}/api`, the app's hashed files at `{base}/assets/`, and `index.html` for
  every other GET or HEAD. One build serves under any prefix. The prefix comes from config, never from a request
  header.
- The fallback to `index.html` never answers under `{base}/api` (an unknown API path is a JSON 404) or for a path
  with a file extension (a missing asset is a 404, not a page). `index.html` is sent `no-cache`, so an upgrade never
  shows a stale UI; hashed assets are cached as immutable.
- A page open across an upgrade keeps its old build, whose lazily loaded pages may no longer be served, so the server
  reports the build on disk and the page offers a Reload while the two differ. It never reloads on its own: the
  operator may be typing.
- Every response refuses framing and MIME sniffing and sends no Referer. `index.html` carries a CSP that allows only
  this origin, plus the inline theme script by its hash, computed from the file served.
- The Host header must name a loopback host or the bind address, on any route: that stops DNS rebinding. An `Origin`
  header on an API route must name one of those too: that stops another site's page from calling the API or opening
  the stream. Ports are not compared, so an SSH forward to another local port works.
- A request body over 1,280 KiB is refused 413, and a chunked one, with no Content-Length, 411, on any route. FastAPI
  reads a body before the session check runs, so without this a client that never signed in could make the server hold
  a body of any size. The largest body the API takes, an edited plan of 100,000 characters (§25), fits under it even
  when every one is escaped as a surrogate pair.
- The event stream is FastAPI's SSE, marked so that no proxy or forward buffers it, with a keepalive comment after 15
  idle seconds. Nothing compresses it.
- The page makes no request to another origin: fonts and icons are bundled.
- `python -m canopy.serve --mock` serves the same API over a journal it seeds from fixtures in a temporary directory,
  for the UI's development server and its end-to-end tests; writes go to that journal, and canopy's GitHub programs
  (§29) are answered from it in process, so a draft sent from the mock posts nowhere. Without `--secret-file` it
  signs nobody in and asks for no session; only mock mode allows that, and it binds loopback only.
- The API documents itself: its OpenAPI schema at `api/openapi.json` and a Swagger UI page over it at `api/docs`,
  under the base path, behind the session like every other API route. FastAPI's stock page loads Swagger UI from a
  CDN, which would run another origin's script beside the operator's journal and session, so canopy serves its own
  copy, from the UI's build, under a CSP as `index.html`'s.

### Trust model changes

M18 and M19 changed TRUST_MODEL T1 and T6. M20 added T8: the listener secret's file and sign-in, the session cookie and
its token on writes, the allowed hosts, escaping, and the residuals they leave; serving a session's prompt beside its
log changed T8 again. Replies on public tickets and trusted reviewers (D089) changed T1: an operator message authorizes
a public ticket's `resume`, as an authorized reply does, and an untrusted reviewer's feedback starts no run without
one.

The overseer prompt carries the rest: private tickets' phases from the state block and no `--label` for them (M18),
and mirroring each new comment (M19).

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
