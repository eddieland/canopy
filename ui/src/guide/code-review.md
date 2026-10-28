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
  **not worth it**, it holds and isn't worth the fix; **out of scope**, it holds and is worth fixing, in another PR.

A review whose findings are all dismissed moves on as a clean one. On a coworker's PR there's no worker to send to, so
leaving a finding out of your draft dismisses it ([Publishing your review](pull-requests#publishing-your-review)).

## Measure the noise

It's easy to catch more bugs if you don't mind flagging a lot of non-bugs, so watch what you do with the findings.
`canopy review noise` counts the last 90 days' findings by severity, persona, and model, and why you dismissed each.
The ones you didn't dismiss count by what the worker last said of them, `fixed` or `declined`, beside how many came
back as rebuttals. Your dismissal outranks the worker's answer: a finding the worker called fixed and you called wrong
counts as wrong.

- A high `wrong` rate is a reviewer worth retuning: another model, another persona, or a sharper `REVIEW.md`.
- A high `not worth it` rate is a reviewer that's right about things you've chosen to live with. Ask for fewer minor
  findings, in a persona or your docs.
- `out of scope` isn't noise at all: the reviewer was right, just early. Those findings are work you owe another PR, so
  write them down somewhere canopy isn't the only one remembering.
- Few dismissals at all, on a reviewer you don't trust yet, is the evidence for trusting it.
- A pile of rebuttals is an author and a reviewer that disagree on purpose. Read a few: one of them is usually right.

Noise is half the story; the other half is what the reviewer misses, and you can only count that on bugs you already
know about. Keep a few as `[[review.eval_cases]]` in the workspace's private config: PRs that were reverted or fixed
forward, each with the line its bug was on, and a few you know are clean. `canopy review eval` reviews every case at
its commit and reports how many of the bugs it found and how many alarms it raised on the clean ones; `--persona` and
`--model` try something else on the same cases. Run it when you change the reviewer's prompt, persona, or model, before
you decide the change helped. It's a measurement, not a gate: nothing it finds reaches the loop, and each result lands
in `.canopy/review-evals/` with what it ran on, so the next run has a number to beat. [Adding eval
cases](#adding-eval-cases) says how to pick them.

## Adding eval cases

An eval case is a real PR at a real commit, not one made up for the test. That's the point: a bug planted to be found
is the kind a reviewer finds, and the ones worth measuring are the ones that got past people. Your history already
holds them, in every revert and every "fix:" that names a PR.

A case is a table in `.canopy/config.toml`, the workspace's private config. Nowhere else will take one, since a case
asks for a review of a PR as `review.query` does:

```toml
[[review.eval_cases]]
name = "retry-forever"
pr = "https://github.com/acme/api/pull/412"
repo = "api"
sha = "3f9c2e..."     # the PR's head as it merged, the full hash
base = "a71d04..."    # where it left main
kind = "bug"
lines = ["src/retry.py:42", "src/retry.py:57-61"]
```

- **`name`** names the case's files and `canopy review eval --case NAME`: lowercase letters, digits, and dashes.
- **`pr`** is the PR's plain `https://` URL, and **`repo`** the repository's name in the workspace file.
- **`sha`** is the commit the reviewer reads, the PR's head as it merged, or as it stood when the bug was in it.
  canopy fetches it from origin, so it has to be a commit origin still has; GitHub keeps a PR's commits after its
  branch is deleted.
- **`base`** is where the PR left its base branch: `git merge-base SHA LANDED^`, where `LANDED` is the commit it
  merged as, its merge or squash commit. That works however it merged. Asking `main` alone does not after a merge
  commit, since the PR's head is on main now and you get the head back. Pinning it means every eval of the case reads
  the same diff.
- **`lines`**, for a bug, is where the bug is, as `path:line` or `path:first-last` from the repository's root,
  numbered as the file stood at `sha`, not after the fix. The fix's diff shows you where to look. A finding within 3
  lines of any one of them finds the bug, so name every spot a fair reviewer might point to, and nothing else.

A **clean** case has `kind = "clean"` and no `lines`, and every finding on it counts as a false alarm. Pick PRs that
have run in production for a while without a revert or a fix, and that look like they might not have: a clean case
that's a one-line docs change tests nothing.

Some habits make the score mean something:

- **Keep both kinds.** Bugs alone reward a reviewer that flags everything; clean cases alone reward one that says
  nothing.
- **Mix the shapes.** Small and large PRs, more than one repository, and the parts of the code you'd least like a bug
  in. Five bugs that are all off-by-ones measure the reviewer on off-by-ones.
- **Mind the thread.** The reviewer reads the PR's description and comments, so a PR whose thread ends "this broke
  prod, reverting" hands it the answer. Prefer cases whose conversation doesn't, or expect a flattering score.
- **Start small.** Each case is a full review, on your spend, so a handful of each kind is plenty to begin with.

Check a new case with `canopy review eval --dry-run`, which lists every case and flags one whose repository canopy
doesn't know or hasn't cloned, then `canopy review eval --case NAME` to review it alone. Run evals while the loop is
idle: an eval leases slots from the loop's pools, and a case the review guards refuse (the daily limit, review
capacity, `max_workers`) is skipped, not scored.

If you don't have history yet, a PR you open on purpose with a bug you know about works the same way. Score it lower in
your own head, though: you wrote that bug knowing it would be looked for.

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

Some changes are `high` whatever the reviewer thinks. A PR that touches `.github/workflows/`, in any repository, is
recorded `high`, and the review's `harness` line names the path that did it. The reviewer reads the PR's description,
and a description is exactly where someone would write "trivial CI tweak, nothing to see". Each repository can add its
own paths in the workspace file, as `high_impact_paths` in its `[repos.NAME]` table: canopy's own lists `.agents/` and
`docs/TRUST_MODEL.md`. An entry covers the path it names and everything under it; there are no globs. A repository's
list only adds, so nobody can take CI's workflows off it. `high` puts the PR's items first in `canopy status`,
`attention.md`, and your notifications. It doesn't buy a longer review.

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
the next review will read it: a rule in `AGENTS.md` or `REVIEW.md`, a test, or a lint rule. Then add the PR as a bug
case, so the next eval says whether the rule worked ([Adding eval cases](#adding-eval-cases)). A [chore](chores) can
read your existing code through GitHub on a schedule, too, and report the old bugs no PR's review was ever going to
look at.
