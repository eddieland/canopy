# Review replies

Part of the canopy design, normative like all of it: the replies to coworkers' review comments that workers draft and
the operator sends. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Agent memory](MEMORY.md).

## 29. Review replies the operator sends (M53)

ROADMAP M53, REQUIREMENTS R20. §8, §21, and §22 describe workers that post their own comments; this section says what
changes when they draft them instead.

A `resume` worker answers coworkers' review comments as the operator (D010), and the operator first reads what it said
when their coworkers do. Every reply starts with `CANOPY:`, which tells the reader a model wrote it and the loop to
read past it (D069), but it is still the operator's name on it. So under `trust.review_replies = "approve"`, the
default, a worker drafts every comment it would have posted, canopy reads the PR's review threads itself, and the
operator reads each draft on its thread, on the PR's diff, edits or drops it, and sends the ones they approve. canopy
posts exactly that text, unmarked: the operator approved it word for word, so it is their comment.

Settled by the operator (2026-10-17): canopy ships its own GitHub program (REQUIREMENTS C7, D003); `approve` is the
default; every comment a worker would post is drafted; nothing canopy sends resolves a thread; a newer draft supersedes
an unsent one; a send is one comment review; the push does not wait for the drafts; GitHub Enterprise works as
github.com does.

### Configuration

Private keys (§12), never the workspace file, since a shared file must not decide what is said in the operator's name
(TRUST_MODEL T7):

```toml
[trust]
review_replies = "approve"   # approve | post

[connect.sources.github]     # unset: canopy's own two programs, as shown
kind = "vcs"
cmd = ["canopy-connect-github"]
post_cmd = ["canopy-post-github"]
timeout_minutes = 2
```

- `approve` drafts; `post` is how workers worked before this section, every prompt the same bytes, held by a snapshot.
  The default changes what workers do on upgrade, so the release notes say so, and `canopy status` names the setting
  and the drafts waiting.
- A source is configured as ROADMAP M36's connectors are: argv with no shell, a timeout, private. This section defines
  the `vcs` source's table and its `post_cmd`, and runs them only for drafts (The threads, read in code, below); M36
  grows the reader into the whole connector. Unset, the `vcs` source is canopy's own programs, so `approve` needs
  nothing configured.
- A `tracker` source with a `post_cmd` posts a ticket's drafts (The drafts, below). There is none by default: the
  harness never branches on `tracker.provider`, which is shared (§17), so the operator names the command, such as
  `canopy-post-github` for GitHub Issues.
- A run keeps the setting its prompt was rendered under (§8, step 3), recorded on it, as memory's modes are (§28).

### The drafts

Under `approve`, an `implement` or `resume` worker, public or private, pushes as before, comments on no PR, and
comments on the ticket only as `ticket` below says. A push never waits on the drafts: ROADMAP M54 is how the operator
approves work before it is pushed. Its result line gains `drafts`, parsed apart from the result and never stored in
`result_json`, as memory's fields are:

```json
{"drafts":[{"on":"thread","pr":"https://...","comment":2468013579,"did":"changed|declined|answered","text":"..."},
 {"on":"pr","pr":"https://...","text":"..."},{"on":"ticket","url":"https://...","text":"..."}]}
```

- `thread`: a reply to a review thread, naming a review comment on it by the id in its URL (`#discussion_r<id>`), the
  one every tool shows; canopy finds the thread from that. `did` says whether the run made the change, declined it, or
  answered a question. A decline the worker would have argued on the PR is a draft too, and the run still reports
  `blocked` with the disagreement.
- `pr`: at most one a PR, carrying everything the prompt would have had it post there: a review's body answered, what
  it fixed in CI, a note on a conflict.
- `ticket`: at most one a run, its question when blocked and otherwise what it did, only while a `tracker` source has a
  `post_cmd`, and never on a private ticket, whose worker writes nothing to the ticket (§22). It names the ticket's URL
  as the worker read it; the page shows it beside the text. Without a tracker post command the worker posts its ticket
  comments itself, marked, as under `post`.
- A PR's title and body are not drafts: they describe the change, not the operator's words (§8). A split's tickets and
  its comment on the parent are not either: they record what it made, at an authorized replier's request.
- Bounds, in code, each draft refused alone with a harness note on the run, never cut or cleaned: at most 30 a run; a
  text at most 4000 characters, line feeds allowed, every other character §28's bounds refuse refused, a secret's shape
  included. A `thread` or `pr` draft naming a PR that is not one of the run's units' is `not_ours`, and a `ticket`
  draft on a run that may not make one is `no_post`. The operator's edits are held to the same bounds. Under `post`,
  `drafts` a worker sends anyway are stored nowhere.
- The prompts' "Reply on the PR to each comment you addressed", their PR and ticket comments, and their comment marks
  render from `{{COMMENTING}}`, which under `post` is the text it replaced. Under `approve`, an override without it is
  `bad_prompt` (§8, step 3): an older override would have its worker post in the operator's name.

The marks (D069) change use, not meaning. A comment carrying them is never authority, under either setting. Under
`approve` they go on what still posts without the operator, a ticket comment with no tracker post command; under
`post`, on every comment. What the operator sends carries none.

A blocked worker adds `needs_human_label` as before, whether or not its question waits as a draft: labels are not
speech, and the operator left it to the simplest rule (2026-10-17).

### The threads, read in code

canopy reads review threads itself, never through the worker, so the page shows a thread as GitHub holds it and a
draft can answer only a thread that exists.

- After a run under `approve` closes with its drafts (§8, step 7), `_run` runs the `vcs` source's `cmd` for each PR of
  the run's units, and records what it read in `observed_reviews` (M36): each thread's path, line, side, and whether it
  is outdated or resolved, and each comment's id, author login, time, and body, cut as a mirrored comment is (§22). The
  slots are already returned, so the read holds none.
- A draft is unchecked until a whole read of its PR, one whose `end` line covers it. A `thread` draft whose comment that
  read did not return is refused (`unknown_thread`), with a harness note on the run; a `pr` draft needs only the read.
  A `ticket` draft needs none.
- A read that fails, times out, or ends without its `end` line refuses nothing: the drafts stay unchecked, with a
  harness note, `drafts_waiting` says the threads could not be read, and each tick's reconcile (§6, step 3) reads the
  PR again until a read is whole. No unchecked draft can be sent, so an outage delays the replies and never drops them.
- Once checked, a draft supersedes an unsent draft of an earlier run for the same thread, the same PR's comment, or
  the same ticket: shown struck, never sendable, and the page warns when the one superseded carried the operator's
  edits.

PR review comments thereby join the journal (§22, Open), read only and authorizing nothing: the overseer and workers
still read the PR live.

### Sending

Sending is the operator's act, from the PR's page or the CLI, and one function serves both, in `core`, as a plan's
approval does (§25). Every verb refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, as `send` and
`reply` do: an agent that could send a draft could post as the operator.

- `canopy draft list [KEY|URL]` lists the drafts waiting, each with its thread as last read, its text, and its hash;
  `canopy draft show run:ID` prints one run's, with what became of each. A draft is `run:ID` and its number, 1 to 30,
  as a review's findings are (§21).
- `canopy draft edit run:ID N --text TEXT` makes a new version of its text, kept beside the run's own. `canopy draft
  drop run:ID N...` dismisses drafts as a finding is dismissed, and `--undo` takes that back.
- `canopy draft send run:ID N@HASH...` sends drafts, each with the hash of its text as the operator last saw it. In
  order, it refuses:
  - `stale`: the draft's text is no longer that hash, since an edit in another tab or shell, as M41's config write is.
  - `unchecked`, `superseded`, `dropped`: as above.
  - `thread_changed`: a whole read of the PR, made now, shows a comment on the draft's thread newer than the draft's
    basis, at first the run's start, other than one the operator sent through canopy. The refusal names the new
    comments, the page shows them under the thread, and it moves the draft's basis to the newest of them, so sending
    again posts unless yet another arrives. A read that is not whole refuses as `unchecked`.
- What reaches GitHub is the text, verbatim, with no marks. The drafts sent together for one PR are one review, so a
  reviewer gets one notification: `post_cmd` opens a pending review, adds each reply to its thread, puts a `pr` draft in
  the review's body, and submits it as `COMMENT`. A `ticket` draft is one comment through the tracker's `post_cmd`.
- A draft is posted at most once. The send claims its drafts in one transaction, so two sends at once post once, and a
  draft already sent records nothing new. A post that fails before it submits removes its pending review and posts
  nothing, and the drafts can be sent again; GitHub allows one pending review per author, so one the operator left
  open in the browser fails it, and the refusal says so. A post that ends without saying whether it submitted leaves
  its drafts `unconfirmed`, never sent again by canopy until a whole read settles it: a comment on the thread by the
  login the program posted as, with exactly that text, posted after the send began, is the draft sent; none, and it
  can be sent again.
- Each sent draft records the comment's id, URL, and time, the run that drafted it, whether the operator edited it, and
  the channel. Nothing canopy sends resolves a thread, approves, or requests changes: that stays the reviewer's.

Stopping a ticket leaves its drafts sendable. `canopy forget` drops its unsent ones, whose unit is gone, and keeps the
sent records. M47's pass (§26) deletes no draft: a sent one is how canopy knows its comment.

### Read back by id

A sent reply carries no mark and is by the operator's login, so the loop would read it as new review feedback, or as
an authorized reply; canopy knows it instead by the id the post returned. The state block lists, per PR, the comments
the operator sent through canopy, and the overseer's and the `resume` worker's prompts say they are neither review
feedback nor a go-ahead: the operator's answer to the reviewer, already made. The `review` cursor (§7) passes them.
ROADMAP M37 moves that check into code.

### Waiting drafts

The harness raises `drafts_waiting` (§14), the operator's alone, as memory's items are (§28): a harness reason the
overseer's view of the list leaves out. One per unit with a sendable or unchecked draft, and one per ticket with a
ticket draft, open until each is sent, dropped, or superseded, or the PR merges or closes; its detail counts them, says
when the threads could not be read, and opens the PR's threads. It holds nothing else: the push already happened, and
the cursors passed the comments the run was given. A ticket draft shows on the ticket's page, and sending a question
answers nothing until an authorized replier does.

### On the PR's diff

The PR's page shows its threads on the diff (§22, The web UI): each thread at its line, an outdated one, or one whose
line the diff does not show, under its file as a finding outside the diff is (§21, The diff), its comments as text by
their authors, and under it the draft, edited as plain text, with Send and Drop. A thread no draft answers shows as it
is, and the page sends one draft or several together. The attention item opens this view. How it looks is
`ui/DESIGN.md`'s.

- The diff is the run's own: `_run`, under `approve`, takes it at the run's head once its pushes are verified (§8,
  step 5), from its merge base with the base branch, as a review takes its commit's, and the server reads it with the
  same bounded reader. When the PR's head has moved past it, the page says so.
- A draft is a worker's text, written from coworkers' comments, and a thread is coworkers' text: both are rendered as
  text, never Markdown, every hidden character named, as memory's are (§28). GitHub renders the reply once it is sent.

### canopy's GitHub program

`packages/canopy-github`, a uv workspace member, stdlib only and importing nothing from canopy, as the Slack sink is
(§5, §20), with one fake for the tests. Its two commands:

- `canopy-connect-github` reads. On stdin, `{"prs":["https://..."]}`; on stdout, M36's `pr` and `review` lines for
  each PR, every thread and comment paged, then an `end` line naming the PRs it read whole.
- `canopy-post-github` writes, the first program canopy ships that writes to GitHub. On stdin, one PR's drafts
  (`{"pr":URL,"body":TEXT|null,"replies":[{"comment":ID,"text":TEXT}]}`) or one ticket's (`{"issue":URL,"ticket":KEY,"body":TEXT}`);
  on stdout, the login it posts as, each new comment's id and URL, and an `end` line saying whether it submitted. It
  refuses a ticket URL that is not an issue numbered as its key. It never approves, requests changes, or resolves a
  thread.

The host is the PR's own, read from its URL by the program, never by the harness, with the token `gh` holds for that
host, read when the program runs, so GitHub Enterprise works as github.com does and the harness never holds a token
(TRUST_MODEL T2). Lint bans importing it from the harness, as it bans the sink. Rejected: posting through an agent (the
text it posts is the model's last word, not the operator's); the harness calling GitHub (D003).

### Agent definitions

Under `approve`, `canopy-worker` is rendered from the setting, as the private worker's definition is from the user
config (§13), and both deny the GitHub server's comment, reply, and review-comment tools by name, and `gh pr comment`
and `gh issue comment` in bash, as defense in depth. Under `post`, they are as before.

### Code shared with later milestones

Built once, for M32, M43, M44, M54, and this section: the diff with cards on its lines, for any item anchored at a path
and line, which M32's page keeps the look of; keeping and serving a diff, moved from `reviews` down to `core`, since
`runs` may not import a feature (§5); drafts, their versions, and sending one exactly as approved, in `core`, which
M43's review drafts reuse with a review run as their source; a thread's card, shared with a plan's comment threads
(§25), whose models stay apart, since a plan's threads are the operator's text and a PR's are other people's (T1);
one GitHub program for M36's connector, these reads and replies, and M43's review post; and the thread ids, by which
M54's plans show their proposals on the same threads.

### Trust model changes

To be approved by the operator in merging the PR that builds them:

- T1: a draft is untrusted text, written from coworkers' comments, until the operator sends it, and is rendered as
  text. PR review threads join the journal, read only.
- T2: a second program canopy ships makes outbound calls, with `gh`'s token, never the harness's.
- T5: a sent reply speaks as the operator, unmarked, word for word as approved, and the journal says which run drafted
  it; the marks stay on what workers post themselves.
- T6: under `approve`, a worker's comment leaves the machine only as the operator sent it, and its definition denies
  the GitHub server's comment tools by name.
- T8: the web channel edits, drops, and sends drafts. Its residual gains that a stolen session can post text of its
  choosing, as the operator, on a PR or ticket a run drafted for.
- §6: "never submit a PR review of any kind" becomes never one that approves or requests changes: a comment review only,
  of text the operator sent word for word, the change M43 also needs.

D003 states the programs as built, D069 that a comment the operator sent through canopy is known by id, and AGENTS.md's
"No GitHub client" line is scoped to the harness package, as M36 plans.

### Open

- Whether a run's account of what it did, drafted for the ticket, is worth the operator's send, or should post marked
  without them, as on a tracker with no post command.
- Whether a draft on a PR that merged or closed should still be sendable, as it is.
- Editing or deleting a sent reply from canopy. The operator does it on GitHub for now.
