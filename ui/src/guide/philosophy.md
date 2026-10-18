# Philosophy

The few convictions canopy is built on, and what each one means for you. When the loop does something you didn't
expect, or pointedly doesn't do something you did, the reason is usually on this page.

## Stop herding monkeys

canopy started as an answer to a particular kind of day. Three agents going, each on its own branch. You switch your
IDE to one to check its work, stash what you were doing to look at another, restart a worker that wandered off, and
remember, mostly, which terminal belonged to which ticket. Each chore takes a minute. Together they take the day, and
the monkeys never get tired.

So canopy reconciles your work in the background. You label a ticket; the loop notices, gives its worker a worktree of
its own, comes back when CI fails or a review lands, and tells you when something needs you. Your checkout stays on
whatever you're doing. No branch moves under your editor, and no terminal is yours to babysit.

Background doesn't mean slow when you're in a hurry. When something needs doing now, push it: **Tick now** in the
header, or `t` at the loop's terminal, starts a tick at once; [starting a ticket](tickets#starting-a-ticket) brings it
in without its label; and a reply ends the loop's wait. The loop keeps its own pace until you give it yours.

## Your machine, your credentials

canopy runs where you are, as you. Workers act under your tracker and GitHub accounts, through the MCP servers your
agent runtime already holds tokens for, and canopy never sees those tokens. No vendor gets standing write access to
your repositories, your tracker, or the internal tools behind your own auth, and no service of canopy's sits in the
middle. That's the whole reason it exists: hosted agents can't reach what you can, and you shouldn't have to hand them
the keys to find out.

The price is that anyone who can write a ticket comment can try to talk an agent into something. Most of what follows
is how canopy pays it.

## The world is the source of truth

Your tracker and GitHub own the facts: what a ticket says, which PRs are open, what CI thinks, who reviewed. The
journal owns facts about the loop: what it saw, what it decided, what it started, and what came back. It never takes
its own notes over the world's. Every tick rereads live state and works out each ticket's phase fresh.

So you can work by hand without telling canopy. Merge a PR, close one, push a fix yourself, change a label: the next
tick sees it and carries on from there. When the journal and the world disagree, the journal is a stale cache, not a
bug, and the world wins.

## Judgment in prompts, limits in code

What to do about a ticket is the overseer's call, an agent reading the state and deciding. What the loop may never do
is canopy's, in code: how many workers at once, how many attempts, how long to cool down, one worker per ticket. No
prompt relaxes a [guard](how-the-loop-works#guards), however persuasive it gets, and when one refuses you see its name.

This is also why there's no workflow engine. Ticket dependencies, stacked branches, and "wait for that PR first" are
things the overseer reads and reasons about, not states in a schema. Teaching canopy something new is usually a tool
and a paragraph of prompt. The day a prompt proves unreliable at a rule, the rule moves into code, one at a time.

## Agents are untrusted

The overseer and the workers are language models, and canopy assumes they'll follow an injected instruction some of the
time. So text from other people is data, never orders. Authority comes only from things with permissions behind them:
who can add your queue label, whose replies may resume blocked work (`trust.authorized_repliers`), and whose reviews
may send a worker back to a PR (`trust.trusted_reviewers`). Anyone else's review waits on [Attention](attention) for
your word.

The aim is to keep the worst case at a branch nobody merged. No agent has web tools, canopy loads its agent
definitions from its own copy rather than the repository being worked on, and workers can run in an OS sandbox if you
set one up. The full argument, written to be handed to a security reviewer, is the
[trust model](https://github.com/eddieland/canopy/blob/main/docs/TRUST_MODEL.md).

## Humans approve and merge

canopy never approves a PR, never merges one, and never moves a ticket to Done. That isn't a feature waiting for a
milestone; it's the line. The loop gets the work to where a person can judge it, and a person judges it. You'll find
plenty of PRs on [Attention](attention) marked ready for their reviewer, and none marked merged by canopy.

## Hold nothing while waiting

A worktree is held only while an agent is actually working in it. Waiting on CI, on a review, or on your answer holds
nothing: the worker pushes its branch, hands the worktree back, and the pushed branch is the checkpoint. The next run
on that ticket, a `resume`, leases a slot and picks up from the branch. A small pool goes a long way when
nobody sits in a slot waiting for a green check.

## Tell you only what needs you

You shouldn't have to watch the loop to trust it. Each tick ends by rebuilding the [attention list](attention): a
question waiting on you, a run that failed, a ticket at its limit, a PR ready for review. An item leaves when its cause
is gone, not when you look at it, so the list is the state of things, not an inbox to clear. When nothing changes, the
loop backs off and ticks less often. Quiet is the system working, not the system broken; the header's breathing dot
tells the two apart.

## The smallest surface that works

Installing canopy is five steps, and canopy holds that number on purpose. Your coworkers need nothing new at all: they
file tickets, answer questions in comments, and review PRs, as they already do. Your own surface is a label, this UI,
and the CLI's verbs for the same.

The UI is a second front door, not a back door. Every action here runs the code its command runs, behind the same
guards, and a refusal reads the same in both places. The browser is where the loop is easiest to read, not where it
gets permission to do more.

## Boring on purpose

The Python never calls a model. It runs agent processes, reads what they say, and enforces the rules. State is one
SQLite file in your workspace. The loop is one command you started, and stops when you stop it; nothing installs it
with your OS or restarts it behind your back. No bot account, no tracker adapters, no retry logic hiding inside a
worker.

Each of those was easy to build and left out, because every moving part is one more thing to explain at 2am. When the
loop surprises you, the answer should be in [Ticks](ticks), in a transcript on [Runs](runs), or in a guard's name, and
never in a mechanism you didn't know was there.
