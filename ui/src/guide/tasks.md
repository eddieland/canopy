# Tasks

A task is work you hand canopy in your own words, about no ticket: find out why the nightly export takes an hour, try
an approach on a branch, or plan the tickets a feature should become. A worker runs it once, in a worktree of one
repository, and leaves a report, a branch, and perhaps a draft PR or a few tickets. Treat all of it as a first draft:
a task's output is where your own pass starts, not where it ends.

## A task, a ticket, and a chore

The three get confused, so here is the line between them.

- **A ticket** lives in the tracker. A label or `canopy start` authorizes it, and the loop drives it all the way to a
  PR: implement, fix CI, answer review, again and again until it's done. The overseer decides each step.
- **A chore** recurs. On a schedule, an agent reads what its tools reach and reports findings to the attention list.
  It changes nothing, ever.
- **A task** is one-off, and it's yours alone. Your text is the instruction, and your submitting it is the whole
  authorization: the overseer never sees it and never decides whether it runs, so nothing a stranger writes in a PR or
  a ticket can start, steer, or stop one. It runs when you ask, and again only when you reply.

If you'd file it in the tracker anyway, it's a ticket. If you'd want it every Monday, it's a chore. If you'd otherwise
open a terminal and an agent session for twenty minutes, it's a task.

## Submitting one

For now you submit a task from the shell:

```sh
canopy task submit "Find out why the Android build takes twelve minutes."
```

In a workspace of several repositories, name the one it runs in with `--repo NAME`. A task files tickets only when you
name a tracker project with `--project KEY`, and only there, with no queue label, so none of them is worked until you
say so. It opens a PR, as a draft, only when your text asks for one. Pass `-` as the text to read it from stdin, which
is easier for a paragraph than shell quoting is.

The next tick starts it, before the overseer runs, as capacity allows: tasks share `capacity.max_workers` with
everything else, and `capacity.max_tasks` caps how many of those may be tasks, so your side quests never starve the
queue. Its worker works on the branch `agent/task/N` (your `trust.branch_prefix`, then `task/N`), and pushes only if it
changed something. A task that commits nothing has not failed; sometimes the answer is the report.

## The list

[Tasks](/tasks) lists every task you submitted. Those waiting on your reply come first, since they are the only ones
that need you; the rest follow, the newest first. Each row leads with where the task stands: `waiting on you` when its
run asked a question, `queued` while it waits for a tick, `running`, or how its latest run ended (`done`, `failed`, and
the rest, in the colors a run's state wears), or `stopped`. Then `task:N`, its repository, the first line of your text,
and how long ago you submitted it. Under the text is the first line of what its latest run said.

The repository picker narrows the list once your tasks span more than one, and the count reads `2 of 7` while it does.
The list moves as the loop does: a task submitted, a run starting or ending, a reply, all show without a reload.
`task:N` opens the task's page.

## A task's page

A task's page reads as one story. Its title is `task:N` and the first line of your text; under it, where the task
stands, how many runs it has had, and when you submitted it.

**Conversation** starts with your instruction, whole and in your own words, on your side of the thread. Then come what
its runs said and your replies, in order, each message naming the run that wrote it (`task:4#5` is task 4's run
number 5, counted across every task's runs). While a run works, the thread ends on it, `working now`, with what it
has cost so far. A question waiting on you wears `waiting on you`, and the band under the thread says how to answer
it: from your shell for now, with `canopy reply task:N "TEXT"`, which the band offers to copy. With no question
waiting, the same line says a reply queues the next run.

**Report** is the page's main content: the newest report a run left, laid out as a document. It is the agent's
Markdown, drawn as a plan is, so headings, lists, and code read as they should and anything else (HTML, an image, a
link) stays its characters. The header names the run that left it, and says `edited` when the file changed since its
run wrote it. Under it is the file's path, to open in your editor. When there is no report yet, or its file is gone,
the panel says so.

**What it left** gathers the rest: the repository, the branch (with a link out once a run pushed it), each run's
pushed head commit, the draft PR, and the tickets it filed, each opening its page. Copy a commit, not the branch, when
a ticket should build on a task's work: the branch moves with every later reply, and the commit stays put. The line
under the panel is the whole policy: all of it is throwaway until you give it a pass of its own.

**Runs** lists every run, the first first: its status, `task:N#M`, cost, how long it took, and what it said.
`task:N#M` opens the run's page, here and wherever the page names a run.

## A task's run

A run's page is a worker run's page with the task in its trail: its title is `task:N#M` and your text's first line,
and under it how the run ended. **Run** has the whole of what it said, never cut to a line, and its question when it
asked one; for a run that failed, the call it ended on; the harness's note when canopy decided how it ended; the PRs it
named and the tickets it filed; when it ran, what it spent and on which models; its branch, the commit it pushed, and
its log.

Under it is the **transcript**, the session's events read from the run's log: what the worker wrote, each tool call
with its input and output, and what each model call cost, with the context chart one click away, as on a run's page.
It is the place to check how a run got its answer before you build on it. A run still working shows what its worker
has printed so far, and the page reads it again as the task moves.

## Replying and stopping

A run that needs something from you ends `blocked` with a question, and the task goes on the attention list as
`awaiting_reply`. Answer it with `canopy reply task:N "TEXT"`. A reply is also how you ask for more after a run is
done: the next tick starts another run on the same branch, with the conversation so far and the latest report.
A task never retries on its own; a run that failed stays failed until you say what to do differently.

`canopy show task:N` prints the task, each run, the tickets it filed, and its latest report. `canopy stop task:N` ends
it: a queued run is dropped, and a running one finishes unless you add `--now`. A stopped task is never deleted, so
its runs, its report, and what it cost stay there to read.
