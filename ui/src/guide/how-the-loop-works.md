# How the loop works

The few ideas every page of the UI assumes you know: ticks, runs, phases, and guards. Ten minutes here saves an hour of
wondering why the loop did, or didn't, do something.

## Ticks

The loop runs in ticks. A tick tidies up after the last one (a worker that died is marked, a worktree nobody holds is
returned), then runs the overseer, an agent that reads the world fresh: your tracker and GitHub, through the agent
runtime's MCP servers, and the worktree pools. For each ticket it works out where things stand and decides what comes
next: start a worker, wait, skip, or put something on the attention list. Every one of those is a decision, recorded
with the overseer's reasons, and the [Ticks](/ticks) page shows them all.

Between ticks the loop waits `loop.interval_minutes`, 15 by default. When a tick finds nothing new, the next wait is
longer, doubling up to `loop.idle_max_minutes`, so a quiet afternoon doesn't cost a tick every quarter hour. Anything
you do that the loop should hear about ends the wait early: a reply, a start or stop, a grant, a notice to workers.
So does a run ending, a cooldown running out, a chore coming due, or a notice lapsing. Even then it waits at least
`loop.min_gap_minutes` after the last tick ends, one minute by default. **Tick now** in the header skips even that.

While it waits, the loop also polls: every `connect.every_minutes`, two by default, it runs the connectors that read
your tracker and GitHub into canopy's own record, and the comments on your artifacts if you set up a source for them.
A poll runs no overseer, so it keeps that record fresh however long you set the wait between ticks. For now nothing
acts on what a poll reads, and a poll never starts a tick early.

## Runs

A run is a worker agent doing one piece of work on one ticket. The overseer starts it; the run leases a worktree from
its repository's pool, does the work, pushes a branch, opens or updates a PR, and hands the worktree back. Runs
outlive the tick that started them, so a long one spans many ticks. Each run has a kind:

- `implement`: the first pass at a ticket.
- `resume`: back to a PR for whatever came back to it: failed checks, review comments or canopy's own review findings,
  your reply, a conflict with its base, a branch with no PR yet, or a blocker that merged. A resume names its reasons,
  and the run's chip shows them, as in `resume (ci, review)`. One resume takes all of a PR's reasons at once, so a red
  build and a reviewer's comment get one run and one push, not two runs racing for the same branch.
- `plan`: writes a plan for you to approve before the first implement. See [Plans](plans).
- `feedback-plan`: with `policy.feedback_plan = "approve"` in your own config, a plan for what came back to a PR,
  approved before the resume that acts on it. It reads the PR and pushes nothing.

Older runs may say `fix-ci`: that was a kind of its own before a resume took over fixing CI. They still show as they
ran, and count toward the ticket's resume limit. Older still, a `split` run broke a ticket into child tickets, before
workers filed follow-ups (below) instead; those show as they ran and count toward no limit.

A run ends `done`; `waiting on you`, when the worker stopped to ask you something; `stopped`, when you ended it; or
failed, in one of several ways: `failed`, `crashed`, `timeout`, `unpushed` (it said done, with work it never pushed),
or `unknown` (its last words weren't a result canopy could read). Every failed run reaches the attention list.

Every run has a timeout, and near it, each tool call tells the agent how many minutes it has left, so a worker pushes
what it has rather than losing it with its slot. That's advice: the timeout is still what ends the run.

Reviews and chores are runs too, of their own kinds, with their own pages: a review reads one PR at one commit and
reports findings, and a chore is recurring work no ticket asked for. [Runs](/runs) lists them beside the workers;
[Pull requests and reviews](pull-requests) and [Chores](chores) cover them.

## Phases

Every ticket has a phase, and so does each of its PRs: where it stands, as the overseer last worked it out. A ticket
is `ready`, `running`, `needs human`, `human replied`, `blocked` (on another ticket), or `plan proposed`. A PR
goes through phases such as `ci running`, `ci red`, `review pending`, `review findings`, `changes requested`,
`green unreviewed`, `approved`, and `merged`. The UI writes them with spaces; hover over one, or Tab to it, for the
CLI's spelling.

The overseer derives a phase from live state every tick and never takes the journal's word for it. If a PR merged at
lunch, the next tick knows, whatever canopy last wrote down.

## Public and private tickets

A ticket is **public** when its queue label brings it in, `agent-ready-` and your name by default. Its conversation
lives on the tracker, where workers write their reports and questions, and canopy keeps a copy.

A worker may file **follow-up** tickets: a TODO its change leaves, a bug it tripped over and didn't fix. Each one is
created in the ticket's project, linked to it, with no labels and nobody assigned, and that is all it is: a request.
canopy works none of them until you say so, the usual way, with your queue label or `canopy start`. Your
notification sinks hear about them once, when the run that filed them ends, and the worker's report lists them too.
They don't sit on the [attention list](attention): ignoring one, or closing it in the tracker, is a perfectly good
answer, and canopy has no business nagging you about it. At most five a run (`policy.max_follow_ups`; 0 turns them
off), and a follow-up files none of its own. A private ticket's worker files them too, the one thing it writes to the
tracker, so anyone on the tracker can read them. Want a ticket cut into pieces? Reply asking for it, and its next run
files the pieces as follow-up tickets, for you to label or start.

A ticket is **private** when you start it in canopy, from [Tickets](tickets#starting-a-ticket) or with
`canopy start KEY`. It needs no label, and its conversation stays in canopy: workers read the ticket and write nothing
to it. That's how you deliver a ticket a client filed without them reading the agent's working notes.

You can reply to either kind in canopy. On a public ticket your reply reaches its workers and never the ticket. That's
also how you answer a review from someone outside `trust.trusted_reviewers`, whose comments wait for your word before
any worker acts on them.

## Guards

Judgment is the overseer's; limits are canopy's own, in code, and no prompt talks its way past them. When the overseer
asks for something a guard won't allow, the decision is recorded as `refused` with the guard's name, and the UI shows
it as the CLI does. The ones you'll meet most:

- `capacity`: at most `capacity.max_workers` runs and reviews at once. A refused ticket waits for a slot.
- `attempt_limit`: each kind of run has a limit per ticket, such as `policy.max_resume_attempts`, six by default.
  Every run counts, however it ended, and nothing resets the count. A ticket at its limit reaches the attention list,
  and **Allow one more** on its page grants it another run.
- `cooldown`: a resume for failed checks alone waits `policy.ci_cooldown_minutes` after the last run that worked on
  CI. A resume with review comments or your reply goes at once, and fixes the build on the way.
- `running`: one worker per ticket. A second one would only argue with the first.

And the guard that never lifts: canopy never approves or merges a PR, and never moves a ticket to Done. Those stay
yours.

## The attention list

Each tick ends by listing what needs a human: a question waiting on you, a run that failed, a ticket at its limit, a
PR ready for its reviewer. The list is rebuilt every tick, and an item leaves when its cause is gone, not when you
look at it. You'll read it on [Attention](attention), and it's the reason you can leave the loop running and get on
with your day.
