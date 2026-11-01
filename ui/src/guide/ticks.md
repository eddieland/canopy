# Ticks

What the overseer decided each tick, and why. When the loop does something you didn't expect, a tick's page is where
you find out what it was thinking. What the ticks cost is on [the spend page](reports#the-spend-page).

## The ticks page

**Ticks**, under [Workspace](/workspace), lists the latest 50 ticks, newest first: each one's status, how many decisions
it recorded, what its overseer cost in dollars, tokens, and peak context, and its summary. A `dry run` chip marks a tick
from `canopy tick --dry-run`, which plans and dispatches nothing. Before the first tick, the page says when one comes:
after `loop.interval_minutes`, or now, with **Tick now** right there in the sentence. **idle**, in the panel's header,
keeps the latest 50 [idle ticks](#idle-ticks) instead, the ones the loop ran and found nothing to start.

A tick reads `running` while it works, and ends:

- `ok`, the usual. Its summary starts `no overseer, nothing left to judge` when canopy's own decisions left the
  overseer nothing, so it didn't run and cost nothing (see [How the loop works](how-the-loop-works#ticks));
- `skipped`, only on a tick from before canopy read the tracker for the overseer, when it couldn't see the world.
  These days a source that's down is `connector_failed` on the attention list, and the overseer never notices;
- `overseer failed`, when the overseer didn't finish its job, such as deciding about every ticket;
- `canopy unavailable`, when the overseer couldn't run canopy at all, so nothing was decided;
- `disk low`, when the disk had less free than `loop.min_free_disk_mib`, 2 GiB by default, so the overseer didn't run
  and started nothing;
- `model missing`, when OpenCode doesn't list the model `runtime.models` chose for the overseer, and `model list
  failed`, when canopy couldn't read OpenCode's list to check. Either way the overseer didn't run rather than run on a
  model nobody chose, and the attention list says which;
- `reconcile failed`, when tidying up after the last tick went wrong;
- `error`, when something in canopy itself broke during the tick; its summary names what, such as a full disk;
- `abandoned`, when its process went away without closing it, and the next tick closed it for it.

## A tick's page

The line under the title says how the tick ended, how many decisions it recorded, and what woke it: the timer, your
reply, a run ending, **Tick now**, and so on. The **Tick** panel leads with its summary, then, while the tick runs, its
overseer's **last call**: the tool it called last, what the call did, and how long ago, as a running run's page shows
its worker's. Then when it ran and for how long, what it spent, the model its overseer ran on, the one
`runtime.models.overseer` asked for until its session is read, and the version of canopy that ran it, laid out as a
run's page is. The version is the one to check when a decision looks like the work of a release you thought you'd
upgraded past.

The buttons at the right of the title step to the tick before and after this one, dry runs included, so the ticks
around an old one are a click away rather than an edit to the URL. At either end the button stays, greyed out; on the
newest tick, the next one's button comes alive when the next tick starts. For the latest tick itself, the header's
readout is the shortcut.

**Decisions** lists what the overseer decided, in the order it decided, each with its subject, its action, and the
overseer's reasons in its own words. A `refused` action, in red, names the [guard](how-the-loop-works#guards) that held
it back; an `attention` action, in amber, is an item it put on your list. When you want to know why a ticket sat still,
its refusals are usually the answer.

Under them are the overseer's session, as a run's [Transcript](runs#a-runs-page) shows it, its session id in the
header; the **Prompt** canopy started it with, folded as a run's is; and its raw **Output**, stdout then stderr, under
the path of its file, opened with **Show output**. The transcript and the output fill in while the tick runs, so a
tick that seems stuck can be watched being stuck. A tick that kept no output file has no Output panel; the
transcript's header says why, once. **Pretty** lays each event out on its own lines. The output opens at its end,
where the errors are, since that's usually why you're reading it.

A tick keeps those files for 7 days by default, and one that didn't close `ok` keeps them as long as a run does, 30,
since those are the ones you come back to debug. After that your `[retention]` removes them, and the page says
`removed after 7 days` where they were; the decisions stay forever.

## Idle ticks

A tick is idle when it started no work: it closed ok, dispatched no worker, review, or chore, and nothing reached the
journal since the tick before: no run ending, no poll finding something new, and nothing from you. Waits, refusals,
a ticket marked done, or a new attention item don't count. The loop waits longer after each idle tick, so a quiet day
costs little, but a tick that starts nothing still pays for the overseer to read everything. The share of the
overseer's spend that went on idle ticks heads the spend page's **Ticks** panel, whose link opens them here. If it's
high, a longer `loop.idle_max_minutes` is the knob.
