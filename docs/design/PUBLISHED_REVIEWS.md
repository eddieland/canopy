# Published reviews

Part of the canopy design, normative like all of it: a review of a PR the loop does not own, revised in canopy and
published on the PR as the operator's own comment review. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [A clock for running agents](CLOCK.md). Next: [The overseer reads the
journal](READING_THE_JOURNAL.md).

## 34. Publishing a review

Built in part (ROADMAP M43): the draft, its versions, publishing and staging from the CLI and the review's page, and
revising with an agent on a note from the CLI. Asking for a revision from the review's page is designed, not built. Each
part changes D114 and TRUST_MODEL as it is built (Trust model changes).

§21's reviews post nothing (D114), and §29's drafts answer threads on the loop's own PRs. This section says what
changes for a review of someone else's PR, a `review.query` match or a review request (§21), where sending findings to
a worker does not apply: the operator reads the review as a **draft** of a review on the PR, edits it or has an agent
revise it, and publishes one version, which canopy posts word for word as a comment review in the operator's name.

### The draft

A `done` review of a PR the loop does not own is its draft's first version; a review that names a ticket, or of a PR a
ticket's unit holds, has no draft, checked in code, and keeps §21's send. The draft is §29's, with the review as its
source rather than a run, kept with the review rather than a ticket: versioned, each version recording who wrote it, the
reviewer, the reviser, or the operator, and through which channel. A review the operator asked for waits on them, as
a worker's drafts do: the harness raises `review_waiting` about its PR until a draft of the PR's newest reviewed commit
is published or staged, the operator empties it of all it would post, or the PR is seen merged or closed. A draft
staged or of unknown outcome raises `review_unsettled` until a read settles it. A `review.query` match's draft waits on
nobody, and none need ever be published.

A version is exactly what would post: a body, and comments, each on a line of the diff the review kept (§21, The diff),
on the commit's side. canopy makes the first from the review's body, what the reviewer would tell the PR's author and
often empty, and its findings, a comment for each finding at its `path:line`; a finding, or a reviser's comment, whose
location is on no such line goes into the body under its location as the version is made. So what the operator reads
is what posts, and canopy composes nothing when it publishes. The review's summary briefs the operator and stays out:
the PR's author needs no account of their own change. Each text is held to §29's bounds for a draft and refused alone,
with a note on the review, never cut or cleaned; the operator's edits are held to the same. A version carries at most
as many comments as one run's drafts, 30, which is what one review canopy posts already holds and more than a review
reports findings; a comment past it is refused.

The operator edits the body or a comment, drops a comment, or adds one on a line of the diff, each a new version.
Dismissing a finding (§21) drops its comment, one control rather than two, and taking the dismissal back restores it.
The draft shows on the review's page, each comment at its line on the diff (§29, On the PR's diff), as text, every
hidden character named (§28). Until the operator publishes a version its text is untrusted, since the reviewer and the
reviser wrote it from the PR's (TRUST_MODEL T1).

### Revising with an agent

A note on the draft, the operator's reply on the review, asks for a revision. While a note is newer than the draft's
newest version, the overseer starts a revision or records why it waits, as it plans again on a reply (§25); only a tick
starts one (D020). The state block gives each such draft and its revisions spent, never its text. A revision is a
review run at the same commit, under §21's guards but two, the `done` review of its commit and the per-PR limit: the
daily limit, review capacity, and `max_workers` hold it, and a draft's revisions are limited, by
`policy.max_revisions_per_draft`, which a repository may only lower, never reset (D030), and raised only by the
operator's grant. A note is refused at that limit and while a revision runs, and a revision whose draft moved on while
it ran makes no version: what the operator did meanwhile stands.

It runs as the reviewer does, with `canopy-reviewer`, outside the checkout, and posts and writes nothing. Its prompt
carries the review, the newest version, and the operator's notes since it, which are instructions; the PR and the
draft are data. Its result line is a new version, validated (D026); anything else is `unknown` and leaves the newest
version standing. A revision that does not end `done` raises `review_failed`, as a review does.

### Publishing

Publishing is the operator's act on one version, from the review's page or the CLI, through one function for both, as
§29's send is. It is refused `inside_run`: an agent that could publish could post as the operator on any PR the
operator's query matches. It names the version the operator last saw by its hash, and every check runs before anything
posts. It refuses a version that is not the newest; a draft with a revision running; a PR holding a review canopy
staged (§29); and a draft with a version published, staged, or of unknown outcome. A draft publishes one version, at
most once, and a later commit's review is a new draft: a PR gets at most one published review for each commit canopy
reviewed, so no more than `policy.max_reviews_per_pr` (§21) and the operator's grants allow.

What reaches GitHub is that version verbatim, with no marks, as one comment review on the commit the review read: the
body as the review's, each comment as an inline comment on its line, outdated on a PR that has moved on, which the page
says before the operator publishes. canopy never approves, requests changes, or resolves a thread (TRUST_MODEL §6). The
post goes through §29's poster, `canopy-post-github`, never an agent or the harness (D003), which gains a review on a
named commit whose comments start threads rather than answer them. It opens a pending review, adds every comment, and
only then submits, so a comment GitHub refuses, such as one on a line GitHub's diff of the PR lacks, posts nothing, and
the page says which. The journal records the version, the channel, when, and the review's and each comment's id.

A post that ends without saying whether it submitted is of unknown outcome, and nothing is posted for the draft until a
whole read of the PR through the `vcs` source (§30) settles it, as §29's sends are. In place of publishing, after the
same checks, the operator may stage the version: canopy opens a pending review holding it and never submits it; the
operator does, on GitHub, or deletes it. A whole read settles a staged draft as §29's: published once its review is
submitted, publishable again if it is gone. Staging is the default, so submitting stays the operator's click on GitHub
unless they ask canopy to submit; the CLI's `--submit` does. A draft is publishable while the diff its review kept is,
so not after garbage collection deletes it (§26). A published review is not followed onto the next commit, and the
loop's own PRs publish none.

### Trust model changes

In the PR that builds each part, which the operator approves by merging: D114, §6, T1, T5, and T6 with the draft and
publishing, T3 with revisions, and T8 with the review page.

- D114: from "posts nothing" to "posts nothing the operator has not published, word for word"; its revisit is met.
- §6: the review canopy submits or stages may also be one the operator published or staged word for word, on a PR the
  loop does not own. Never pushing to or editing a PR the loop only reviews stands: a comment review edits nothing.
- T1: a draft is untrusted until published; the reviser reads the PR as the reviewer does, the operator's notes its
  only instructions; every verb on a draft is refused inside a run. T3: revisions are review runs, limited per draft.
- T5: a published review speaks as the operator, unmarked, word for word as they last saw it, on someone else's PR;
  the journal records which review and revisions wrote each version and what the operator changed. With no bot
  identity (D010), nothing on GitHub says a model wrote it but what the operator leaves in.
- T6: the reviewer and the reviser still hold no write tool. Residual: a steered reviewer can put a link carrying data
  in a comment the operator publishes unread.
- T8: the web channel gains editing a review's draft, asking for a revision, publishing, and staging. Its residual
  widens to every PR canopy reviewed: a stolen session can post text of its choosing, as the operator, on a coworker's
  PR.

### Open

- Following a published review onto the next commit, its comments or a coworker's answers on its threads carried into
  the next draft. It needs a finding's identity across commits first (§21, Open).
- The loop's own PRs publishing a review, for a coworker's benefit, beside §21's send.
