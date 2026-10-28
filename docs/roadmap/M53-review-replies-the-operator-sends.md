# M53. Review replies the operator sends

REQUIREMENTS R20, DESIGN §8, §21, and §22, TRUST_MODEL T1, T2, T5, T6, and T8, D003, D069. Needs M32. Asked for by
the operator (2026-10-17): a `resume` worker answers coworkers' review comments in the operator's name before the
operator has seen what it says, and every answer starts with `CANOPY:`. The operator wants to read each planned reply
in place, on its thread on the PR's diff, edit or drop it, and send the ones they approve, as their own words and
without the mark. Sketch only; the design comes first, as a new design file (§29). The operator settled its open
questions on 2026-10-17: canopy ships its own GitHub program (C7, D003), `approve` is the default, nothing is resolved,
every comment a worker would post is drafted, a newer draft supersedes, a send is one comment review, the push does not
wait, and GitHub Enterprise is supported.

- **The setting.** `trust.review_replies`, private (T7, since a shared file must not decide what is said in the
  operator's name): `"approve"`, the default, where the operator sends every comment a worker would have posted, or
  `"post"`, where workers post as today. The default changes what workers do on upgrade, so the release notes and
  `canopy status` say so.
- **The worker drafts and posts no comment.** Under `approve`, a worker, public or private, pushes its changes as today
  (a push never waits: M54 is how the operator approves work before it is pushed) and comments nowhere. Its result line
  gains `drafts`: one per review thread it answers (a review comment on the thread, the reply's text, and whether it
  made the change, declined it, or answered a question), at most one top-level comment on the PR, and one ticket
  comment, its question when it is blocked and otherwise what it did, where a `tracker` source has a post command
  (DESIGN §29). A worker's own PR body and title are not drafts: they describe the change, not the operator's words. A
  decline it would have argued on the PR is a draft too, and the run still reports `blocked` with the disagreement. At
  most 30 a run, each bounded and refused with hidden characters, as memory's notes are (DESIGN §28). The prompts'
  "Reply on the PR to each comment you addressed", their ticket comments, and their comment marks move behind the
  setting; under `post` each prompt is the same bytes as today, held by a snapshot.
- **The marks change use, not meaning.** The rule that a comment carrying the marks is never authority stays, on both
  settings (D069). Under `approve` the marks go on what still posts without the operator: a question on a tracker with
  no post command (Jira today, until a Jira post command exists beside M36's Jira connector), and every comment under
  `post`. What the operator sent carries none.
- **The threads, read in code.** canopy reads review threads itself, not through the worker: after the worker ends,
  `_run` runs canopy's GitHub reader (below) for each PR the run pushed to, and records each review thread, its path,
  line, and side, whether it is outdated or resolved, and each comment's id, author login, time, and bounded body. A
  draft naming a thread a whole read did not return is refused, with a harness note on the run. A read that fails, times
  out, or ends without its `end` line refuses nothing: the run's drafts are kept unchecked, with a harness note,
  `drafts_waiting` says the threads could not be read, each tick reads the PR again until one read is whole, and no
  unchecked draft can be sent, so an outage delays the replies and never drops them. The page shows the thread as the
  reader saw it, never the worker's copy of it. The rows are M36's `observed_reviews`, which this milestone creates and
  M36 fills for every watched PR. PR review comments thus join the journal (DESIGN §22, Open), read only, authorizing
  nothing.
- **canopy's GitHub program.** A uv workspace member, `packages/canopy-github`, stdlib only and importing nothing from
  canopy, as the Slack sink is. It reads the token `gh` holds when it runs, so the harness never holds one (T2). Two
  commands: `canopy-connect-github`, the reader, which here answers one request, a PR's review threads, in M36's
  `review` line shape, and which M36 grows into the whole connector; and `canopy-post-github`, the first program canopy
  ships that writes to GitHub, which takes on stdin one PR's approved drafts and posts them verbatim as one comment
  review (a pending review, each reply added to its thread, a top-level comment as the review's body, submitted as a
  `COMMENT`), or a ticket's question as an issue comment, and prints each new comment's id and URL. It never approves,
  requests changes, or resolves a thread. The host is the PR's own, read from its URL by the program, never by the
  harness, with `gh`'s token for that host, so GitHub Enterprise works as github.com does. Configured as M36's
  connectors are (argv, no shell, a timeout, private), this milestone defining the `vcs` source's table and the post
  command beside it.
- **Sending is the operator's act.** Drafts are a journal fact per run, numbered as a review's findings are. From the
  PR's page or the CLI the operator edits a draft's text, drops it, or sends it. Sending carries the hash of the text
  as the operator last saw it, and is refused `stale` when the draft changed since, as M41's config write is; it
  re-reads the thread first and is refused `thread_changed` when a comment arrived after the draft was made, the page
  showing the new comment, and sending again after that posts. It is refused `inside_run` as `send` is, and posts a
  draft at most once. What reaches GitHub is that text, verbatim, with no comment marks: the operator approved it word
  for word, so it is their comment. The drafts the operator sends together go as one review, so a reviewer gets one
  notification, and each sent draft's journal record holds the comment's id, URL, and time, which run drafted it, and
  whether the operator edited it. A newer run's draft for the same thread supersedes an unsent one, shown struck, and
  the page warns when the one superseded carried the operator's edits. Nothing canopy sends resolves a thread: that
  stays the reviewer's.
- **Read back by id, not by mark.** A sent reply carries no mark, so canopy knows it by the comment id the post
  returned. The state block lists, per PR, the comments the operator sent through canopy; the overseer's and the
  `resume` worker's prompts say those are neither review feedback nor a go-ahead, and the `review` cursor passes them.
  M37 moves that check into code. Everything a worker posts itself keeps the marks (D069): its ticket comments, and
  its replies under `post`.
- **Waiting drafts.** A run with unsent drafts raises `drafts_waiting`, an operator item on the attention list, open
  until each draft is sent or dropped or the PR merges or closes. A question drafted for the ticket shows on the
  ticket's page, its sending answering nothing until an authorized replier does. It holds nothing else: the push already
  happened, and the cursor passed the comments the run was given.
- **In place on the PR.** The PR's page gains its threads on the diff: the diff at the run's pushed head, which `_run`
  keeps as `_review` keeps the reviewed commit's (§21, The diff), each thread at its line, an outdated one under its
  file as a finding outside the diff is, its comments as text by their authors, and under it the draft, editable as
  plain text, with Send and Drop. A thread no draft answers shows as it is. The attention item opens this view.
- **Code shared, built once.** The review UI is becoming the operator's main surface for PRs, so the build extracts
  what M32, M43, M44, and this milestone each need, rather than copying it:
  - The diff with cards on its lines. `ReviewDiffPanels`, `review-folds`, and `findingAnchor` (M32) take any item
    anchored at `path:line`, a finding, a thread, or M43's draft comment, with the page saying how each card draws; the
    fold budget keeps the context around every placed line. M32's page keeps its look, held by its Playwright shots.
  - Keeping and serving a diff. `_review`'s diff code moves from `reviews` down to `core`, since `runs` may not import
    a feature (§5), and the server reads both kinds through its one bounded reader.
  - Drafts. A draft, its versions, and sending one exactly as approved live in `core`, called by the CLI and the
    server alike, as `core/plans.py` and M52's memory verbs are. M44's approval by hash, which `_run` checks before it
    copies a plan, is the pattern. M43's review drafts are the same records with a review run as their source.
  - Threads. A PR's thread cards and a plan's comment threads (`plan-threads.ts`, M44) share the card: comments with
    their authors and times, then the operator's reply box. Their models stay apart: a plan's threads are the
    operator's own text, a PR's are other people's (T1).
  - The GitHub program. One workspace member for M36's connector, this milestone's thread reads and replies, and M43's
    review post, so there is one token read, one GraphQL client, and one fake.
  - The threads view and its ids. M54's feedback plans show their proposals on the same threads, by the same ids.
- **TRUST_MODEL**, in the PR that builds it, which the operator approves by merging: T1 (a draft is untrusted text,
  written from coworkers' comments, until the operator sends it, and rendered as text); T2 (a second program canopy
  ships makes outbound calls, with `gh`'s token, never the harness's); T5 (a sent reply speaks as the operator,
  unmarked, word for word as approved, and the journal says which run drafted it; the marks stay on what workers post
  themselves); T6 (under `approve` a worker's reply leaves the machine only as the operator sent it; the worker's
  definition denies the GitHub server's reply and review-comment tools by name, as defense in depth); T8 (the web
  channel gains editing, dropping, and sending drafts; its residual gains that a stolen session can post text of its
  choosing, as the operator, on a PR or ticket of the loop's own a run drafted for); §6 ("never submit a PR review of
  any kind" becomes never one that approves or requests changes: a comment review only, of text the operator sent word
  for word, the change M43 also needs). D003 already records the direction (C7); its building PR states it as built.
  AGENTS.md's "No GitHub client" line is scoped to the harness package, as M36 plans. D069 notes that a comment the
  operator sent through canopy is known by id.
- Tests with the fakes: a fake reader and post command that record what they are sent, as the `notified` sink does; a
  `resume` under `approve` posts nothing and records its drafts; a draft naming an unread thread refused; a failed read
  keeping the drafts unchecked and unsendable until a later read; a send posts the text verbatim and records the id; an
  edit after the page read refused `stale`; a thread with a new comment refused `thread_changed`; a second send posts
  nothing; `inside_run` refused; drafts sent together posted as one `COMMENT` review and never approving; a PR on an
  Enterprise host posted to that host; a newer draft superseding an older; the sent ids in the state block, a snapshot;
  `post`'s prompts unchanged, a snapshot; Vitest for the draft card, Playwright for sending from the PR's page.
- A blocked worker adds the `needs_human` label as today, whether or not its question waits as a draft: labels are
  not speech, and the operator left it to the simplest rule (2026-10-17).

Accept: written with the design, before work starts. Live, once built: on one of the loop's PRs with a coworker's
review comments, a `resume` under `approve` pushes its changes and posts nothing; the operator reads its drafts on their
threads on the PR's page, edits one, drops one, and sends the rest; GitHub shows exactly the sent text under the
operator's name with no mark; the next tick dispatches nothing for the sent replies.

Status: in progress. Designed 2026-10-18 (DESIGN §29). The design settles what the sketch left open: a thread draft
names a review comment by the id in its URL and canopy finds the thread; a ticket comment is a draft only where the
operator configured a `tracker` source with a `post_cmd`, since the harness never branches on `tracker.provider`; the
`vcs` source defaults to canopy's own programs, so `approve` needs nothing configured; `thread_changed` counts comments
since the run started, and a refusal moves that basis; and a post whose outcome is unknown is `unconfirmed` until a
read settles it, so a draft is posted at most once. Built: `packages/canopy-github`, the reader and the poster, tested
against a stand-in for GitHub's GraphQL API, and TRUST_MODEL T2's line for them; `trust.review_replies` (`post`
until sending is built, then `approve`) and `[connect.sources]`; and migration 0043's tables, `observed_prs`,
`observed_reviews`, `drafts`, `draft_versions`, and `run_replies`, with their row types. Workers draft under
`approve`: the prompts' posting sentences as placeholders (every prompt the same bytes under `post`, held by the
memory snapshots), `{{DRAFTS}}` required under `approve`, and `_run` writing a run's drafts under their bounds, each
refused alone, a PR's waiting `unchecked`. Threads read in code: `core/observe.py` runs the `vcs` source's reader and
records each PR it read whole into `observed_prs` and `observed_reviews`; `_run` reads its PRs once the run is closed
and each tick's reconcile reads every PR a draft waits on, checking each draft (`unknown_thread`, one a thread a run)
and superseding the unsent drafts of earlier runs; `drafts_waiting` for the operator alone; and fakes of both GitHub
programs in `tests/fakes/github`. Sending from the CLI: `runs/drafts_manage.py` and `canopy draft list`, `show`,
`edit`, `drop`, `send`, and `settle`, each refusing `inside_run`; a send checks every draft and reads each PR again
whole before anything posts, refusing `stale` and `thread_changed`, claims its drafts, posts one PR's as one review,
and records each comment's id; a post that ends unsure is `unconfirmed` until a read settles it by its pending
review's id, or the operator a ticket's; and `canopy status` names the setting and the drafts waiting. Read back by
id: the state block's `operator_sent` per unit, the overseer prompt's section on it, and the `resume` prompt naming
what was sent on its PRs; the worker definitions under `approve` deny the GitHub server's comment tools and `gh pr
comment` by name; TRUST_MODEL T1, T5, T6, and §6, D003, D069, and AGENTS.md's GitHub-client line; and `approve` is the
default. The web API: `_run` keeps each repository's diff at its pushed head under `approve`, with the commit, through
the diff code moved down to `core`; `GET /api/pull-request/threads` serves a PR's threads on that diff with every draft,
and edit, drop, and send take the CLI's functions; and TRUST_MODEL T8 for both. The PR's page: its threads on that
diff, each draft under its thread with Send, Edit, and Drop, a send of every waiting draft as one review, and a warning
when the PR's head is past the diff; `drafts_waiting` opens it; the diff with cards on its lines takes any card
(`DiffPanels`), M32's page keeping its look; and the mock journal's PR 88 carries a run's drafts, with canopy's GitHub
programs answered in process, so a draft sent from `--mock` posts nowhere. A ticket's own drafts on its page and in
its `drafts_waiting` item, each naming the issue it goes to. Staging, asked for by the operator (2026-10-19): `canopy
draft stage` opens a PR's drafts as one pending review the operator submits on GitHub, settled by the next whole read
(migration 0051). Left: the live acceptance above.
