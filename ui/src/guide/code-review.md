# Code review

How to review code at the pace agents write it, and where canopy fits: the principles it's built on, and the setting
or page each one lives in. The mechanics are on [Pull requests and reviews](pull-requests); this page is the why.

## The job has changed

Review used to be a gate at the end of the road: write the code, open a PR, wait for a colleague. When agents write
most of the code, that gate either becomes the bottleneck or quietly becomes a rubber stamp, and neither is review.

So stop asking whether a person read every line, and ask what could go wrong with this change, and which check,
automated or human, is the right one to catch it. Machines are good at reading every line. You are good at
deciding whether the change should exist, whether it fits the system, and what it costs if it's wrong. canopy is built
to spend your attention on the second list and let agents do the first.

Two costs come with any review: the time spent reading, and the time spent fixing what got through. Cutting the first
only helps if the second doesn't grow to match. If reverts climb, you didn't save time, you moved it to the on-call.

## Layers, not one gate

No single check catches everything, so a change passes through several, each catching some of what the others miss:

1. **The worker checks its own work.** Before each push it runs what your contributors run before opening a PR, as your
   `AGENTS.md`, contributing guide, Makefile, or CI name them: formatting, lint, types, and tests. A worker that says
   it's done without running anything is a worker telling you a story.
2. **CI** runs on the PR. A red check sends a worker back with the failures ([How the loop works](how-the-loop-works)).
3. **canopy's review** reads the change once checks pass, before a person is asked, with `review.agent_prs` set
   ([When canopy reviews](pull-requests#when-canopy-reviews)).
4. **You**, or whoever your team asks, approve and merge. canopy never does
   ([Philosophy](philosophy#humans-approve-and-merge)).

What happens after the merge is yours: branch protection, a merge queue, feature flags, staged releases, and a revert
that takes minutes. canopy doesn't replace any of them, and the cheapest of them is the revert you've practiced.

## Machines read first, you decide

With `review.agent_prs` set, by the time a loop PR is `needs reviewer` on [Attention](attention), its checks are
green and canopy's reviewer has read it. The routine mistakes are found and, if you let them be, fixed. What's left for
you is the part only a person can do:

- **Whether to build it at all.** Direction, taste, and scope. Agents make starting things cheap, so some work
  shouldn't land. The best time to say so is before there's code: with `policy.plan` set to `approve`, a ticket waits on
  your approval of its [plan](plans) before a worker writes a line.
- **Risky code**, such as auth, billing, migrations, and CI workflows, where the review's `high impact` points you.
- **Architecture** that sets a pattern others will copy.
- **The evidence.** The worker's summary, its run's transcript, and the reviewer's findings. If you can't say what
  the checks would have missed, that's the PR to read properly rather than approve quickly.

Whether canopy's own findings may send a worker back on their own is your call, and the default is no: until you put
`canopy:review` in `trust.trusted_reviewers`, findings wait as `untrusted review` until you pick which matter. Read a
few dozen before you change that. Trust is cheap to give and expensive to discover you shouldn't have.

## A fresh pair of eyes

The agent that wrote a change is the worst one to review it: it remembers what it meant, so it reads what it meant. So
canopy's reviewer is a fresh run with no transcript of the author's, told to assume the change is wrong until the code
shows otherwise. It runs outside the PR's checkout, so nothing in the PR configures it, and it can't change anything:
it reads the code, the diff, the history, and the PR's conversation, and reports to canopy.

Give it another model than your workers', with `runtime.models.reviewer`. Two models miss different things, which is
the point of asking a second one. Give it a voice, too: a [persona](tickets#choosing-a-persona) such as `skeptic`
presses harder on failure paths, and a request in several personas reviews the PR once in each, side by side.

## Prove it or drop it

A reviewer that flags everything is easy to build and useless to own. canopy's is told to try to prove each finding
wrong before it reports it: to look for the guard, the caller, or the test that makes it harmless, and keep only what
survives. Each finding has to rest on an input or sequence of events that shows it, and the line that mishandles it,
read in the code, never guessed from a function's name or a comment.

It looks for correctness: wrong behavior, missed cases, security holes, broken contracts, and new behavior no test
would catch breaking. Not style, and not what your lint, formatter, type checker, or a failed check already reports.
Your CI already has opinions about whitespace; it doesn't need a second one.

## Severity, and whose bug it is

Each finding is `blocking` (must not merge), `major` (fix it before merging), or `minor` (real, small, not a reason to
hold the merge). By default a review reports at most five minor findings, the ones that matter most, because the
sixth nit is where people stop reading. A persona may draw those lines differently, and say how many minor ones are
worth your time.

A bug the code had before the PR isn't the PR's finding. The reviewer names it in the summary instead, so it doesn't
look like the author's fault and a worker is never sent to fix code its PR didn't touch. If it matters, make it a
ticket of its own.

## Your rules, as they stood

The reviewer reads your repository's own docs, such as `AGENTS.md`, `CONTRIBUTING.md`, and `REVIEW.md`, and holds the
change to them: breaking a rule they state is a finding. It holds the change to the rules as they stood before it, so
a PR that edits `AGENTS.md` is judged by the version it replaces, and an edit that loosens a rule the rest of the change
then leans on is a finding too. No PR gets to grade itself on a curve it drew.

That makes those files the place to tune review. When the reviewer keeps flagging the same thing, fix it at the
source: a lint rule if a machine can check it, a line in `AGENTS.md` or `REVIEW.md` if not. The good ones are short.
They say what failure looks like in that repository, list what not to report, and ask for a file and line as evidence
rather than a guess.

Reviews read no [memory](memory), on purpose: a reviewer that shares the workers' beliefs shares their blind spots.

## Every finding gets an answer

A finding nobody answers is noise that trains you to skip findings. So answer each one, on the review's page
([Acting on findings](pull-requests#acting-on-findings)):

- **send to a worker**, for the ones worth fixing: your go-ahead for a `resume` to fix those and leave the rest.
- **dismiss**, for the rest, with why: **wrong**, it doesn't hold; **intentional**, it holds and the change means it;
  **not worth it**, it holds and isn't worth the fix.

A review whose findings are all dismissed moves on as a clean one. On a coworker's PR there's no worker to send to, so
leaving a finding out of your draft dismisses it ([Publishing your review](pull-requests#publishing-your-review)).

## Measure the noise

It's easy to catch more bugs if you don't mind flagging a lot of non-bugs, so watch what you do with the findings.
`canopy review noise` counts the last 90 days' findings by severity, persona, and model, and why you dismissed each.

- A high `wrong` rate is a reviewer worth retuning: another model, another persona, or a sharper `REVIEW.md`.
- A high `not worth it` rate is a reviewer that's right about things you've chosen to live with. Ask for fewer minor
  findings, in a persona or your docs.
- Few dismissals at all, on a reviewer you don't trust yet, is the evidence for trusting it.

## Review has to converge

An agent author and an agent reviewer can keep each other busy all night: each fix is a new commit, each commit a new
review, and each review a few more findings in code that was there all along. canopy keeps that bounded.

- **A limit per PR.** `policy.max_reviews_per_pr`, three by default, counts every review of a PR however it ended.
  At the limit the PR moves on to a person, and its page offers **Allow one more**
  ([The pull requests page](pull-requests#the-pull-requests-page)) for the time you mean it.
- **Memory of the last round.** A review of a new commit reads canopy's last finished review of the PR and checks each
  finding you didn't dismiss: one the worker fixed stops coming back. It still reads the whole change, since being told
  where not to look is how a bug survives three reviews.
- **A cool reviewer.** If your reviewer's model takes a temperature, set `runtime.review_temperature` low. A reviewer
  sampling hot finds something new every round in code nobody touched, and with it trusted, every one of those sends a
  worker back.

If a PR keeps going round, the fix is rarely another round. It's you reading it and deciding whether the approach is
wrong.

## Risk sets the effort

A docs fix and a change to the auto-updater don't deserve the same review. Each review rates its change's impact,
`low`, `normal`, or `high`, and shows it on the reviews list and the review's page, so you know where to look first.
The reviewer may call a change `low` only under your rule for it, `review.low_impact`, written in plain language; with
none, nothing is low.

Spend review where a missed bug is expensive. For a PR that worries you, ask for a review in two or three personas
([Asking for a review](pull-requests#asking-for-a-review)), and give the reviewer a stronger model than the one that
wrote the code. For routine work, one review in the default persona is plenty.

## Approvals

canopy reads approval from GitHub, as your team gives it. A person's latest verdict counts: an approval makes the PR
`ready to merge` until it merges, and a later request for changes takes it back. A bot's approval never counts, and
canopy never approves anything, so every approval it sees is a person's. If your branch protection dismisses approvals
on a new push, canopy sees the
dismissal and the PR waits for its reviewer again; if it doesn't, an approval stands until the merge. That's your
team's rule to set in GitHub, and canopy follows it rather than inventing a stricter one.

## Your coworkers' PRs

canopy can review a PR the loop doesn't own: one `review.query` matches, or one you paste into **Review a PR**. It
never pushes to one, fixes it, or opens a ticket for it. What it gives you is a draft of your review, which you edit,
have an agent revise, and publish word for word as your own comment review, or discard. It never approves or requests
changes in your name. A model's first draft about a colleague's code deserves the same read you'd give anything
you're about to sign.

## When a review misses something

Something will get through. When it does, ask what the reviewer didn't have in front of it, and put the answer where
the next review will read it: a rule in `AGENTS.md` or `REVIEW.md`, a test, or a lint rule. A [chore](chores) can
read your existing code through GitHub on a schedule, too, and report the old bugs no PR's review was ever going to
look at.
