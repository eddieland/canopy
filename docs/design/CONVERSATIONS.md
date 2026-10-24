# Conversations

Part of the canopy design, normative like all of it: the journal's conversation, private tickets, its channels, and the
web UI. Sections are numbered across the whole design; the [README](README.md) has the map. Previous: [Chores,
notifications, and reviews](CHORES_NOTIFICATIONS_REVIEWS.md). Next: [Flaky CI](FLAKY_CI.md).

## 22. Conversations

The journal is the one record of every ticket's conversation: what workers reported and asked, what people replied,
and where each came from. A **channel** is a way into or out of that record: the tracker, the CLI, the web UI, and
Slack. Each proves the operator its own way: the tracker by `trust.authorized_repliers`, read by agents; the CLI by
the operator's shell (T1); the web UI by the listener secret (TRUST_MODEL T8); Slack by the user ids a `slack` source
lists, checked in code, for replies in the sink's ticket threads and mentions of canopy's bot in its channel (§20).
Outbound, every channel uses §20's events. The overseer and workers never see which channel a message came from, so
adding one changes no prompt.

A ticket is **public** when one of `tracker.labels` authorizes it, and **private** when the operator starts it in
canopy, or, with `tracker.private` set, when its label brings it in (below). A started ticket is private whatever labels
it carries. A private ticket's conversation never touches the tracker, so the operator can deliver a ticket a client
filed without the agent's reports, its questions, or the operator's answers appearing on it.

### Messages

Each message is recorded against its subject, with its source (a worker's run, the operator through a channel that
authenticated them, or a tracker comment), its kind, and its channel. The harness records a run's report and
a `blocked` run's question from the result line (§8), in the transaction that closes the run. Operator input goes
through one function every channel calls, which refuses an empty or overlong body rather than cut it and records a
retried submission once. Agents never write a message directly. An operator message, or a task submitted (§36), or a
start, stop, grant, or notice (§8), from any channel, ends the loop's wait (§6, D073); a note to a chore does not (§19).
A message is acknowledged once a tick that read it closes `ok`; the first live one answers it with canopy's own note on
the ticket, what it decided there and why, so a message is never left unanswered while the loop waits. No agent's prompt
has one.

### Authority stays with the source

- **Public ticket.** Authorization and replies are the overseer's live read of the tracker (§7, §17); a tracker
  comment in the journal is only a copy. The operator may also reply in canopy (D089), which is how they answer an untrusted
  reviewer (§7); the message is canopy's own fact and stays in the journal.
- **Private ticket.** The journal is the source. Its start record and the operator's messages are canopy's own facts,
  written after a channel authenticated the operator, so the harness checks them in code without reading the tracker
  (D003). Tracker comments on a private ticket are data, whoever wrote them.

### Private tickets

The operator's verbs (start, stop, reply, forget, grant, plan, show) name a subject by the shape of its reference, a
ticket key, a PR's URL, a chore, or a run, each validated in code (D075). They refuse inside a tick or any agent's run,
so no agent can lift a limit that bounds it (TRUST_MODEL T1).

- The start record is the authorization. Only the operator's commands write it, and, under `tracker.private` (off by
  default, D119), the first dispatch of a labeled ticket canopy never ran; removing the label then does not stop it.
  The label stays visible (REQUIREMENTS R11): the switch hides the conversation, not the work.
- Dispatch checks the start record in code, where a public ticket's label is a claim (D051), and always runs a started
  ticket's private worker and prompt.
- `stop` keeps the ticket private and lets nothing dispatch it until it is started again. Stopped now, its run is ended
  as reconcile ends a crashed one (§6) and still counts toward attempt limits. Stop and dispatch cannot interleave.
- The private worker reads the tracker, and writes to it only to file follow-ups, which authorize nothing (§18): it
  is allowed the tracker tools config names as read tools, so a wrong list fails closed, the provider's tools that
  create a ticket, whole, and on GitHub, whose server its PR goes through, the PR tools, which the planner never
  gets; with no read tools a private run is refused (TRUST_MODEL T6, D044), and a deny in the operator's own config
  cannot take the create tools back (D021). `policy.max_follow_ups = 0` has workers file none and
  records none; only the MCP server's own tool selection, where it has one, takes the tools away. A follow-up a
  private run filed is a public ticket like any other, worked only once the operator labels or starts it.
- Its phases (§7) come from the journal: `needs_human` after a `blocked` run with no operator message since,
  `human_replied` after one. The harness raises `awaiting_reply` for an unanswered question (§14).
- Workers' prompts carry the operator's messages as instructions, and reports and tracker comments as data; the
  overseer points at a message by id and never quotes it. On a public ticket (D093), keeping those messages off the
  tracker is the worker's prompt's rule, not a guard (T6).

`canopy forget` drops a ticket's work, public or private, so it reads to the overseer as never dispatched (D086). It
keeps every run, so attempt limits and the CI cooldown still hold (D030), and touches nothing outside the journal: the
old PR and branch are the operator's to close.

### Granting attempts

`canopy grant` lets the loop keep working one unit at its `implement` or `resume` attempt limit (§8), or one PR at its
review limit (§21), without raising the limit for every ticket. Grants are only ever added to the policy's limit, so
lowering the policy lowers it too. A grant resets no count (D030) and dispatches nothing; the overseer still decides.

### What the operator has seen

A result is **new** to the operator until they see it in any channel: a review that ended with findings, or with any
verdict when they requested it, on its page, with `canopy review show ID`, or marked from the reviews list. A clean
review the loop started on its own is never new, so routine reviews do not bury the ones to read. The journal keeps
the mark by the subject's reference, so every channel agrees on what is new, and another kind of subject joins by its
own (Open, below). A mark authorizes nothing and no agent reads it; only the operator writes one, so an agent cannot
hide a result by marking it seen.

### Tracker comments in the journal

Each comment the tracker source observes (§30) is recorded once in its ticket's conversation, in code and as the
connector read it, so the operator reads every conversation in one place; no agent writes one. A comment bearing a
worker's marks (D069) is recorded as a worker's. Either way it authorizes nothing: phases, `awaiting_reply`, and the
loop's wake read operator messages only. An edit after its first read is not followed, and without a tracker source no
comment reaches the conversation.

### Attachments

The operator may attach text files to a ticket, public or private, or to a task (§36): what someone sent them, such as
a design doc, for its runs to check against the code. Only the operator's channels attach or remove one, refused inside
a tick or any run (TRUST_MODEL T1), on a ticket canopy knows or a task not stopped. Its text is data, never an
instruction: what to do with it is the operator's reply, or the task's text. Guards in code take only UTF-8 text and
hold each subject to `policy`'s limits on how many files it holds, how large each is, and how large all are together,
each under a ceiling no file raises, since every later run carries all of them. Rejected: canopy reading PDFs or
documents, which would put a parser of untrusted files in the harness; the operator exports one as Markdown.

An attachment is kept as a plan is (§25), an operator-only file in the state directory, and each run of its subject
gets a copy in its worktree, excluded from git, which its prompt names as data. Removing one deletes its file and keeps
its record, so the journal still says what the subject held.

### The web UI

The operator's view of the journal in a browser, with the CLI's verbs. Its pages are `ui/DESIGN.md`'s and the guide's,
and its controls TRUST_MODEL T8's.

- `canopy loop` serves it from a thread (D073), on loopback or a private address (D076). Without a valid listener
  secret it serves nothing; a server failure never ends the loop. Only its development mode, on loopback with a journal
  of its own, may skip signing in.
- It writes only through core's functions, with their guards: the ones the CLI's verbs use, and, for what no command
  would do, one of its own that TRUST_MODEL T8 names, such as the operator's own words on a plan (§25), what they have
  seen, and the limits and trust settings §12 lists, which Settings' Limits and trust page writes to the workspace's
  private file and then reloads (`serve.config_edit`, D128). It never takes the tick lock. A page needs no CLI verb for
  what nobody would type. The server, not the page, refuses a forget not typed out.
- It records each write it lets through, and each sign-in, in the journal, so the operator can see what a holder of
  the secret did; never a request's body or credentials (T8).
- Every value from the journal or a run's log is untrusted and rendered as text (D113). `canopy.serve` alone imports
  the web stack, and calls out to nothing, so T2's "no outbound call" stands. No read costs more as the journal ages,
  but the spend's all-time total and search.

### Search

One box finds a ticket or a task, or the run or tick that said something, by substring over the journal's text. It
serves only what the other pages serve, so T8 is unchanged. Rejected for now: SQLite's FTS5, whose index is three
times the text.

### Trust model changes

Private tickets and tracker comments changed TRUST_MODEL T1 and T6, and the web UI added T8. Operator messages on
public tickets (D089) changed T1: one authorizes a `resume` as an authorized reply does. Seen marks changed T8: the web
writes what no CLI verb does (D127). Limits and trust (M41) changed T8 too: the web writes a few config keys, limits
within bounds and trust only stricter (D128).

### Open

- Whether a private worker should have no tracker MCP server at all, and where it would read the ticket's text.
- Deleting a ticket's conversation, for client data the operator must not keep. `forget` keeps it.
- Seen marks beyond reviews: a plan waiting on the operator (§25), each new plan its own subject, then a chore's
  findings and a run's drafts, each counted where the operator reads it.
