# Epics

An epic is work that spans several tickets, toward one goal you write in your own words. canopy plans the whole
once, you approve that plan once, and each ticket you make a member is then planned against it, so its planner stops
settling the shared questions again and you stop approving them again.

## An epic, a ticket, and a task

- **A ticket** is one piece of work in the tracker, planned and built on its own. See [Tickets](tickets).
- **A task** is one-off work in your words, about no ticket, run once in one repository. See [Tasks](tasks).
- **An epic** is the plan over several tickets: the goal, the requirements it traces to your words, the contracts
  between the tickets, and a breakdown of which tickets to file. It writes no code and files nothing on its own.

Like a task, an epic is yours alone. Your text is the instruction and your submitting it authorizes its plan runs; the
overseer never sees it, and its conversation never touches the tracker. The word is canopy's: an epic in Jira or
GitHub is a [tracker epic](glossary#tracker-epic), and it never becomes one of canopy's by itself.

## Submitting one

**New epic**, at the top of [Epics](/epics), takes the goal in your own words: what is true once it's done, and why.
Write it as you would a reply, with the same toolbar, and the same microphone where canopy offers dictation. Under it:

- **The repositories its plan reads**, picked from the workspace's. With several, name each one the work touches; the
  form won't send until you do, since a planner guessing which repositories matter is how a plan misses one. A
  workspace of one needs no choice.
- **Tracker project**, optional: where its tickets are filed. With none, the epic files no tickets.
- **Tracker epic**, optional: a [tracker epic](glossary#tracker-epic) whose tickets are put to you as suggestions.
  They're only that: none becomes a member until you add it.

**Submit**, or the send key, records it and opens the epic's page, `queued`: the next tick starts its plan run, before
the overseer, within `capacity.max_workers`. A submission refuses as the command does, naming the guard: an empty goal,
a repository the workspace hasn't got, a project or tracker epic that isn't a plain key, and anything sent from inside
a tick or a run.

From the shell it is the same:

```sh
canopy epic submit "Let customers export their invoices as CSV, from the API and the web app." \
    --repo api --repo web --project ABC
```

## Its plan

A planner reads the epic's repositories and writes one plan, in an outline that does not change: the goal; each
requirement `R1`, `R2`, ... traced to your words; each contract `C1`, ... between the tickets, with who provides it
and who uses it; the breakdown, each entry `B1`, ... with the requirements it covers, the contracts it provides and
uses, its repositories, and what it comes after; its decisions; and what is out of scope. It is shallow on purpose:
no ticket's steps, which each ticket's own plan writes just before it is built.

The ids are the one part of the plan canopy reads, and they never change meaning, so a later plan can say what it
changed by id. A plan waiting on you is on [Attention](attention), as `plan review` on `epic:N`. You approve the plan
from its page, or ask for changes there (`canopy plan epic:N --approve` and `canopy reply epic:N "TEXT"` in a
terminal), and the next tick plans again with your reply. Its plan runs count against
`policy.max_plan_attempts` and are never reset, so a planner that can't land one stops rather than burning the budget
on its fortieth try.

## Its members

A member is a ticket you add to the epic, usually one you filed for an entry of the approved plan. You add one from
[the epic's page](#an-epics-page): **Register a ticket** beside an entry's `none yet`, or **Add a ticket** under the
breakdown. A ticket is a member of one epic at most, and an epic holds `policy.max_epic_tickets` at most. Being a
member authorizes no work: a member is worked once you label it or start it, like any other ticket, and then its
planner reads the epic's approved plan beside its own ticket, and so does each worker after it, so the contracts its
siblings build against are in front of the one doing the building.

A member whose every entry the approved plan marks `trivial` skips its own plan: approving the epic's plan approved it,
and its implement goes straight to work with the epic's copy. Its plan card says `not needed` and, on hover, the
plan's reason. The mark only counts while `policy.planner_may_approve` is on, and never for a ticket you asked to plan
(`canopy plan KEY`), a member of no entry, or one registered against an entry the plan no longer holds. Approve a plan
that drops the mark and the member waits on a plan of its own again, which is the point: the epic planner's "it's only
a config change" holds until you approve otherwise.

A member's own page says whose it is: its **Work** panel reads `member of epic:2 · B1`, or `of no entry`, one click
from the epic. Its plan's page names the epic plan its planner read, by hash, and when you approved it, and says when
you've approved a newer one since. See [Reading a plan](plans#reading-a-plan).

In a terminal, name the entries it fulfils with `--entry`, once for each, or `--no-entry` for one the breakdown didn't
foresee, and `canopy epic remove` takes it out again:

```sh
canopy epic add epic:2 ABC-140 --entry B1
canopy epic remove epic:2 ABC-140
```

## The list

[Epics](/epics) lists every epic you submitted, the newest first. Each row leads with where the epic stands, in the
color a run in that state wears:

- `queued`, muted: the next tick starts its plan run.
- `planning`: its plan run is working.
- `waiting on you`: its plan is proposed. Approve it, or reply with what to change.
- `approved`: you approved its plan, and its breakdown is what's left to file.
- `unplanned`, in the failure color: its plan runs ended without a plan, and none starts again until you reply. Once
  `policy.max_plan_attempts` is used up, a reply starts none either.
- `stopped`, muted as `queued` is: you stopped it, from [its page](#stopping-one) or with `canopy stop epic:N`. No plan
  run of it starts again, a reply to it is refused, and its members are left as they are. A plan run working when you
  stopped it finishes, unless you end it now, and until then the epic still reads `planning`.

Hover the word for its spelling in the CLI and what it means. Then come `epic:N`, which opens its page, its
repositories, your goal's first
line, how many of its breakdown's entries have a member (`2 of 4 entries filed`; `no breakdown` before it has a plan,
and `breakdown unreadable` for a plan canopy can't read: its file is gone, or its ids repeat or won't parse), and how
long ago you submitted it. A stopped epic says under its goal how long ago you stopped it.

The list moves as the loop does: a plan run starting or ending, a stop, a reply, a member added from the shell, all
show without a reload, and so does an epic's page you have open, its plans with it.

From the shell, `canopy epic list` lists them and `canopy show epic:N` prints one, its breakdown with each entry's
members.

## An epic's page

An epic's page answers what is left to file, and how far along each part is. Its title is `epic:N` and your goal's
first line; under it, where the epic stands, how many of its breakdown's entries are filed, how many members it has
against `policy.max_epic_tickets`, and when you submitted it; once you stopped it, it says so, and when. The first time
you see every entry filed, as you register the last one or on your next visit, the count lights up and drops a leaf,
once. Once it has a plan, **Open plan** at the title's right opens [its plan's page](#an-epics-plan), and **Stop**
beside it [stops the epic](#stopping-one).

**Breakdown** leads, at the page's width: a row per entry, in the plan's order. Each row has the entry's `B` id and
title, `trivial` when the plan marks it so (hover it for why), the requirements it covers, the contracts it provides
and uses, its repositories, the entries it comes after, and its members: each ticket's key, opening its page, with
the dot of its latest run and its phase. An entry with no member says `none yet`: that is what's left to file. Before
you approve a plan, the board is the proposed plan's, marked `proposed`, and every entry is still to file. The mark,
`proposed` or `approved`, opens the plan it names. With no
plan yet, the board is one line: the plan run writing it, or what starts the next. A plan canopy can't read says why
in place of the rows. Under the board come the members it has no row for: those of no entry, with their titles, and
those registered against an entry the approved plan has since dropped.

Once its plan is approved, an entry with no member offers **Register a ticket**: type the ticket's key, and the entries
it fulfils are checked, that entry first; check more if it fulfils several. **Add a ticket**, under the board, does the
same with none checked, for one ticket of several entries, or of none, one the breakdown didn't foresee. Before a plan
is approved there are no entries to choose, so a ticket you add then is a member of no entry until you register it
again. Registering a member again replaces its entries, so the same form moves a ticket from one entry to another.
Hover a member and its **×** removes it, once you say so: the ticket and its work stay as they are, and only its
membership ends. Each refuses as its command does: a ticket another epic holds, an epic already at
`policy.max_epic_tickets`, an entry the approved plan doesn't hold, and anything done from inside a tick or a run.

Point at any `R`, `C`, or `B` id on the page, with the mouse or by tabbing to it, and it lights up wherever it shows,
with every entry that cites it: a requirement lights the entries that cover it, a contract the ones that provide and
use it, an entry itself and the ones that come after it. Its hover says the same in words: a requirement's text on the
board, who covers it under **Requirements and contracts**, so a requirement no entry covers stands out.

**Conversation** starts with your goal, whole and in your own words, then what each plan run said and your replies, in
order. A plan run is named `epic:N#M`, the epic's plan run number M, counted across every epic's plan runs. A question
a plan run asked wears `waiting on you` until you reply.

**Requirements and contracts** lists each `R` and `C` with what the plan says of it. **Plan runs** lists every run of
the planner, the first first: how it ended, `epic:N#M`, cost, how long it took, and what it said.

### Stopping one

**Stop**, at the title's right, ends the epic's planning: no plan run of it starts again, and it takes no more
replies. It asks once more first, since nothing undoes a stop, and says that its members and their work are left as
they are: a stop ends no member's run and removes no member. Its waiting plan may still be approved, and its members
still added and removed. While a plan run of it works, that run finishes its work unless you also press **Stop now**,
which asks once more too, then ends the run and returns its slots, or says it couldn't return one. Stopped with its
run still working, the epic keeps **Stop now** alone. What the stop did is said under the buttons, in the command's
words; it refuses inside a tick or a run, as the command does:

```sh
canopy stop epic:3        # its plan run at work finishes
canopy stop epic:3 --now  # and ends it now
```

## An epic's plan

The plan's text gets a page of its own, `/epics/N/plan`, since it wants the width: its trail is Epics, then `epic:N`,
which takes you back to the breakdown.

The newest plan opens in the plan editor, read only, as its file stands now. An epic's plan takes no comments, so it
has no margin: what you want changed goes in a reply, which reads the whole plan anyway. Its header has its status,
`waiting on you` while it is proposed and no plan run is working, or `changes asked` once you asked and the next tick
has yet to act on it, and how long ago it was written, then the plan's
modes: **Markdown** shows the file as written, and **Outline** jumps to a heading. A plan that replaced another opens
with **Changes since plan N** pressed while it waits on you, so you read what your reply changed rather than the whole
thing again.

Under the title, a line says which plan run wrote it (`epic:N#M`), when you approved it and how, and whether its file
was edited since the planner wrote it or since you approved it. Under that is the file's
`sha256` as it stands, the start of it shown, the whole on hover and copied by the button beside it. canopy approves a
plan by that hash and keeps a copy, so an edit after approval doesn't sneak in: canopy goes on reading the copy you
approved, and a change you want goes in a reply, which asks for a new plan.

While the plan waits on you, its foot, stuck to the bottom of the window as you read, has your two ways out:

- **Approve** approves it as its file stands, by the hash the page read. If the file changed after the page loaded,
  say in your own editor, canopy refuses (`stale`) and the page reads it again, so you approve what you read and
  nothing else. It also refuses a plan whose ids won't read (`bad_outline`) or that brings back an id an earlier
  approval dropped (`reused_id`). Approved, it says what changed since the plan you approved before, by id: added,
  removed, changed. Then the epic's board leads with the approved breakdown.
- **Ask for changes** sends the note you write beside it as a reply, which the next plan run reads. It says what that
  starts: the next tick's plan run, the next one after the run at work, or none at all once the epic has had
  `policy.max_plan_attempts`. Until a run picks it up, a band under the title says you asked. Approving in the
  meantime still works, and is your later word. Approve stays off while a note is written, since an approval carries
  none, and a note you meant to send shouldn't vanish into a plan you approved instead.

An epic's planner writes the choices your goal left open the way a ticket's does, under Decisions, and the page asks
them the same way: **Open decisions**, under the plan, each with the planner's choice picked, and `↓ 2 open decisions`
in the foot to take you there. The difference is where an answer goes. A ticket's approval can carry a note to its
implement; an epic's can't, because the members' planners read the approved plan itself, and a plan that says A with
a note that says B is how you get half of each. So picking another option is asking for a new plan: the answer goes
with **Ask for changes**, and **Approve** waits until you send it or pick the planner's choice again. With nothing
answered, the button reads **Approve as planned**. See [Approving, or asking for
changes](plans#approving-or-asking-for-changes) for the rest.

Both refuse inside a tick or a run, as the commands do. Once you've [stopped the epic](#stopping-one), its plan offers
**Approve** alone, and asks no decisions: a stopped epic takes no reply, so nothing would plan it again.

**Earlier plans** lists the plans this one replaced, the newest first, each folded. Open one to read it as it was, in
the same editor.
