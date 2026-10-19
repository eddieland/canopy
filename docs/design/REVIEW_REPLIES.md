# Review replies

Part of the canopy design, normative like all of it: the replies to coworkers' review comments that workers draft and
the operator sends. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Agent memory](MEMORY.md). Next: [Connectors](CONNECTORS.md).

## 29. Review replies the operator sends

ROADMAP M53, REQUIREMENTS R20. §8, §21, and §22 describe workers that post their own comments; this section says what
changes when they draft them instead.

A `resume` worker answers coworkers' review comments as the operator (D010), and the operator first reads what it said
when their coworkers do. Every reply starts with `CANOPY:`, which tells the reader a model wrote it and the loop to
read past it (D069), but it is still the operator's name on it. So under `trust.review_replies = "approve"`, the
default, a worker drafts every comment it would have posted, canopy reads the PR's review threads itself, and the
operator reads each draft on its thread, on the PR's diff, edits or drops it, and sends the ones they approve. canopy
posts exactly that text, unmarked: the operator approved it word for word, so it is their comment. The operator
settled this shape (2026-10-17), with canopy shipping its own GitHub program (REQUIREMENTS C7, D003).

### Configuration

`trust.review_replies` is private (§12), since a shared file must not decide what is said in the operator's name
(TRUST_MODEL T7). `post` is how workers worked before this section, every prompt the same bytes. A run keeps the setting
its prompt was rendered under (§8 step 3). The `vcs` source (§30) reads the threads and its `post_cmd` sends; unset, it
is canopy's own programs, so `approve` needs nothing configured. A ticket's drafts need a `tracker` source with a
`post_cmd`, which the operator names, since the harness never branches on `tracker.provider` (§17).

### The drafts

Under `approve`, an `implement` or `resume` worker, public or private, pushes as before and comments on no PR. A push
never waits on the drafts: ROADMAP M54 is how the operator approves work before it is pushed. Its result line gains
`drafts`, parsed apart from the result:

- `thread`: a reply to a review thread, naming a review comment on it, and whether the run made the change, declined
  it, or answered a question. A decline is a draft too, and the run still reports `blocked`.
- `pr`: at most one a PR, everything the prompt would have had it post there.
- `ticket`: at most one a run, only while a `tracker` source has a `post_cmd`, and never on a private ticket (§22).
  Without one, the worker posts its ticket comments itself, marked, as under `post`.
- A PR's title and body, and a split's tickets, are not drafts: they describe the change, not the operator's words.
- Each draft is refused alone, never cut or cleaned: past a count or a length, with a character §28's bounds refuse or a
  secret's shape, on a PR not of the run's units (`not_ours`), or on a ticket the run may not post to (`no_post`). The
  operator's edits are held to the same bounds, since a sent reply is public. Under `post`, drafts are stored nowhere.
- Under `approve`, a prompt override without `{{DRAFTS}}` is `bad_prompt` (§8 step 3): an older override would have its
  worker post in the operator's name.

The marks (D069) change use, not meaning: a comment carrying them is never authority. Under `approve` they go on what
still posts without the operator; what the operator sends carries none. A blocked worker adds `needs_human_label` as
before: labels are not speech.

### The threads, read in code

canopy reads review threads itself, never through the worker, so the page shows a thread as GitHub holds it and a draft
can answer only a thread that exists. After a run under `approve` closes with drafts (§8 step 7), canopy reads each PR
of its units through the `vcs` source, recording observations (§30), its slots already returned.

- A draft is unchecked until a whole read of its PR. A `thread` draft whose comment that read did not return is refused
  (`unknown_thread`), and so is a run's second draft for the same thread.
- A read that is not whole refuses nothing: the drafts stay unchecked and each tick's reconcile (§6 step 3) reads
  again. No unchecked draft can be sent, so an outage delays the replies and never drops them.
- Once checked, a draft supersedes an unsent draft of an earlier run for the same thread, PR comment, or ticket, never
  sendable again, with a warning when it carried the operator's edits.

### Sending

Sending is the operator's act, from the PR's page or `canopy draft`, through one function for both. Every verb refuses
as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set: an agent that could send a draft could post as the
operator. Each send names the hash of the text the operator last saw. Every check runs before anything posts, and any
refusal posts nothing:

- `unchecked`, `superseded`, `dropped`, `refused`, or `unconfirmed`, as above and below.
- `stale`: the text is no longer that hash, checked again as the send claims the draft; a claimed draft takes no edit.
- `thread_changed`: a whole read made now shows a comment on the thread newer than the draft's basis, other than one the
  operator sent through canopy. The refusal names the new comments and moves the basis, so sending again posts.

What reaches GitHub is the text, verbatim, with no marks. The drafts sent together for one PR are one comment review,
so a reviewer gets one notification; a `ticket` draft is one comment. Nothing canopy sends resolves a thread, approves,
or requests changes: that stays the reviewer's.

A draft is posted at most once: the send claims its drafts in one transaction. A post that fails before it submits
posts nothing. One that ends without saying whether it submitted leaves its drafts `unconfirmed`, never sent again
until a whole read settles it by the review's id, or, for a `ticket` draft, until the operator does. Each sent draft
records its comment, the run that drafted it, and whether the operator edited it. Stopping a ticket leaves its drafts
sendable; `canopy forget` drops its unsent ones; §26 deletes no draft, since a sent one is how canopy knows its comment.

### Read back by id

A sent reply carries no mark and is by the operator's login, so the loop would read it as new review feedback, or as an
authorized reply; canopy knows it instead by the id the post returned. The state block lists, per PR, the comments the
operator sent through canopy as neither review feedback nor a go-ahead, and the `review` cursor (§7) passes them.

### Waiting drafts

The harness raises `drafts_waiting` (§14), the operator's alone, for each unit or ticket with a draft to send, until
each is sent, dropped, or superseded, or the PR closes. It says when the threads could not be read, and holds nothing.

### On the PR's diff

The PR's page shows its threads on the diff (§22), each at its line or under its file (§21), and under it the draft,
edited as plain text, with Send and Drop. The diff is the run's own, taken at its verified head (§8 step 5), and the
page says when the PR's head has moved on. A draft is a worker's text, written from coworkers' comments, and a thread is
coworkers' text: both are rendered as text, never Markdown, every hidden character named (§28).

### canopy's GitHub program

`packages/canopy-github`, a uv workspace member, stdlib only and importing nothing from canopy, as the Slack sink is
(§5, §20); lint bans importing it from the harness. `canopy-connect-github` reads a PR's reviews and threads (§30).
`canopy-post-github`, the first program canopy ships that writes to GitHub, posts one PR's drafts as one review, or one
ticket's comment, and reports whether it submitted. It refuses a ticket URL that is not an issue numbered as its key,
never approves, requests changes, or resolves a thread, and deletes no review but the pending one it is handed.

The host is read from the PR's URL by the program, never by the harness, with the token `gh` holds for it, so GitHub
Enterprise works as github.com does and the harness never holds a token (TRUST_MODEL T2). A URL is a worker's word, so
the program reads a token only for a host `gh` is logged in to, and follows no redirect, which would carry the token
elsewhere. Rejected: posting through an agent (the text it posts is the model's last word, not the operator's); the
harness calling GitHub (D003).

### Trust model changes

T1: a draft is untrusted text until the operator sends it, and PR review threads join the journal (§22), read only and
authorizing nothing. T2: a second program canopy ships calls out, with `gh`'s token. T5: a sent reply speaks as the
operator, word for word as approved, and the journal says which run drafted it. T6: under `approve`, a worker's comment
leaves the machine only as the operator sent it, and worker definitions deny the GitHub server's comment tools and
`gh pr comment` and `gh issue comment`, as defense in depth. T8: a stolen web session can post as the operator on a PR
or ticket a run drafted for. §6's "never submit a PR review" becomes never one that approves or requests changes.

### Open

- Whether a run's account of what it did, drafted for the ticket, is worth the operator's send; whether a draft on a
  PR that merged or closed should still be sendable, as it is; editing or deleting a sent reply from canopy.
