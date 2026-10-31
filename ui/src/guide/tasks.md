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

The **Submit a task** panel at the top of [Tasks](/tasks) takes your text. It starts one line high and grows as you
write, so a paragraph is fine. Enter submits it, Shift+Enter starts a new line, and Settings can change the send key as
it does for a reply. Beside the text:

- **The repository** it runs in, shown only when the workspace has more than one. It starts at the one the list is
  narrowed to, else the one your newest task ran in, so a run of tasks against one repository needs no clicking.
- **The project**, optional: the tracker project it may file tickets in. Leave it empty and it files none.

The line under them is the whole of what a task may do outside its branch: it opens a PR, as a draft, only when your
text asks for one, and files tickets only in the project you name, with no queue label, so none of them is worked until
you say so. A refusal takes that line's place and names its guard, as the shell would: `bad_project` for a project that
isn't a plain key, `unknown_repo` for a repository the workspace doesn't have.

Once it's recorded, a note says so in the CLI's words (that the next tick starts it, and that none will while
`capacity.max_tasks` is 0) and you land on the task's page. Its row reaches the list the way every other change does,
over the live stream.

From the shell it's the same verb:

```sh
canopy task submit "Find out why the Android build takes twelve minutes."
```

Name the repository with `--repo NAME` and the project with `--project KEY`. Pass `-` as the text to read it from
stdin, which is easier for a paragraph than shell quoting is.

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
has cost so far. A question waiting on you wears `waiting on you`. Under the thread is the reply box, and while a
question waits it sits on the same amber band, naming the run that asked and the message it answers. Under that is
Stop.

**Report** is the page's main content: the newest report a run left, laid out as a document. It is the agent's
Markdown, drawn as a plan is, so headings, lists, and code read as they should and anything else (HTML, an image, a
link) stays its characters. The header names the run that left it, and says `edited` when the file changed since its
run wrote it. Under it is the file's path, to open in your editor. When there is no report yet, or its file is gone,
the panel says so.

**What it left** gathers the rest: the repository, the branch (with a link out once a run pushed it), each run's
pushed head commit, the draft PR, and the tickets it filed, each opening its page. Copy a commit, not the branch, when
a ticket should build on a task's work: the branch moves with every later reply, and the commit stays put. The line
under the panel is the whole policy: all of it is throwaway until you give it a pass of its own.

**Runs** lists every run, the first first: its status, `task:N#M`, cost, how long it took, and what it said, with
the [progress](runs#a-running-agents-progress) of one still working on a line under it. `task:N#M` opens the run's
page, here and wherever the page names a run.

## A task's run

A run's page is a worker run's page with the task in its trail: its title is `task:N#M` and your text's first line, and
under it how the run ended. Its **Progress** leads, once the worker has posted any, as a worker run's does, but with no
question in it: a task's run asks its question by ending `blocked`, and your reply starts the next. **Run** has the
whole of what it said, never cut to a line, and its question when it asked one; for a run that failed, the call it ended
on; the harness's note when canopy decided how it ended; the PRs it named and the tickets it filed; when it ran, what it
spent and on which models, the one canopy asked for first, as a worker run's page names them; its branch, the commit it
pushed, and its log.

A task's worker pushes like any other, so in a repository you keep a [checklist](reports#the-checklist-page) for, its
first push is held for the list too, and its answers sit in a **Checklist** panel under Run, as on [a worker run's
page](runs#a-runs-page). A one-off task doesn't get a pass on the house rules just for being one-off.

Under it is the **transcript**, the session's events read from the run's log: what the worker wrote, each tool call
with its input and output, and what each model call cost, with the context chart one click away, as on a run's page.
It is the place to check how a run got its answer before you build on it. A run still working shows what its worker
has printed so far, and the page reads it again as the task moves.

## Replying and stopping

A run that needs something from you ends `blocked` with a question, and the task goes on the attention list as
`awaiting_reply`. Answer it in the box under the task's conversation, or with `canopy reply task:N "TEXT"`; they are
the same reply. A reply is also how you ask for more after a run is done: the next tick starts another run on the same
branch, with the conversation so far and the latest report. If a run is still working, the next one waits for it to
end, and the line under the box says which run that is. A task never retries on its own; a run that failed stays
failed until you say what to do differently. What you write is kept while the tab is open, and a reply sent twice
after a flaky connection is recorded once.

Under Stop, **Attach a file** uploads a text file for the task's runs to read, such as the design doc you want
checked against the code, the same as `canopy attach task:N FILE`; your text or a reply says what to do with it. Each
later run gets a copy in its worktree, and the ✕ beside a file removes it. It works as on a ticket, limits and all:
[Attaching files](tickets#attaching-files) has the details. A stopped task keeps its list and takes no more files.

Stop ends the task, and it asks once more first, because nothing starts a stopped task again: there is no Start for a
task, only a new one. A queued run is dropped, and a running one finishes its work. Stop now, there while a run
works, ends that run too and gives its slot back, after its own second click. A stopped task takes no more replies,
so its page has no box; it is never deleted, so its runs, its report, and what it cost stay there to read.

From the shell, `canopy show task:N` prints the task, each run, the tickets it filed, and its latest report, and
`canopy stop task:N` stops it, with `--now` for Stop now.
