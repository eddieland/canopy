# Plans

A plan is a worker's proposal for a ticket, written before any code: what it will change, where, and how it will
know it worked. You read it, comment on it, edit it, and approve it, and nothing is implemented until you do. It's the
cheapest code review you'll ever do, because there's no code yet.

## When a ticket gets a plan

A ticket needs a plan when `policy.plan` is `approve` in your config, or when you asked for one with `canopy plan KEY`
or `canopy start KEY --plan`. `canopy plan KEY --skip` waives it for one ticket. Until a plan is written, the ticket's
**Plan** card says `needed` or `not needed`, and hovering it says which of those applies.

The next tick then dispatches a `plan` run. It writes the plan as a Markdown file, and the ticket's phase becomes
`plan proposed`, which puts a `plan review` item on your attention list. Until you approve, the overseer can't start an
implement: the guard is `unplanned`, and no prompt gets around it.

A typo fix gets a plan too, if the policy says so. canopy once let a cheaper agent judge such work trivial and skip
its plan, and it judged so little trivial that it cost more than the plans it saved. So the judge is you: `--skip`
the ones you'd rather not read.

## Reading a plan

A plan has a page of its own, so it gets the whole width and its comments get a margin. The ticket's page has a
**Plan** card instead, at the top while the plan waits on you, and a `plan review` item in [Attention](attention)
shows the same card. It says where the plan stands (`waiting on you`, in amber like everything else that is, then
`approved` or `superseded`), which plan it is (`plan:2`), the run that wrote it and when, and how many comments are
open. **Approve** on the card approves it as its file stands, for when you've already read it; **Open plan** opens
its page, where the rest happens: comments, edits, asking for changes, skipping.

There, the plan opens in an editor. The page's title names the plan and its ticket, and the line under it says which
run wrote it, when you approved it and how, and whether its file was edited since. The **Plan** panel's header says
where it stands and how old it is. Older plans are folded under **Earlier plans**, read only. The trail at the top
leads back to the ticket.

A plan that replaced one opens with its changes marked: the words added and removed since the plan before, word by
word, so formatting alone is no change. A paragraph, heading, or table cell that's new whole gets one green block with
a bar at its left, rather than confetti. A passage rewritten around a few words it happened to keep reads as the old
passage struck and the new one after it, since nobody learns anything from a green `the` surviving between two
strikeouts. **Changes since plan N**, in the Plan panel's header, turns the marks off and
back on; while they're on, the header counts them, **Previous change** and **Next change** step through them, round
to the other end, and the comments' highlights step down to a thin underline so a passage never wears two colors,
but you can still see where your comments are. After asking for
changes, that's how you check you got them without reading the whole plan again.

The plans are compared section by section first, each heading paired with its namesake in the plan before, or with
the section most like it when the heading was renamed. So a section the planner moved wears a small **moved** at its
heading instead of being struck out in one place and pasted green in another, and one it dropped folds into a single
**Section removed** line where it used to be. Open that line to read what went; it was probably the part you liked.

**Outline**, at the right of the Plan panel's header, lists the plan's headings, each step indented under its
section, and goes to the one you pick, with the cursor in it if you can edit. Every plan has the same headings (Goal,
Acceptance, Context, and so on down to Risks), so after a few plans you'll know where Steps is without looking, and
the menu still saves you the scrolling. As it opens it marks the section you're reading, for when a long plan has lost
you.

While a planner is writing, the editor is read only and says which run is writing. A plan that was replaced is read
only too.

## Commenting

Select a passage and press **Comment**, in the bubble that appears or the toolbar, or Ctrl+Alt+M (⌘+Option+M on a
Mac). Write your comment and press **Comment** again, or your send key. Each comment is saved as you make it, and sits
in the **Comments** panel, quoting its passage. Click the quote to find it in the plan.

A comment's card says what it can do in words: **reply**, **edit**, **resolve** (or **reopen**), and **delete**,
which asks first. Comments hold onto
their passage by its words, so they survive your edits, and they belong to the ticket, so they carry over to the next
plan. When a new plan drops a passage, its comments are marked `passage gone`, and **resolve all** clears them in one
go. Resolved comments fold away under the open ones.

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
finds its passage again by its words. A passage you rewrote there is `passage gone`, as it would be if you'd rewritten
it in the document.

Leaving the page with edits not saved or a comment not sent asks first. And if the file changed since you opened it,
the save is refused rather than overwriting someone else's edit unseen.

## Approving, or asking for changes

The Plan panel's foot holds the decision, and sticks to the bottom of the window while you read, so a long plan is
decided from wherever you got to. **Approve** is always its main button; everything else steps back.

- **Approve**, or **Save and approve** with edits not yet saved, as `canopy plan KEY --approve`. It approves the plan
  as saved, your edits included, and the next tick can implement it. Editing an approved plan means approving it
  again, and until you do, the ticket's implement waits.
- **Ask for changes** sends the planner back with your open comments, and an optional note on the whole plan, as one
  reply on the ticket. If you edited the plan yourself, the reply says so, and asks the planner to keep your edits.
  Resolved comments aren't sent. The reply's 4000-character bound holds, so a long round of comments may need
  resolving or shortening first.
- **Skip the plan**, as `canopy plan KEY --skip`: the implement goes ahead with no plan. The current plan's file
  stays. Nothing on the page undoes it, so it asks first, right there in the foot; **Keep** (or Escape) backs out.

Approving doesn't send open comments. The implement reads the plan alone, so a comment left open is a comment nobody
acts on. While any are open, the line under the buttons counts them and says so, every time, until you resolve them
or send them.
The note on the whole plan travels the same way: only with Ask for changes. Press Approve with words in it and the
foot asks whether to approve without them, rather than quietly throw away what you wrote.

After you ask, a green band under the plan's title says "You asked for changes", and when, until the next planner
starts or you approve the plan after all; the ticket's Plan card carries the same band, and the plan's chip reads
`changes asked`. A reply once the plan is approved asks for no changes: it goes to the implement. The button reads
**Ask again**, so you never send a second request without knowing about the first.

Approving is the moment an agent gets the go-ahead to write code, so the foot marks it: a check, the CLI's words on
the accent, a leaf, and a **Back to Attention** link for whatever is next. It shows only once the approval is in the
journal. A refused approval gets its refusal, and no leaf.
