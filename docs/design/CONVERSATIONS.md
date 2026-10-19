# Conversations

Part of the canopy design, normative like all of it: the journal's conversation, private tickets, its channels, and the
web UI. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Chores,
notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md). Next: [Flaky CI](FLAKY_CI.md).

## 22. Conversations

The journal is the one record of every ticket's conversation: what workers reported and asked, what people replied,
and where each came from. A **channel** is a way into or out of that record: the tracker, the CLI, the web UI, and
Slack later. Channels differ in how they reach the operator and how they prove who wrote a reply. The overseer and
workers never see which channel a message came from, so adding a channel changes no prompt.

A ticket is **public** when one of `tracker.labels` authorizes it, and **private** when the operator starts it in
canopy, or, with `tracker.private` set, when its label brings it in (below). A started ticket is private whatever labels
it carries: the start record wins. A private ticket's conversation never touches the tracker, so the operator can
deliver a ticket a client filed without the agent's reports, its questions, or the operator's answers appearing on it.

### Messages

The journal records each message against its subject (a ticket now, a PR later), with where it came from (a worker's
run, the operator through a channel that authenticated them, or a tracker comment the overseer mirrored), its kind (a
worker's `report` or `question`, the operator's `reply`, a mirrored `comment`), its channel, and, for a reply, the
message it answers when the channel knows it. Bodies are bounded. An operator's is stripped and refused empty or over
4000 characters rather than cut, and carries a submission id unique per subject, so a retried submission, from the web
form or the same `canopy reply` rerun, records nothing new.

Who writes: the harness records a run's `report` and, for a `blocked` run, its `question`, from the result line (§8) in
the transaction that closes the run; operator input goes through one function every channel calls, with the guards in
one place (the key is valid, §17; the ticket was started or is known; the body is within its bound); the overseer
records mirrored comments (below). Agents never write a message directly: no worker command records one, and mirrored
comments authorize nothing.

### Authority stays with the source

- **Public ticket.** Authorization and replies are as §7 and §17 say: the overseer's live read of the tracker. A
  mirrored comment is the overseer's claim, like `--label`; it never makes a ticket `human_replied`, authorizes a split,
  or counts as "try again". The operator may also reply in canopy (D089): an operator message is canopy's own fact, as
  on a private ticket, and is how the operator answers an untrusted reviewer (§7). It stays in the journal.
- **Private ticket.** The journal is the source. Its start record and the operator's messages are canopy's own facts,
  written after a channel authenticated the operator, so the harness checks them in code without reading the tracker
  (D003). Tracker comments on a private ticket are data, whoever wrote them.

This is principle 1's split applied to conversation: for a private ticket the journal owns the conversation, and for a
public one the tracker does and the journal holds a copy.

### Private tickets

The operator's verbs take a reference to a subject (References, below; D075): `canopy start`, `stop [--now]`, `reply`,
`forget`, `grant`, `plan` (§25), and `show`; `canopy status` lists what was started. Each refuses when `CANOPY_TICK_ID`
or `CANOPY_RUN_ID` is set; the harness sets `CANOPY_RUN_ID` for every worker, chore, and review agent.

- `start` is private by construction: canopy cannot label a ticket (D003). It clears a done mark, and warns of a public
  run still going, which may still write to the ticket.
- `tracker.private` (off by default, D119) starts labeled tickets privately: the first dispatch of a ticket canopy never
  ran, authorized by its `--label`, writes the start record in the transaction that inserts the run. From then on it is
  an ordinary private ticket, and removing the label does not stop it. A ticket already worked in public, and a ticket
  to split, stay public. The label stays visible (REQUIREMENTS R11): the switch hides the conversation, not the work.
- The start record is the authorization. Only the operator's commands write it, and, under `tracker.private`, a
  labeled ticket's first dispatch. `canopy dispatch` checks it in code, a guard where a public ticket's `--label` is a
  claim (D051), and always renders the private prompt and runs the private worker for a started ticket, whatever the
  overseer passed. `--kind split` is refused `private`: a split creates tickets in the tracker.
- `stop` marks the start record stopped. A stopped ticket stays private and is dispatched by nothing, whatever labels
  it carries, until started again; its waiting question waits on nothing. Without `--now` a running run finishes; with
  it the run is ended as reconcile ends a crashed one (§6) and marked `stopped`, which raises no attention item and
  counts toward attempt limits. `stop` refuses a ticket never started: a public ticket stops when its label is removed.
- `stop` and `dispatch` cannot interleave: each is one write transaction, and the run reads the record again before it
  starts its worker, ending `stopped` if it was stopped.
- The private worker runs `canopy-worker-private` with `runtime.private_worker_cmd`. Its definition denies every tool
  of the tracker's MCP server (`tracker.mcp_server`) by wildcard and allows only `tracker.read_tools` by name, so a
  write tool no list names fails closed; it denies the tracker CLIs canopy knows but for `gh` commands that read a PR
  and its CI. Tools that read or write by argument are denied. With no read tools for the provider, `start` and the
  dispatch refuse `no_read_tools`; a wrong list fails closed. The harness refuses a private run whose worktree's
  OpenCode config names the tracker server's tools (D044), since a repository rule could reopen a write tool.
- A private ticket's phases (§7) come from the journal: `needs_human` when its latest run ended `blocked` with no
  operator message since, `human_replied` when an operator message is newer than its message cursor, a cursor of its
  own. The harness raises `awaiting_reply` every tick for a question with no reply (§14). After a failed run, "try
  again" is an operator message.
- The private worker's prompt carries the latest messages, each labeled the operator's (an instruction) or an earlier
  worker's or a mirrored comment (data). On either kind of ticket the overseer's `--context` points at a message by id
  and never quotes it.
- `canopy reply` also takes a public ticket a tick has seen (D093): the state block and every public `implement` and
  `resume` prompt carry its operator messages, labeled the operator's, with the workers' questions as data. A public
  worker can write to the ticket, so keeping those messages off it is its prompt's rule, not a guard (TRUST_MODEL T6).

### Forgetting a ticket's work

`canopy forget REF` drops a ticket's work so the loop starts it over (D086), public or private. It refuses a ticket
the journal does not know, one a run is working, one a split made children of, and one with nothing to drop. It clears
the ticket's branch, phase, and done mark and deletes its units, and records the forget as an event kept for good. The
loop's reads skip what came before the latest forget, so a forgotten ticket reads to the overseer as one never
dispatched. It keeps the rest: every run still counts toward attempt limits and the CI cooldown (D030), the cursors
and the start record stay, and `show` prints the whole history. It holds the dispatch lock, so a dispatch that read the
old branch cannot record it again. It touches nothing outside the journal: the old PR and branch on origin are the
operator's to close and delete, and the command names them.

### Granting attempts

`canopy grant REF KIND` lets the loop keep working one unit at its attempt limit (§8) without raising the limit for
every ticket. It takes `implement` or `resume`; `fix-ci` is refused, since its runs count as resumes, a split's limit
only config raises, and a plan's is the ticket's (§25). `--repo` names the unit. Grants are only ever added: the
unit's limit for the kind is `policy.max_<kind>_attempts` plus its grants, so lowering the policy lowers it too. A grant
resets no count (D030) and dispatches nothing: the next tick decides from the ticket's phase. The state block shows
the grants beside the attempts.

`canopy grant URL review` does the same for a PR at `policy.max_reviews_per_pr` (§21), keyed by the PR's URL. The web
UI grants through the same code, one run a click, without confirmation: one more run of a kind the loop already ran is
the least a grant can do, and the overseer still decides whether to use it.

### References

A reference names a subject by its shape, so no kind needs a flag: a ticket key (§17) has no `:`, `#`, or `/`. Every
form is parsed and validated in code, and a verb a kind does not support is refused `unsupported`. Messages and start
records are keyed by subject, so a new kind adds a row here, not a table.

| Reference | Subject | Verbs |
|---|---|---|
| `PROJ-123` | a ticket | all, and the overseer's `mirror` |
| `api#42`, or the PR's URL | a PR | `grant` (its reviews), `start --review` and `stop` (§21), `show`, each by URL |
| `chore:NAME` | a chore (§19) | `reply` (its notes), `dismiss`, `show` |
| `run:ID` | a run | `show` |
| `review:ID` | a review run (§21) | `dismiss`, `send` |

### Tracker comments in the journal

The journal holds a copy of each ticket's tracker comments, so the operator reads every conversation in one place
(D081). Each tick the overseer records each comment past the ticket's mirror cursor with `canopy mirror`, which
requires `CANOPY_TICK_ID` (D020). The text goes on stdin through a quoted heredoc whose delimiter the state block draws
fresh and random each tick, so no comment can end it early and run what follows. Author, time, and id are validated in
code; a body is cut at 2000 characters and marked; at most 100 `mirror` calls a tick. A mirror is idempotent on the
comment id and recorded as a decision. A comment bearing a worker's marks (D069) is recorded with source `worker`.
Either way it authorizes nothing: phases, `awaiting_reply`, and the loop's wake read operator messages only. The mirror
cursor is its own, apart from the comment cursor the phases use, and only `canopy mirror` moves it. A dry run records
the mirror but moves no cursor. The mirror lags by up to a tick, and an edited or deleted comment is not updated.

### Waking the loop

During the wait (§6), the operator's acts end it and run the next tick, no sooner than `loop.min_gap_minutes` after the
last one began: a message to a ticket, a ticket started or stopped, a grant, or a notice to workers set or cleared (§8).
A note to a chore does not; its next run reads it (§19). The tick records what woke it and is not idle. Every channel
wakes it the same way (D073). Capacity, attempt limits, and cooldowns hold as for any tick.

### Channels

| Channel | In | Out | Proves the operator by |
|---|---|---|---|
| tracker | comments, mirrored | worker comments on public tickets | `trust.authorized_repliers`, read by agents |
| cli | the operator's verbs | `canopy show`, `canopy status` | the operator's shell (T1) |
| web | the CLI's verbs, and the writes below | pages | the listener secret (TRUST_MODEL T8) |
| slack (later) | thread replies | §20's sink | Slack user ids the operator lists |

Outbound, every channel uses §20's events: a sink posts them, and the web UI reads the same journal.

### The web UI

The operator's view of the journal in a browser, with the CLI's verbs beside it. Its pages are in `ui/DESIGN.md` and
the guide; this is what the server promises. Its controls are TRUST_MODEL T8's.

- `canopy loop` serves it from a thread (D073), on unless turned off, on `serve.bind`: loopback by default, or a
  private address. Every `serve.*` key is private (T7). Without a valid listener secret it says why and serves nothing;
  the loop goes on. It serves plain HTTP, also on a private address (D076). A server failure is logged and the server
  restarted; it never ends the loop.
- Each request opens its own journal connection, never takes the tick lock, and writes only through the functions the
  CLI's verbs use, with channel `web` and their guards: start, stop (and stop now), reply, forget, grant, dismiss, send,
  `canopy chore try`, pause and resume (§6), notices (§8), plans (§25), review requests (§21), and memory (§28).
  Beyond the verbs it writes only the operator's own words on a plan (§25). Reload and tick now ask the loop, as SIGHUP
  and `t` do (§6), and write nothing.
- A forget, of a ticket or a memory, carries its key typed out, and the server refuses `not_confirmed` before reading
  anything when it does not match, so no client skips the challenge.
- The one process it runs is `treehouse status --json`, for the worktrees page; it changes no lease.
- Signing in: the listener secret (`canopy secret` writes one) is given once to the sign-in page, compared in constant
  time, and answered with a signed session cookie; the server keeps no session state, so a new secret signs every
  browser out. Every API route but the session's needs the session; a write also needs the session's token in a header
  and a same-origin `Origin`. The Host header must name a loopback host or the bind address. A request body over the
  largest the API takes is refused before the session check. The app's own files are served without a session.
- Every value from the journal is untrusted: rendered as text, never as HTML, control characters dropped, laid out by
  a small parser of canopy's own rather than a Markdown library. An http or https URL is a link showing itself (D113).
  The page makes no request to another origin, its API docs page included.
- A run's, chore run's, or tick's transcript, prompt, and output are read from its log on each request: only the
  session the journal recorded, bounded, from a regular file opened without following links, rendered as text, never
  served as a file. Rejected: running `opencode export` from the server (a second runtime process behind the listener)
  and copying events into the journal (unbounded rows for a view).
- `src/canopy/serve/` is the only package that imports the web stack. canopy's code opens no socket itself (§20); the
  server listens and calls out to nothing, so T2's "no outbound call" stands.
- `--mock` mode, for the UI's development, serves a seeded journal of its own, posts nowhere, and binds loopback only;
  only it may sign nobody in.

The API's contract: a guard's refusal is a 409 naming the guard, as the CLI prints it; a write that waited out the
journal's busy timeout is a 503 and wrote nothing. A message is acknowledged once a tick that read it closes `ok`, and
the attention list is that tick's, so until then the UI marks a reply as waiting for the next tick. The event stream
sends each list a page shows again, whole, from one snapshot, whenever the journal changes; nothing in the browser
polls but the worktrees, which the journal does not hold. No read a page or the stream makes costs more as the journal
ages, but the spend's all-time total and search.

### Search

One box finds a ticket, or the run or tick that said something: every query word as a case-insensitive substring of
one field, over tickets' keys, branches, and PRs, messages, chore runs, decisions, and ticks, newest hits first. It
reads only, and serves only journal text the other pages serve, so T8 is unchanged. Ticket titles (the journal holds
none) and transcripts (unbounded) are not searched. Rejected for now: SQLite's FTS5, whose trigram index is about three
times the text; revisit when a real journal's empty search takes more than a quarter of a second.

### Trust model changes

Private tickets and mirrored comments changed TRUST_MODEL T1 and T6; the web UI added T8. Replies on public tickets and
trusted reviewers (D089) changed T1: an operator message authorizes a public ticket's `resume`, as an authorized reply
does, and an untrusted reviewer's feedback starts no run without one.

### Open

- Whether a private worker should have no tracker MCP server at all. It would then need the ticket's text from
  elsewhere; the overseer's `--context` holds 2000 characters.
- Whether a private ticket's PR body and branch should name the ticket key.
- Deleting a ticket's conversation, for client data the operator must not keep. `forget` keeps it.
- A forgotten ticket's attempt counts are not in the state block, which shows them per unit, so the overseer learns a
  limit from the `attempt_limit` refusal rather than before dispatching.
- Mirrored comments edited or deleted after the mirror.
- PR review comments in the journal, alongside ticket comments, once PRs are subjects.
- Slack replies: a bridge holding a Socket Mode connection that runs `canopy reply` (a uv workspace member, like the
  Slack sink, so the harness stays free of network code), or the overseer reading Slack through MCP (§20). Either needs
  a T1 change naming Slack user ids.
