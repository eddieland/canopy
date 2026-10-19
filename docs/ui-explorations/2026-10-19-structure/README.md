# UI structure exploration, 2026-10-19

Rounds three and four of the exploration that `../2026-10-08-style/` began. That one varied the look of a single
Attention screen and picked E, the ops inbox. Ten days later the UI had grown far past what E drew, and the operator
liked it less each day, so this one varies the amount as well as the look. It is a record of ideas, not normative:
`ui/DESIGN.md` still governs the UI until it is changed.

Open `redrawn.html` in a browser from a checkout: its "Where we are" board shows the screenshot baselines in
`ui/e2e/screenshots.spec.ts-snapshots/`, which were taken at 8db8772 for this round and change with the UI. Fonts
come from Google Fonts, which the real UI may not use. It was published as a claude.ai artifact
(<https://claude.ai/artifact/JjGFDofKE2qq6CWWTfA6rX>, private to the operator), where its keep, maybe and drop marks
are saved; opened from the repository, the marks are disabled. Edit it by hand from now on. Its lines are not wrapped.

Every direction draws the same three screens with the same content, after the mock journal: the inbox with ABC-102's
question open, ABC-102's ticket page, and run 39. The times are made consistent and the spend breakdown is invented.

## Outcome

**Mailroom, as drawn** goes forward: the three-pane layout in Geist and neutral grey, not in today's tokens. Ledger and
Briefing were dropped. Direction 1 was a maybe, noted as much cleaner than the current app, which says the amount was
much of the problem.

## Why the UI felt heavier

Measured at 8db8772 against #107, which adopted E:

| | When E was adopted | 2026-10-18 |
|---|---|---|
| `ui/DESIGN.md` | 111 lines | 1,339 lines |
| UI source files, tests not counted | 49 | 228 |
| Route files | 8 | 25 |
| Nav | 4 tabs, as E drew it | 10 sections, Settings and the guide in the rail |

341 commits touched `ui/` in those ten days. The diagnosis drawn from today's screens:

- Nothing leads. Every block is a panel with the same hairline and uppercase label, so a worker's question and a
  session id get the same weight.
- The nav follows the journal's tables (runs, ticks, worktrees, chores, spend, memory), not the operator's day, which
  is spent in tickets.
- Answering is a text box in a corner, and reading a ticket means stitching Conversation, Runs and Decisions back
  into one story.
- Eleven section hues, an aurora and the ticker's flair compete with the five status colors that carry meaning.

## Round 3: four directions

Each entry gives the board, then its idea and the operator's mark.

- **1 · Ops inbox, kept.** E as picked, with everything added since removed: four tabs, four counters, the list beside
  the thread, today's palette and type. Isolates the amount from the look. *Maybe:* "much cleaner than the current
  app".
- **2 · Mailroom.** Round one's calm inbox taken further: mailboxes, a message list, and the open thread with its
  composer. Runs, ticks and notes are small lines in the thread, so a ticket reads as one story; the machinery (ticks,
  worktrees, memory, settings) is a line at the foot. Geist and Geist Mono, neutral grey, an indigo accent. *Keep.*
- **3 · Ledger.** Round two's F, all monospace, a ticket as one log, amber for what waits on the operator. *Drop.*
- **4 · Briefing.** Round one's B for its structure: a headline sentence counting what needs the operator, the answer
  box in the page, workers' words in a serif. *Drop.*

## Round 4: Mailroom, two ways

Mailroom's layout drawn as round three drew it and in today's tokens and IBM Plex, on eight screens: the three above,
and a PR with the replies a worker drafted for it, a review with its findings on the diff, memory's proposals, a
chore, and the empty inbox. *Keep, as drawn.*

What the new screens propose:

- A PR's life lands in its ticket's thread: canopy's review, coworkers' comments, and the drafted replies (DESIGN §29),
  drawn as outgoing mail to edit, drop, or send together.
- A review is a message with its findings attached, each on its diff, ticked and sent to a worker.
- Memory shows one proposal at a time with Promote, Edit first and Reject; Forget moves to small print.
- A chore is a thread of its runs, with its findings as messages that start a ticket.
- The empty inbox says so, and the thread pane becomes a digest of what happened meanwhile.

### Mailroom's palette

| Role | Dark | Light |
|---|---|---|
| mailboxes (background) | `#0f0f11` | `#f4f4f5` |
| list and thread (surface) | `#17171a` | `#ffffff` |
| surface-raised | `#222226` | `#f0f0f3` |
| border | `#2a2a30` | `#e4e4e8` |
| foreground | `#f2f2f4` | `#18181b` |
| body text | `#d4d4d8` | `#27272a` |
| muted-foreground | `#8d8d97` | `#6b6b76` |
| accent | `#8f90ff` | `#4f46e5` |
| status-running | `#3fcf8e` | `#15803d` |
| status-blocked (waiting) | `#f5b544` | `#a16207` |
| status-failed | `#f87171` | `#b91c1c` |
| review | `#5ccfe6` | `#0e7490` |

Chosen by eye and not checked for contrast. Radii are 8 to 16px, larger than today's; bubbles and chips tint their
state color at about 15% alpha.

## If Mailroom is adopted

These need decisions, not just new tokens:

- **Tokens.** The palette above, in oklch, held to 4.5:1 by `tokens.test.ts`; body text separate from foreground, and
  a review color.
- **Typeface.** Geist and Geist Mono replace IBM Plex, from `@fontsource`.
- **Shell.** Three panes replace the header, the rail and the page column. The nav becomes mailboxes (Needs you,
  Working, Waiting on others, All tickets, Done), a short list for the loop (Runs, Reviews, Chores, Spend), and a foot
  for the rest.
- **The ticket is its thread.** Conversation, Runs and Decisions merge into one timeline, with a details drawer for
  the facts; a run and a review open from their lines in it. Busy tickets may need runs and ticks folded to a line.
- **Identity color goes.** Section colors, the aurora and the ticker leave, and the Fun rules in `ui/DESIGN.md` change
  with them.
- **Docs.** The direction in `ui/DESIGN.md` is rewritten in the same PR, and the guide where a page changes.
