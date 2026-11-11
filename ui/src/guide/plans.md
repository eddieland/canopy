# Plans

A plan is a worker's proposal for a ticket, written before any code: what it will change, where, and how it will
know it worked. You read it, comment on it, edit it, and approve it, and nothing is implemented until you do. It's the
cheapest code review you'll ever do, because there's no code yet.

## When a ticket gets a plan

A ticket needs a plan when `policy.plan` is `approve` in your config, or when you asked for one with `canopy plan KEY`
or `canopy start KEY --plan`. `canopy plan KEY --skip` waives it for one ticket. Until a plan is written, the ticket's
**Plan** card says `needed`, and hovering it says why: `policy.plan`, or the ticket's own setting. A ticket that needs
no plan has no card at all.

The next tick then dispatches a `plan` run. It writes the plan as a Markdown file, and the ticket's phase becomes
`plan proposed`, which puts a `plan review` item on your attention list. Until you approve, the overseer can't start an
implement: the [guard](how-the-loop-works#guards) is `unplanned`, and no prompt gets around it.

A typo fix gets a plan too, if the policy says so. canopy once let a cheaper agent judge such work trivial and skip
its plan, and it judged so little trivial that it cost more than the plans it saved. So `--skip` the ones you'd
rather not read, or let the planner, which has just read the ticket and the code, say so for you.

## When the planner says a plan needs no review

Set `policy.planner_may_approve` in your own config, the user file or the workspace's private one (a shared file
can't), and the planner may answer that its plan needs no review, with a sentence saying why. canopy then approves
the plan on the planner's word: the implement goes ahead without you, no `plan review` item appears, and your sinks
get one line saying so. The **Plan** card says it was **approved by** the planner, with that sentence, so you can read
the plan after and disagree at leisure. Feedback plans take the same key.

The key is a level, for how much you'd rather not read. The planner may waive your review:

- `off`, the default: never. Every plan waits on you.
- `strict`: when the plan leaves you nothing to judge. Small, plain, every choice settled by the ticket and the code,
  and no interface anyone uses touched.
- `normal`: when the plan follows patterns the code already has and the ticket settles its scope. A small, additive
  interface change is fine.
- `lenient`: when the plan is the planner's confident best reading of the ticket and leaves no real question open.

`true` still means `strict` and `false` still means `off`, so a file written for the old switch keeps working. No level
waives review of a plan that touches security, credentials, a change that could lose data, or migrations, and a
ticket that asks the planner to skip your review gets one. `strict` approves very little, which is the point of it;
if you've watched it decline plan after plan you'd have waved through, `normal` is the next notch. The
[Plans page](reports#the-plans-page) shows how each level's approvals went, and whether their PRs needed a resume, so
you loosen it on evidence rather than a hunch.

A feedback plan, the one for what came back to a PR, lives on that PR's page, not here: see
[The feedback plan](pull-requests#the-feedback-plan). While one waits on you, the ticket's page leads with a card
that points there, and its run's page names the plan it wrote.

The planner's word counts only until you've had one of your own. Once you've asked for changes, or asked for the plan
by name with `canopy plan KEY`, every plan after waits on you, whatever the planner thinks. Edit an approved plan and
it needs your approval again, as any plan does. The ticket's text can talk a planner into anything, including this,
so the PR's review is still where the work gets judged.

## Reading a plan

A plan has a page of its own, so it gets the whole width and its comments get a margin. The ticket's page has a
**Plan** card instead, at the top while the plan waits on you, and a `plan review` item in [Attention](attention)
shows the same card. It says where the plan stands (`waiting on you`, in amber like everything else that is, then
`approved` or `superseded`), which plan it is (`plan:2`), the run that wrote it and when, its **effort**, and how
many comments are open. The effort is the planner's guess at how much work the plan is for the worker that follows
it, `small`, `medium`, or `large`: a hint for your reading, which canopy acts on nowhere. **Approve** on the card
approves it as its file stands, for when you've already read it; **Open plan** opens its page, where the rest
happens: comments, edits, asking for changes, skipping.

A plan that leaves [decisions open](#approving-or-asking-for-changes) asks them on the card too, right over the
button, each with the planner's choice picked. So the one part of a plan addressed to you is read before you approve
it, even on the days you approve from Attention without opening anything. Pick another option and it goes with the
approval, to the implement. While you've picked nothing, the button reads **Approve as planned**: it takes the
planner's choices, and says so itself. In Attention, a `plan review` row says `2 decisions` beside its ticket's key,
so you can tell a plan with questions from a rubber stamp before you open either.

There, the plan opens in an editor. The page's title names the plan and its ticket, and the line under it says which
run wrote it, when you approved it and how, whether its file was edited since, and its effort. A member of an epic
gets one more line: `follows epic:2's plan`, the start of that plan's hash, and when you approved it, since its planner
read the epic's approved plan beside the ticket. When you've approved a newer plan of the epic since, the line says so
and when, and leaves what changed for you to read on [the epic's plan page](epics#an-epics-plan). The **Plan** panel's
header says where it stands and how old it is. Under the plan, **Persona** names the persona its planner wrote in,
with the start of its text's digest, and **Show instructions** opens exactly what that persona told it: canopy keeps
each persona's text once per digest, so editing the file later doesn't rewrite history. See
[Choosing a persona](tickets#choosing-a-persona). Older plans are folded under **Earlier plans**, read only, each
with its own Persona panel. The trail at the top leads back to the ticket.

A plan waiting on you that replaced one opens with its changes marked: the words added and removed since the plan
before, word by word, so formatting alone is no change. A paragraph, heading, or table cell that's new whole gets one
green block with a bar at its left, rather than confetti. A passage rewritten around a few words it happened to keep
reads as the old passage struck and the new one after it, since nobody learns anything from a green `the` surviving
between two strikeouts. An approved or replaced plan opens with the marks off. **Changes since plan N**, in the Plan
panel's header, turns them off and back on; while they're on, the header counts them, **Previous change** and **Next
change** step through them, round to the other end, and the comments' highlights step down to a thin underline so a
passage never wears two colors, but you can still see where your comments are. After asking for changes, that's how you
check you got them without reading the whole plan again.

The plans are compared section by section first, each heading paired with its namesake in the plan before, or with
the section most like it when the heading was renamed. So a section the planner moved wears a small **moved** at its
heading instead of being struck out in one place and pasted green in another, and one it dropped folds into a single
**Section removed** line where it used to be. Open that line to read what went; it was probably the part you liked.

**Outline**, at the right of the Plan panel's header, lists the plan's headings, each step indented under its
section, and goes to the one you pick, with the cursor in it if you can edit. Every plan has the same headings (Goal,
Acceptance, Context, and so on down to Risks), so after a few plans you'll know where Steps is without looking, and
the menu still saves you the scrolling. As it opens it marks the section you're reading, for when a long plan has lost
you.

On a ticket's newest plan, each `##` section in the outline ends in two marks: a check for read and fine, and a `!`
for read with a concern you mean to come back to. Pick one and the menu stays open, so you can mark a few on the way
down; pick it again to clear it. The button counts what you haven't marked (`Outline 3 left`, then `all read`) and
how many concerns you've left yourself, so a long plan tells you what's still to read. The marks are notes to you and
nobody else: they live in this browser, and the planner never hears of them. A concern you want the planner to act
on is a comment. A mark holds while its section reads as it did when you marked it, so when a new plan rewrites
Risks, Risks is unread again, and the sections the planner left alone keep their marks. That includes your own
edits: change a section's words and it wants reading again, which, to be fair, it does.

While a planner is writing, the editor is read only and says which run is writing. A plan that was replaced is read
only too. Before the first plan, the page says whether a run is writing one or the next tick dispatches a planner; for
a ticket that needs none, it says so and names `canopy plan KEY`. If a plan's file has gone missing or can't be read,
the page names the problem and the path instead of opening an empty editor, since an empty plan approved is the most
expensive kind.

## Diagrams

A code block fenced as `mermaid` is drawn as the diagram it describes: a flowchart, a sequence diagram, or a state
diagram, which covers how modules fit, which side calls which, and what a status may become. A picture of the call
order is quicker to check than three paragraphs about it, and quicker to catch being wrong. It's drawn in your theme's
colors, and again when you change them. One wider than the plan is narrowed to fit, but only so far: past three
quarters of its size its labels would be too small to read, so it scrolls sideways instead, its edge faded where
there's more. A twelve-step chain drawn left to right will make you scroll; that's the diagram's fault, not yours.

Planners draw one wherever the work has a shape: a plan that changes how two parts talk, adds a status, or reorders a
flow has at least one, usually in Context for how things stand and again under the step that changes them. They say
the same in prose, since the worker after them reads the code, not the picture, and they reach for a table the same
way, for the files a step changes or the risks beside their way back. A typo fix still gets none. An epic's plan of
three tickets or more opens its breakdown with the order they're built in, drawn.

The code is still the plan. **Source**, under the diagram, shows it; so does putting the cursor in it, which the arrow
keys do from the line above or below, and which is how you edit one, with the diagram redrawn under it as you stop
typing. A comment or a change marked in the code shows it too, since that's where those live. A diagram Mermaid can't
read, or one of a kind not drawn here, shows its code and, under it, `Not drawn:` and why.

A planner's diagram comes from the ticket's text like the rest of the plan, so it's drawn as a picture and nothing
more: its labels stay words, and nothing in it can run, click through, or load from anywhere. It can still be a
confident drawing of the wrong thing, and so can a whiteboard.

## Commenting

Select a passage and press **Comment**, in the bubble that appears or the toolbar, or Ctrl+Alt+M (⌘+Option+M on a Mac).
Write your comment and press **Comment** again, or your [send key](settings#replies). It takes the same Markdown a
[reply](attention#replying) does, and its card shows it formatted. Each comment is saved
as you make it, and sits in the **Comments** panel, quoting its passage. Click the quote to find it in the plan.

Under a new comment's field sit four labels: **Verify this**, **Out of scope**, **Match existing patterns**, and
**Needs tests**. One click starts the comment with a fixed instruction to the planner, worded as an order rather than
a suggestion. Hover a label to read its instruction first. The cursor lands after it, so add your own words or send it
as it is; another label swaps the instruction and keeps what you wrote. The wording is blunt on purpose: a planner
treats "maybe double-check this?" as optional, and it is right to, since that is what you said.

A comment's card says what it can do in words: **reply**, **edit**, **resolve** (or **reopen**), and **delete**,
which asks first. Comments hold onto
their passage by its words, so they survive your edits, and they belong to the ticket, so they carry over to the next
plan. A passage the planner only reworded keeps its open comments: a word swapped or a clause added, and the comment
finds it anyway, as long as most of its words and the text around them are still there. Its card then says
`passage reworded`, and hovering the chip shows the words you commented on: a comment that moved says so, rather than
vouch for words it never saw. When a new plan drops or rewrites a passage, its comments are marked `passage gone`, and
**resolve all** clears them in one go. A resolved comment only finds its passage word for word: it's done asking for
things, so it doesn't go looking. Resolved comments fold away under the open ones.

Escape drops a comment you haven't written anything in. One with words in it stays open until you **Cancel** it.

## Editing

The plan is yours to edit directly, like any document: the toolbar has headings, lists, task lists, quotes, code
blocks, and tables, and Markdown typed as you go (`## `, `- `, `**`) formats itself. Ctrl+S (⌘+S on a Mac) saves, and
**Save** does the same; the plan's foot says `Unsaved edits` until you do.

Every toolbar button names its shortcut on hover, as your keyboard spells it. On a Mac, read ⌘ for Ctrl and Option
for Alt:

- **Undo** Ctrl+Z and **Redo** Ctrl+Shift+Z.
- **Text** Ctrl+Alt+0, and **Heading 1** to **Heading 4** Ctrl+Alt+1 to Ctrl+Alt+4, in the style menu after Redo. A
  plan has two sizes of heading, as this guide does, so 1 and 2 look alike, and so do 3 and 4. The Markdown keeps
  them apart.
- **Bold** Ctrl+B, **Italic** Ctrl+I, **Strikethrough** Ctrl+Shift+S, and **Code** Ctrl+E.
- **Bulleted list** Ctrl+Shift+8, **Numbered list** Ctrl+Shift+7, **Task list** Ctrl+Shift+9, **Quote** Ctrl+Shift+B,
  and **Code block** Ctrl+Alt+C.
- **Comment** Ctrl+Alt+M, with a passage selected.

The **Table** menu has no keys. It inserts a table, and inside one adds or deletes rows and columns, or the table.

**Markdown**, in the Plan panel's header, swaps the document for the Markdown it's made of, as plain text you can
read or edit as written. It's for what a toolbar makes tedious: moving a section, fixing a table by hand, or seeing
exactly what the planner wrote. The toolbar, the outline, and the changes step aside while it's on, and the comments
sit in a plain list. Turn it off and the text is read back into the document, as one step of undo, and each comment
finds its passage again by its words. A passage you only touched up there keeps its open comments; one you rewrote is
`passage gone`, as it would be if you'd deleted it in the document and typed something new.

Leaving the page with edits not saved or a comment not sent asks first. And if the file changed since you opened it,
the save is refused rather than overwriting someone else's edit unseen.

## Approving, or asking for changes

The Plan panel's foot holds the decision, and sticks to the bottom of the window while you read, so a long plan is
decided from wherever you got to. **Approve** is always its main button; everything else steps back.

- **Approve**, or **Save and approve** with edits not yet saved, as `canopy plan KEY --approve`. It approves the plan
  as saved, your edits included, and the next tick can implement it. Editing an approved plan means approving it
  again, and until you do, the ticket's implement waits. Someone else editing the ticket holds nothing up: if its
  title or description changes after you approve, a `ticket_changed` item says which, and the plan's card, on that
  item and on the ticket's page, offers **Approve** again. Approving says the plan still fits the new words; or ask
  for a new plan, or skip it. Meanwhile the work goes ahead on the plan you approved, which is a fine way to build
  the wrong thing carefully. With open comments, an answered decision, or a note on the whole plan, it reads
  **Approve with notes**, as `canopy plan KEY --approve --message TEXT`: see below.
- **Ask for changes**, while the plan waits on you, sends the planner back with your open comments, your answers to
  its decisions, and an optional note on the whole plan, as one reply on the ticket. If you edited the plan yourself,
  the reply says so, and asks the planner to keep your edits. Resolved comments aren't sent. The reply's
  4000-character bound holds, so a long round of comments may need resolving or shortening first.
- **Skip the plan**, as `canopy plan KEY --skip`: the implement goes ahead with no plan. The current plan's file
  stays. Nothing on the page undoes it, so it asks first, right there in the foot; **Keep** (or Escape) backs out.

Not every comment deserves another plan. "Name the test after the bug" is a point for the worker, not a reason to
send the planner round again, so **Approve with notes** carries your open comments and the note on the whole plan to
the implement instead: one message on the ticket, written with the approval, each comment quoting its passage as Ask
for changes would. The implement reads it beside the plan, and where the two disagree, your notes win, being your later
word. The comments it sent are resolved, since the worker has them now and the planner never will. Resolve one first
to leave it out, which is also how you approve with none; and as with Ask for changes, a reply's bound holds, so a long
round may need trimming first.

A comment you already sent with **Ask for changes** stays open on the next plan, so you can check the planner's
answer against it, and its card reads `planner read`. Approve leaves those out: the plan is the answer, and sending
the question along to the worker too only gets it done twice. If the answer fell short, reply to the comment or edit
it, and it goes with the notes again.

Some of a plan is a question only you can answer. The planner writes each choice the ticket left open under
Decisions, as a question with lettered options and the one it went with marked `(chosen)`, and canopy asks it again
wherever you approve the plan: under the plan on this page, and on the plan's card. **Open decisions** is drawn just
as a worker's question is on its progress card: lettered options, the planner's marked `recommended` and picked. Pick
another and that's your answer: a line such as `Decision 1 (Where a schedule keeps its hour): take B, not A.` joins
your notes, so **Approve with notes** carries it to the implement, and **Ask for changes** to the planner. Leave the
planner's choice picked and nothing is sent; agreeing needs no paperwork, but it does get named: with decisions open
and no notes to send, the button reads **Approve as planned**, so you never take a planner's choice under a button
that only said Approve.

Since the panel sits under the plan's last line, the foot says it's there from the moment the page opens:
`↓ 2 open decisions` leads the line under the actions, and clicking it takes you to the panel. Once you've answered
some it reads `1 of 2 answered`, and it counts the plan as it reads now, so editing its Decisions changes the count.
It's a signpost, not a gate: **Approve as planned** works without a visit.

Your picks are kept in this browser until they're sent, not in the journal, so one made on the card is still picked
when you open the plan, and survives a reload. They belong to the plan they answered, and each holds only while its
decision reads as it did: a new plan starts clean, and so does a decision you or the planner reworded, since an
answer to a question that changed isn't one. A plan written before planners used this shape, or one that wanders from
it, shows no panel, and its Decisions are still there to read and comment on.

After you ask, a green band under the plan's title says "You asked for changes", and when, until the next planner
starts or you approve the plan after all; the ticket's Plan card carries the same band, and the plan's chip reads
`changes asked`. Until a planner picks it up, the button reads **Ask again**, so you never send a second request
without knowing about the first, and the line under it says it sends your open comments again. Once the plan is
approved, the foot has no Ask at all: a reply on the ticket then asks for no changes, it goes to the implement.

Approving is the moment an agent gets the go-ahead to write code, so the foot marks it: a check, the CLI's words on
the accent, a leaf, and a **Back to Attention** link for whatever is next. It shows only once the approval is in the
journal. A refused approval gets its refusal, and no leaf.
