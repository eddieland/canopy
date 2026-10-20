# Review replies

Part of the canopy design, normative like all of it: the replies to coworkers' review comments that workers draft and
the operator sends. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Agent memory](MEMORY.md). Next: [Connectors](CONNECTORS.md).

## 29. Review replies the operator sends

A `resume` worker answers coworkers' review comments as the operator (D010), and the operator first reads what it said
when their coworkers do. Every reply starts with `CANOPY:`, which tells the reader a model wrote it and the loop to
read past it (D069), but it is still the operator's name on it. So under `trust.review_replies = "approve"`, the
default, a worker drafts every comment it would have posted, canopy reads the PR's review threads itself, and the
operator reads each draft on its thread, edits or drops it, and sends the ones they approve. canopy posts exactly that
text, unmarked: the operator approved it word for word, so it is their comment. canopy ships its own GitHub program to
post it (REQUIREMENTS R20, C7, D003).

### Configuration

`trust.review_replies` is private (§12), since a shared file must not decide what is said in the operator's name
(TRUST_MODEL T7). `post` keeps workers posting their own comments, marked. A run keeps the setting its prompt was
rendered under (§8 step 3). The `vcs` source (§30) reads the threads and sends; unset, it is canopy's own programs, so
`approve` needs nothing configured. A ticket's drafts need a `tracker` source that can post, which the operator names,
since the harness never branches on `tracker.provider` (§17).

### The drafts

Under `approve`, an `implement` or `resume` worker, public or private, pushes as before and comments on no PR; a push
never waits on the drafts. Its result line carries the drafts, parsed apart from the result:

- a reply to a review thread, saying whether the run made the change, declined it, or answered a question. A decline is
  a draft too, and the run still reports `blocked`;
- at most one comment a PR, and at most one a run on its ticket, only where a `tracker` source can post and never on a
  private ticket (§22). Without one, the worker posts its ticket comments itself, marked;
- a PR's title and body are not drafts: they describe the change, not the operator's words.

Each draft is refused alone, never cut or cleaned: past a count or a length, with text §28's bounds refuse or a
secret's shape, or aimed at a PR or ticket the run may not speak on. The operator's edits are held to the same bounds,
since a sent reply is public. A prompt override that does not tell the worker to draft is refused under `approve`
(§8 step 3), since an older override would have its worker post in the operator's name.

The marks (D069) change use, not meaning: a comment carrying them is never authority. Under `approve` they go on what
still posts without the operator; what the operator sends carries none. A blocked worker still adds the needs-human
label: labels are not speech.

### The threads, read in code

canopy reads review threads itself, never through the worker, so the operator sees a thread as GitHub holds it and a
draft can answer only a thread that exists. After a run under `approve` closes with drafts (§8 step 7), canopy reads
each of its PRs through the `vcs` source (§30). A draft stays unchecked, and cannot be sent, until a whole read of its
PR; a read that is not whole refuses nothing, and each tick's reconcile (§6 step 3) reads again, so an outage delays
the replies and never drops them. A draft answering a thread that read did not return is refused, as is a run's second
draft for one thread. A checked draft supersedes an unsent draft of an earlier run for the same thread, PR comment, or
ticket, with a warning when that one carried the operator's edits.

### Sending

Sending is the operator's act, from the web UI or `canopy draft`, through one function for both. Every verb on a draft
is refused as `inside_run` inside a tick or a run: an agent that could send a draft could post as the operator. A send
names the text the operator last saw, and every check runs before anything posts. It refuses a draft that is
unchecked, superseded, dropped, refused, or of unknown outcome; one whose text changed since the operator saw it; and
one whose thread has a comment newer than the draft, other than the operator's own through canopy. That refusal names
the new comments, so the operator reads them before sending again.

What reaches GitHub is the text, verbatim, with no marks. The drafts sent together for one PR are one comment review, so
a reviewer gets one notification. Nothing canopy sends resolves a thread, approves, or requests changes: that stays the
reviewer's, and is what §6's "never submit a PR review" means. A draft is posted at most once. A post that ends without
saying whether it submitted is never sent again until a whole read, or the operator, settles it. Each sent draft records
its comment, the run that drafted it, and whether the operator edited it. Garbage collection (§26) deletes no draft,
since a sent one is how canopy knows its comment.

A sent reply carries no mark and is by the operator's login, so the loop would read it as new review feedback, or as an
authorized reply; canopy knows it instead by the id the post returned. The state block lists, per PR, the comments the
operator sent through canopy as neither review feedback nor a go-ahead, and the `review` cursor (§7) passes them.

The harness raises `drafts_waiting` (§14), the operator's alone, for each unit or ticket with a draft to send, until
each is sent, dropped, or superseded, or the PR closes. It says when the threads could not be read, and holds nothing.

### Reactions

A thread's draft may stage a reaction, one of the eight GitHub offers, on the review comment it names, beside its reply
or alone: a `+1` on a fixed nit says what "Done." would. It is part of the draft's words: the operator sets, changes, or
clears it as they edit, and a send names it with the text. A send adds its reactions first, and opens no review for
reactions alone. GitHub keeps one reaction of a kind a person, so one a failed send added stays, the draft says so, and
sending again adds no second. Nothing canopy reads gives a reaction meaning, so a sent one is neither feedback nor a
go-ahead.

### On the PR's diff

The operator reads each draft under its thread, on the diff the run pushed (§8 step 5), told when the PR has moved on.
A draft and a thread are untrusted text and are shown as text, never Markdown, every hidden character named (§28); a
comment's `<details>` block folds under its summary, as GitHub shows it, and says while closed when it hides a character.

### canopy's GitHub program

`packages/canopy-github` is a program of its own, which the harness may not import (§5). Its reader reads a PR's reviews
and threads (§30); its poster posts one PR's drafts as one review, or one ticket's comment, and reports whether it
submitted.

The program, never the harness, reads the host from the PR's URL and uses the token `gh` holds for it, so GitHub
Enterprise works as github.com does and the harness never holds a token (TRUST_MODEL T2). A URL is a worker's word, so
it reads a token only for a host `gh` is logged in to, and follows no redirect. Rejected: posting through an agent (the
text it posts is the model's last word, not the operator's); the harness calling GitHub (D003).

### Open

- Whether a draft on a PR that merged or closed should still be sendable, as it is.
- Editing or deleting a sent reply from canopy.
- The operator staging a reaction of their own on a thread no draft answers: every draft today is a run's.
