# The web UI

What each page of the web UI holds, and how to act on what it shows. `canopy loop` serves it, at
`http://127.0.0.1:8765/` unless `serve.bind` or `serve.port` says otherwise.

## The pages

The nav on the left lists them, most used first:

- [Attention](/attention): what needs you, most severe first, beside the selected item's conversation and a reply form.
  It is the home page.
- [Tickets](/tickets): every ticket canopy has worked, and a form to start one.
- [Pull requests](/pull-requests): every PR canopy knows, the loop's own and the ones it reviewed, with their runs and
  reviews.
- [Reviews](/reviews): the PR reviews canopy keeps instead of posting, with their findings on the diff.
- [Runs](/runs): the workers running now, then the ones that ended last, each with its session's transcript.
- [Chores](/chores): the scheduled chores, their runs, and their findings.
- [Spend](/spend): what agent runs cost each day, and what idle ticks spent for nothing.
- [Ticks](/ticks): the overseer's latest ticks, and what each decided.
- [Worktrees](/worktrees): each repository's pool, its slots, and what holds them.
- [Settings](/settings): the theme, the send key, the fun, and the session.

## The rail

Beside the nav, on every page: a search box over the whole journal (press `/` to reach it), the runs working now, and
what the last 24 hours and the last 30 days cost. Its foot names the version canopy serves and opens this guide.

## Acting from the UI

The UI takes the CLI's verbs where their subject is shown: a reply, start and stop, grant, dismiss, forget, pause and
resume, a notice to workers, and approving a plan. Each goes through the same code as the command, so the same guards
hold: a refusal names its guard as the CLI prints it. A reply reaches the loop's decisions at the next tick, and the
conversation marks it as waiting until then.

Everything else a page shows only reads the journal. Nothing in the browser polls: the pages change as the loop writes,
over one stream. While it is connected, the dot in the logo beside `canopy` in the header breathes; while a tick runs,
an arc sweeps its ring.

## Signing in

The UI asks once for the listener secret, and then keeps this browser signed in for 30 days. [Signing in](signing-in)
says where the secret comes from and how to sign every browser out.
