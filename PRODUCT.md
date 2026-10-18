# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is the operator: one developer who runs several coding agents at once. canopy runs on their own
machine, under their own credentials. They label tickets, answer the agents' questions, and review the PRs that come
back. The web UI stays open all day in a tab or on a second monitor. Mostly the operator glances at it to see what
needs them, then spends a short burst reading a ticket's conversation and answering it. They live in the dark theme.

The next audience is coworkers who install canopy in five steps and run their own instance, each for themselves.
There are no team, shared, or multi-user views. Design for the operator first. A coworker's first run matters, but it
never outweighs the daily operator.

## Product Purpose

canopy is an unattended agent loop that runs locally and is driven by the issue tracker. The operator labels a
ticket. When there is capacity, an overseer agent leases a worktree from a treehouse pool and dispatches a worker,
which pushes a branch and opens a PR. Later ticks pick up CI failures and review comments. The web UI, served by
`canopy loop`, is the operator's daily surface (DESIGN §22). It shows the attention list (what actually needs a
human), the runs, the worktrees, every ticket's conversation, canopy's reviews with findings on the diff, the chores,
and a search over the whole journal.

Success means the operator sees at a glance whether anything needs them, and acts on it without a terminal: answer,
grant, stop, reply. Everything that doesn't need them stays quiet. It also means the work is a little fun. Shepherding
thousands of tickets through agents is drudgery by default, and canopy should make it more enjoyable to do, not just
faster.

## Positioning

- Runs entirely on the operator's machine, where their credentials and internal systems already are. No hosted
  service holds standing write access to their code or tracker.
- Orchestration is a prompt, not a workflow engine. The overseer decides from live state each tick.
- One attention list of what truly needs a human, built from a journal that records every ticket's conversation.
- Humans approve and merge. The loop never does.

## Operating Context

- `canopy loop` runs in the foreground, often in tmux. It ticks on an interval and serves the UI on loopback
  (`127.0.0.1:8765`), behind a listener secret (TRUST_MODEL T8).
- The UI sits beside the operator's editor, GitHub, and tracker (Jira or GitHub Issues). Links out to those are
  routine.
- Notifications (desktop, Slack) bring the operator back to the UI when the attention list changes.
- Every UI write is the same server function as a CLI verb (`reply`, `grant`, `start`, `stop`, `forget`, `pause`). A
  refusal names its guard as the CLI does.

## Capabilities and Constraints

- Routes today: attention, runs, ticks, tickets, pull requests, reviews, worktrees, chores, search, settings.
- Terminology is fixed by the docs and code. Ticket, run, tick, worktree/slot, overseer, worker, attention item, chore,
  review, finding, grant, guard, journal. Run kinds are implement, resume, split, and plan; older runs may be fix-ci.
  Attention reasons include `needs_human`, `green_unreviewed`, `untrusted_review`, and `attempt_limit`. Use these words;
  don't invent synonyms.
- Local only. No requests to another origin at run time: no CDN fonts, analytics, or remote images.
- Journal content (tracker comments, agent output) is untrusted and is rendered as text, never as HTML.
- A running worker's events are known only once it ends; live data arrives over the server's event stream.
- No pages or features beyond what a ROADMAP milestone lists. Prompting a running session waits on M15.
- The stack and engineering rules are in `ui/AGENTS.md`. The visual system is `ui/DESIGN.md`, which is normative.

## Brand Commitments

- The name is lowercase: canopy.
- Voice: plain, direct, factual. Say what an action did in the CLI's words (`src/lib/outcomes.ts`). No marketing
  tone in the product.
- canopy should be a little fun to use. This is a goal, not a garnish: the operator manages a huge volume of tasks,
  and the product should lighten that. Play shows up in the details: the section colors, the header ticker's flair,
  the words, moments of small reward when work clears. Today's instances are in `ui/DESIGN.md`. The limit is that
  fun never hides or fakes state, never slows an action, and never gets in the way of reading what needs the
  operator.

## Evidence on Hand

- A mock journal of a three-repository workspace (`src/canopy/serve/mock.py`, run with
  `python -m canopy.serve --mock`), with times fixed around 2026-10-08.
- Playwright screenshot baselines for every route in both themes (`ui/e2e/screenshots.spec.ts-snapshots/`). The README
  shows the dark Attention, ticket, run, review, and tick pages.
- Style directions weighed earlier: `docs/ui-explorations/2026-10-08-style/`.
- Absences not to fabricate: no users beyond the operator yet, no testimonials, no metrics, no hosted offering, no
  pricing. canopy is pre-alpha, MIT-licensed, and unsupported.

## Product Principles

1. Quiet unless it needs you. The attention list is the product; everything else supports reading and answering it.
2. The operator stays in control. Hard guards are in code, humans merge, and every action is a CLI verb with the same
   refusals.
3. Facts come from their source. Show what the tracker, GitHub, and the journal say, with links to them, rather than
   restating it.
4. Local and trustworthy. Nothing leaves the machine, and untrusted text stays text.
5. One record. A ticket's whole conversation, runs, and reviews read as one story.
6. A little fun. Managing thousands of tasks shouldn't feel like a chore. Look for places to add delight, as long as
   it stays clear and never costs the operator time.
