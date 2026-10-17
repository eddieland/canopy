# The web UI

Everything the loop is doing, on one screen, so you can stop tailing `canopy.log` and squinting. `canopy loop` serves
it at `http://127.0.0.1:8765/`, unless `serve.bind` or `serve.port` in your config says otherwise.

## The pages

The nav on the left lists them, most used first. If you learn only one, learn Attention.

- [Attention](/attention): what needs you, worst first, beside the selected item's conversation and a box to reply in.
  It's the home page.
- [Tickets](/tickets): every ticket canopy has worked on, and a form to start a new one.
- [Pull requests](/pull-requests): every PR canopy knows about, the ones it opened and the ones it reviewed, with their
  runs and reviews.
- [Reviews](/reviews): the PR reviews canopy kept to itself instead of posting, with their findings pinned to the diff.
- [Runs](/runs): the workers running now, then the ones that finished most recently, each with its session's
  transcript. When you want to know what an agent was thinking, this is the receipt.
- [Chores](/chores): the scheduled chores, their runs, and what they found.
- [Spend](/spend): what agent runs cost each day, and what idle ticks spent deciding there was nothing to do. Some of
  the priciest answers are "no".
- [Ticks](/ticks): the overseer's latest ticks, and what each one decided.
- [Worktrees](/worktrees): each repository's pool, its slots, and what's holding them.
- [Settings](/settings): the theme, the send key, the fun, and your session.

## The rail

The strip beside the nav, on every page. From the top: a search box over the whole journal (press `/` to jump to
it), the runs working right now, and what the last 24 hours and the last 30 days cost. Its foot names the version
canopy is serving, which links to canopy's releases on GitHub, and opens this guide.

## Acting from the UI

Where a page shows you something, it usually lets you act on it with the CLI's own verbs: reply, start and stop,
grant, dismiss, forget, pause and resume, send a notice to workers, and approve a plan. Each runs the same code as the
command, so the same guards hold. The browser is a second front door, not a back door. When a guard refuses, the UI
names it exactly as the CLI prints it, so a refusal means the same thing wherever you meet it.

The loop reads a reply at its next tick, not the moment you send it, and the conversation marks the reply as waiting
until then. Patience is a virtue; here it's also the architecture.

**Tick now**, beside Pause in the header, does what pressing `t` does at the loop's terminal: it cuts the loop's wait
short and starts the next tick at once, even while paused. It doesn't unpause anything; a pause stays a pause. While a
tick is running, the button waits for it to finish.

Everything else only reads the journal and changes nothing. Pages update as the loop writes, over a single stream,
so there's no need to reload. The worktrees are the one exception: reading them asks every pool, so that page rereads
them every 10 seconds while you're looking at it, and has a Read again button. While the stream is
connected, the dot in the logo beside `canopy` in the header breathes; while a tick runs, an arc sweeps its ring. If
the dot stops breathing, the page has stopped hearing from the loop.

## Signing in

The UI asks for the listener secret once, then keeps this browser signed in for 30 days. [Signing in](signing-in)
covers where the secret comes from and how to sign every browser out at once.
