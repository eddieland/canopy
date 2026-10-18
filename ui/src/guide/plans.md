# Plans

A plan is a worker's proposal for a ticket, written before any code: what it will change, where, and how it will
know it worked. You read it, comment on it, edit it, and approve it, and nothing is implemented until you do. It's the
cheapest code review you'll ever do, because there's no code yet.

## When a ticket gets a plan

A ticket needs a plan when `policy.plan` is `approve` in your config, or when you asked for one with `canopy plan KEY`
or `canopy start KEY --plan`. `canopy plan KEY --skip` waives it for one ticket. The plan's page says which applies:
"Plan needed, by policy.plan approve", or "by your word".

The next tick then dispatches a `plan` run. It writes the plan as a Markdown file, and the ticket's phase becomes
`plan proposed`, which puts a `plan review` item on your attention list. Until you approve, the overseer can't start an
implement: the guard is `unplanned`, and no prompt gets around it.

## Reading a plan

A plan has a page of its own, so it gets the whole width and its comments get a margin. The ticket's page has a
**Plan** card instead, at the top while the plan waits on you: where the plan stands (`needed`, `proposed`,
`approved`, `superseded`), which plan it is (`plan:2`), the run that wrote it and when, and how many comments are
open. **Open plan** on the card, or on a `plan review` item in [Attention](attention), opens the plan's page. The card
only reads; deciding happens on the plan's page, where you can see what you're deciding.

There, the plan opens in an editor. The line above it says which plan this is, when it was written, and whether it was
edited since the planner wrote it. Older plans are folded under **Earlier plans**, read only. The trail at the top
leads back to the ticket.

A plan that replaced one opens with its changes marked: the words added and removed since the plan before, word by
word, so formatting alone is no change. The bar at the foot counts them, and **Previous change** and **Next change**
step through them, round to the other end. After asking for changes, that's how you check you got them without
reading the whole plan again. **Changes since plan N** turns the marks off, and back on.

While a planner is writing, the editor is read only and says which run is writing. A plan that was replaced is read
only too.

## Commenting

Select a passage and press **Comment**, in the bubble that appears or the toolbar, or Ctrl+Alt+M (⌘+Option+M on a
Mac). Write your comment and press **Comment** again, or your send key. Each comment is saved as you make it, and sits
in the **Comments** panel, quoting its passage. Click the quote to find it in the plan.

A comment can be replied to, edited, resolved, reopened, or deleted, and deleting one asks first. Comments hold onto
their passage by its words, so they survive your edits, and they belong to the ticket, so they carry over to the next
plan. When a new plan drops a passage, its comments are marked `passage gone`, and **Resolve all** clears them in one
go. Resolved comments fold away under the open ones.

Escape drops a comment you haven't written anything in. One with words in it stays open until you **Cancel** it.

## Editing

The plan is yours to edit directly, like any document: the toolbar has headings, lists, task lists, quotes, code
blocks, and tables, and Markdown typed as you go (`## `, `- `, `**`) formats itself. Ctrl+S (⌘+S on a Mac) saves, and
**Save** does the same; the bar says `Unsaved edits` until you do.

Leaving the page with edits not saved or a comment not sent asks first. And if the file changed since you opened it,
the save is refused rather than overwriting someone else's edit unseen.

## Approving, or asking for changes

The bar at the foot holds the decision.

- **Approve**, or **Save and approve** with edits not yet saved, as `canopy plan KEY --approve`. It approves the plan
  as saved, your edits included, and the next tick can implement it. Editing an approved plan means approving it
  again, and until you do, the ticket's implement waits.
- **Ask for changes** sends the planner back with your open comments, and an optional note on the whole plan, as one
  reply on the ticket. If you edited the plan yourself, the reply says so, and asks the planner to keep your edits.
  Resolved comments aren't sent. The reply's 4000-character bound holds, so a long round of comments may need
  resolving or shortening first.
- **Skip the plan**, as `canopy plan KEY --skip`: the implement goes ahead with no plan. The current plan's file
  stays.

Approving doesn't send open comments. The implement reads the plan alone, so a comment left open is a comment nobody
acts on. While any are open, **Ask for changes** is the main button and **Approve** steps back, and the note under the
bar counts them.

After you ask, the plan's page says "You asked for changes" until the next planner starts, and the button reads
**Ask again**, so you never send a second request without knowing about the first.
