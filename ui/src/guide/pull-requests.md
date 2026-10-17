# Pull requests and reviews

Every PR canopy knows about, and canopy's own reviews of them. The reviews are yours alone: canopy never posts one on
a PR, so this is the only place, besides `canopy review show`, you'll read them.

## The pull requests page

[Pull requests](/pull-requests) lists the loop's own PRs, every PR canopy reviewed, and every PR you asked it to
review, most recent activity first. Each row shows where the PR stands (a run working it, or its latest review's
verdict), the PR as `org/repo#123`, its phase, its ticket and title, and how long since anything happened. The name
opens canopy's page for the PR; the small icon beside it opens the PR itself.

The title is the PR's own, as the worker that opened it or canopy's last review of it read it, so it says what the PR
changes rather than what the ticket asked for. Until one is reported, a loop PR shows its ticket's title. Titles are
read when canopy looks at the PR, not live: rename one on GitHub and canopy catches up at its next run or review.

A PR's page gathers what canopy knows of it: its ticket, repository, and branch, what it has cost, canopy's reviews of
it, the runs that pushed to it, and the decisions that named it. When a PR has used every review it's allowed, its page
shows **At its limit**, with **Allow one more**, as `canopy grant URL review`. The limit is
`policy.max_reviews_per_pr`, three by default.

## When canopy reviews

A review is a fresh agent's adversarial read of one PR at one commit: it's told to assume the change is wrong and go
looking. canopy reviews:

- **The loop's own PRs**, with `review.agent_prs` set: once checks pass, before a human is asked. Each new commit is
  reviewed again, up to the limit. What happens to the findings depends on whether you trust the reviewer, below.
- **PRs matching your query**, `review.query`, such as your team's: reviewed and nothing more. The loop never
  pushes to them, fixes them, or opens a ticket for them.
- **A PR you ask about**, below.

Reviews are off while `capacity.max_reviews` is 0, and each commit is reviewed once.

canopy treats its own reviewer as it treats anyone else's. With `canopy:review` in `trust.trusted_reviewers`, findings
on a loop PR send a worker back to address them, and the PR's phase is `review findings`. Without it, the findings wait
as `untrusted review` on your attention list until you say which to act on. Untrusted is the default, and a sound
one: the reviewer is wrong often enough that you'll want to read a few before it spends runs on its own say-so.

## Asking for a review

To have canopy review a PR the loop doesn't own, such as a coworker's, paste its URL into **Review a PR** on the pull
requests page and press **Review**. This is `canopy start URL --review`. The next tick reviews the PR once, at its
latest commit, in whichever of your repositories holds it, and the request ends with that review. The PR's page shows
the open request, with **Stop** to withdraw it.

The review stays in canopy, like every other. Whether you pass any of it on to your coworker, and in what tone, is
between you and them.

## The reviews page

[Reviews](/reviews) lists every review, newest first: its verdict, its ticket, how big the change is (`low impact`,
`normal impact`, `high impact`), the PR and commit, and what it cost. A verdict reads `clean`, or counts the findings
with the worst among them, such as `3 findings, 1 major`. A finding is `blocking`, `major`, or `minor`.

## A review's page

At the top, the review's verdict and summary, the commit it read, and the PR's other reviews, if any. Then its
findings, each linking to where it sits, and the diff, a panel per file, with each finding pinned under the line it
names. A finding about a file the diff doesn't touch has a panel of its own. A long diff shows the lines around each
finding at first, with folds that open the rest.

A PR stacked on another branch shows that branch's commits too, since the diff runs from where the PR's branch left
the pool's base branch. If a finding seems to be about code the PR never touched, check that first.

## Acting on findings

A review changes nothing on its own: canopy never approves a PR, requests changes on it, or merges it. What you can do
is tell canopy which findings matter.

- **dismiss**, on a finding's card, as `canopy dismiss review:ID N`: no worker or tick acts on it. It stays listed, and
  **undo** brings it back. If you dismiss every finding, the PR moves on as if the review were clean.
- **send to a worker**, on a finished review of one of the loop's own PRs: tick the findings worth fixing and press
  it, as `canopy send review:ID N`. canopy records a reply on the ticket naming them, and the next tick reads it as
  your go-ahead for a worker to fix those and leave the rest alone. For an untrusted reviewer it's the go-ahead the
  findings wait for; for a trusted one, it narrows what the worker takes on.

A review of a PR the loop doesn't own has neither: the page is all it gives you. Dismissals and sends belong to one
review, so a new commit's review starts fresh.
