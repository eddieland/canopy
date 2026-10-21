# Glossary

The words the rest of the guide leans on, each in a sentence or two, with a link to the page that says the rest. When
a page uses a word as if you already knew it, it's probably here.

## The loop

### Agent runtime

The program that runs canopy's agents, such as OpenCode: canopy hands it a prompt and reads what comes back. It holds
the MCP servers, and with them your tokens for the tracker and GitHub, so canopy never has to.

### Attention list

What needs a human, rebuilt at the end of every tick: a question waiting on you, a run that failed, a ticket at its
limit, a PR ready for its reviewer. An item leaves when its cause is gone, not when you look at it. See
[Attention](attention).

### Decision

One thing the overseer decided in a tick, such as starting a run, waiting, skipping, or putting something on the
attention list, with its reasons in its own words. A decision a guard stopped is recorded as `refused`. See
[Ticks](ticks#a-ticks-page).

### Dry run

A tick from `canopy tick --dry-run`: the overseer decides as usual, and nothing is dispatched. The tick carries a
`dry run` chip, in its row and on its page. The cheapest way to find out what the loop would do.

### Guard

A limit canopy enforces in code, whatever the overseer asks for: `capacity`, `attempt_limit`, `cooldown`, `running`,
and a few more. No prompt talks its way past one, and a refusal names it. See
[How the loop works](how-the-loop-works#guards).

### Idle tick

A tick that started no work: it dispatched no run, and nothing new reached the journal since the tick before. The loop
waits longer after each one, up to `loop.idle_max_minutes`. See [Ticks and spend](ticks#idle-ticks).

### Journal

canopy's own record, one SQLite file in your workspace: what the loop saw, what it decided, what it started, what came
back, and every conversation. It holds facts about the loop, never about the world. When the two disagree, the journal
is a stale cache and the world wins. See [Philosophy](philosophy#the-world-is-the-source-of-truth).

### Notice to workers

A message every run dispatched from now on hears, such as news of a CI outage, until it lapses. Set it on
[Settings](settings#notice-to-workers) or with `canopy notice`.

### Overseer

The agent each tick runs to read the world fresh and decide what comes next for every ticket. It decides and the
workers do, and guards hold what it may ask for. See [How the loop works](how-the-loop-works#ticks).

### Pause

Stops new ticks from starting until you resume, from the header or `canopy pause`. A tick or run already going
finishes. It's kept in the journal, so it outlives a restart of the loop.

### Tick

One pass of the loop: tidy up after the last one, run the overseer, record its decisions, and rebuild the attention
list. Between ticks the loop waits, longer when they find nothing. See [How the loop works](how-the-loop-works#ticks).

### Workspace

The directory you run canopy in: its `canopy-workspace.toml`, the repositories it works on, and `.canopy/`, which
holds the journal, the log, and your private config.

## Tickets

### Authorized replier

Someone in `trust.authorized_repliers`, whose replies on the tracker may resume blocked work. Everyone else's comments
are data: canopy reads them and acts on none of them.

### Conversation

Every message on a ticket: the workers' reports and questions, your replies, and, on a public ticket, the tracker's
comments, copied in. See [Attention](attention#replying).

### Feedback plan

A plan for what came back to a PR, written before the resume that acts on it, with `policy.feedback_plan = "approve"`
in your own config: you read whose each item is and approve what gets addressed. A run of its own kind,
`feedback-plan`. See [Plans](plans).

### Follow-up

A ticket a worker filed for work it found outside its own, linked to its ticket as the parent. It authorizes nothing:
your sinks hear of it once, it never sits on the attention list, and canopy works it only once you label it or start
it. See
[How the loop works](how-the-loop-works#public-and-private-tickets).

### Phase

Where a ticket or a PR stands, as the overseer worked it out from live state this tick. A ticket is `ready`,
`running`, `needs human`, and so on; a PR is `ci red`, `review findings`, `approved`, and the like. See
[How the loop works](how-the-loop-works#phases).

### Persona

The voice a run writes in: how a worker words its PR, how a planner lays out its plan, how hard a reviewer presses. It
changes voice, never a guard. Chosen in `[personas]`, per ticket on its page, or for one run. See
[Choosing a persona](tickets#choosing-a-persona).

### Plan

A worker's proposal for a ticket, written before any code, that you approve before the first implement. See
[Plans](plans).

### Private ticket

A ticket you started in canopy, from [Tickets](tickets#starting-a-ticket) or with `canopy start KEY`. It needs no
label, and its conversation stays in canopy: workers read the ticket and write nothing to it. See
[How the loop works](how-the-loop-works#public-and-private-tickets).

### Public ticket

A ticket the queue label brought in. Workers write their reports and questions on the tracker, and canopy keeps a copy.

### Queue label

The tracker label that brings a ticket in, `agent-ready-` and your name by default. Adding it hands a ticket to the
loop, and removing it is how you stop a public one. It decides which tickets get worked, not who wrote them, so keep
the loop away from trackers where people you don't trust file tickets ([Philosophy](philosophy#agents-are-untrusted)).

### Reply

What you write to a ticket's workers, in its conversation or with `canopy reply KEY`. The loop reads it at its next
tick. On a public ticket it reaches the workers and never the ticket. See [Attention](attention#replying).

### Ticket

A piece of work in your tracker, by its key, such as `ABC-102`: the unit canopy works in, with its branch, its PRs,
its runs, and its conversation. One worker at a time, never two. See [Tickets](tickets).

### Tracker

Where your tickets live, such as Jira or GitHub Issues. canopy reaches it only through the agent runtime's MCP servers.

### Waiting on you

A ticket or run whose worker stopped to ask you something. Not the same as `blocked`, which is a phase: another ticket
holds this one up.

## Runs and worktrees

### Attempt limit

How many runs of each kind a ticket may have, such as `policy.max_resume_attempts`, six by default. Every run counts,
however it ended. See [Tickets](tickets#allowing-one-more-run).

### Context

Everything one model call is sent: the prompt, and every tool call and result before it. A run's cost grows with it,
which is why a run's page charts it call by call. See [Runs and worktrees](runs#context).

### Grant

One more run past a limit, from **Allow one more** or `canopy grant`. It raises the limit and dispatches nothing; the
next tick decides whether to use it.

### Kind

What a run is for: `implement`, `resume`, `plan`, or `feedback-plan`. Older runs may say `fix-ci`, from before a resume
fixed CI, `split`, from before workers filed follow-ups, or `needs-plan`, a triage from before every planned ticket got
its plan. Reviews and chores are kinds of their own. Each worker kind has its own attempt limit, a review counts toward
its PR's review limit, and a chore has none. See [How the loop works](how-the-loop-works#runs).

### Pool

A repository's set of worktrees, kept by treehouse, or by canopy itself when your own config sets
`pools.backend = "canopy"`. A run leases a slot from it and hands it back when it stops working. See
[Runs and worktrees](runs#worktrees).

### Reason

Why a resume runs, named when it is dispatched: `ci` for failed checks, `review` for review feedback, `reply` for your
answer, `conflict` for a clash with the base, `no_pr` for a pushed branch with no PR, and `retarget` when the PR it
was stacked on merged. One resume carries every reason its PR has. See [How the loop works](how-the-loop-works#runs).

### Run

One agent session doing one piece of work: a worker on a ticket, a review of a PR, or a chore. Runs outlive the tick
that started them. A run ends `done`, `waiting on you`, `stopped`, or in one of several ways of failing. See
[How the loop works](how-the-loop-works#runs).

### Slot

One worktree in a pool: `working`, `held`, `dirty`, `idle`, or `broken`. See [Runs and worktrees](runs#worktrees).

### Transcript

A run's session, from its log: its text, every tool call, every model call, and what each cost. When you want to know
what an agent was thinking, this is the receipt. See [Runs and worktrees](runs#a-runs-page).

### treehouse

The tool that keeps canopy's worktree pools and their leases, unless your own config sets `pools.backend = "canopy"`:
then canopy keeps them itself, under `pools/` in the workspace, with the leases in its journal. Either way canopy asks
the pool for a slot and gives it back, so no run ever works in your own checkout.

### Worker

The agent in a run on a ticket: it leases a worktree, does the work, pushes a branch, opens or updates a PR, and
hands the worktree back.

### Worktree

A checkout of a repository on a branch of its own, where a run works without touching yours. It's held only while an
agent works in it; between runs, the pushed branch is the checkpoint. See
[Philosophy](philosophy#hold-nothing-while-waiting).

## Pull requests and reviews

### Draft

A reply a run wrote for you to send, on a PR's review thread or on its ticket, kept until you **Send**, **Edit**, or
**Drop** it. With `trust.review_replies = "approve"`, the default, nothing a worker writes to a coworker goes out any
other way. See [Pull requests and reviews](pull-requests#replying-to-your-coworkers-reviews).

### Finding

One thing a review or a chore found. A review's finding is `blocking`, `major`, or `minor`, pinned to the line it
names; you can dismiss it or send it to a worker. A chore's reaches the attention list. See
[Pull requests and reviews](pull-requests#acting-on-findings).

### Review

A fresh agent's adversarial read of one PR at one commit, in one persona. canopy keeps it to itself and posts nothing
of it on its own; on a PR the loop doesn't own it's also a draft of your review, posted only when you publish it. See
[Pull requests and reviews](pull-requests#when-canopy-reviews).

### Review limit

How many reviews a PR may have, `policy.max_reviews_per_pr`, three by default. **Allow one more** on the PR's page
grants another.

### Trusted reviewer

Someone in `trust.trusted_reviewers`, whose review may send a worker back to a PR on its own say-so. Anyone else's
waits as `untrusted review` for your word, and that includes canopy's own reviewer until you list `canopy:review`.

### Verdict

A review's outcome at a glance: `clean`, or a count of its findings with the worst among them, such as
`3 findings, 1 major`.

## Chores and memory

### Chore

A scheduled task with an agent's judgment: on a schedule you set, an agent reads what its tools reach (CI, PRs, the
tracker, Sentry, canopy's own journal), decides what matters by your prompt and notes, and reports each problem as a
finding on the attention list. It changes nothing. Defined as `[chores.NAME]` in your config; the overseer runs it when
it's due and worth it. See [Chores](chores).

### Lesson

A proposal you promoted into memory, in your own words if you like. Every worker in the workspace reads it, which is
why only you can make one. See [Memory](memory#two-tiers).

### Note to a chore

An instruction to a chore's next runs, from its page or `canopy reply chore:NAME`. Every run reads the latest ten. See
[Chores](chores#notes-to-a-chore).

### Proposal

A lesson a worker suggests. It reaches no prompt until you promote it, and expires after 14 days if nobody does.

### Recording and in use

A memory tier's modes once it's on. While recording, workers write and no run reads, so you see what the tier would
hold; in use, runs read it too. See [Memory](memory#turning-it-on).

### Ticket note

What a ticket's runs leave for its later runs, dead ends included. Only that ticket's runs read them.
