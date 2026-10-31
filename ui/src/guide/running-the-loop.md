# Running the loop

How to start canopy's loop and keep it running on your machine, check on it, stop it, and tidy up after it. What a
tick does once it runs is [How the loop works](how-the-loop-works#ticks).

## Starting it

Run `canopy loop` in your workspace. It ticks, waits, and ticks again until you stop it, and serves this UI while it
runs. Before trusting it with real work, try `canopy loop --dry-run --ticks 1`: one tick where the overseer plans and
nothing is dispatched.

- `--dry-run` makes every tick a dry run.
- `--every MINUTES` waits that long after each tick instead of `loop.interval_minutes`, but never less than
  `loop.min_gap_minutes`. A config reload keeps it.
- `--ticks N` stops after N ticks.
- `--defer MINUTES` waits that long before the first tick.
- `--no-serve` serves no web UI, whatever `serve.enabled` says.

One loop per workspace: a second one refuses, since two would run the overseer twice as often and charge you for both.

## At the terminal

While the loop waits between ticks, it reads two keys, no Enter needed:

- `t` ticks now, as **Tick now** in [the header](overview#the-header) does, even while paused.
- `p` pauses the loop, and pressed again resumes it. Keys pressed during a tick are dropped, all but `p`, which holds
  the next one.

Ctrl-C stops the loop: at once during the wait, or once the running tick ends. It then waits for the runs still
running to end, and keeps serving the UI so you can watch them go. A second Ctrl-C aborts the tick, whose row the next
tick closes as `abandoned`, or stops the wait and leaves the runs running.

Close the terminal and the loop ends with it, right away. Under tmux, or as a daemon, it doesn't.

## In the background

`canopy daemon start` runs the same loop detached from your terminal. Loop options go after it, as in
`canopy daemon start --dry-run`. It waits until the loop has started and prints its pid; a loop that dies on the way
up, over a config error say, has its last words printed instead.

- `canopy daemon status` says whether it runs, its pid, since when, and where its output goes. It exits 0 while the
  daemon runs and 1 otherwise, and it also tells you when a loop you started in the foreground holds the workspace.
- `canopy daemon stop` stops it at once during its wait, or once its running tick ends. It refuses while runs are
  running; `canopy daemon stop --wait` ticks no more and stops once every run has ended.

Nothing installs the daemon with your OS. It doesn't start at login and nothing restarts it if it dies, so after a
reboot, start it again. `canopy daemon status` says when it exited without being told to. `daemon start`,
`daemon stop`, `pause`, and `resume` all refuse inside canopy's own ticks and runs: an agent doesn't get to decide the
loop should take the afternoon off.

## Workers outlive the loop

Stopping the loop never stops a run. Workers, reviews, chores, and tasks are their own processes and keep going, and
each writes how it ended when it ends. The next tick, from whichever loop, sees a run still going and lets it be, and
marks one whose process is gone. To stop a run, stop its ticket; [Stopping a run](runs#stopping-a-run) says how.

That's why `daemon stop` refuses while runs are running. A canopy that changes the journal, as an upgrade can, won't
start while runs from the canopy before it are still working, so a loop you stop to upgrade couldn't start again until
they end. Stop with `--wait`, or Ctrl-C and let it wait, and the upgrade goes in cleanly.

## Checking on it

The header's tick readout says when the last tick ran, and the logo stops breathing when the page stops hearing from
the loop. Without a browser, `canopy status` prints the last tick, whether the loop is paused, the attention list,
and what's running.

The loop logs to `.canopy/canopy.log` in the workspace, one JSON object a line with its time (`ts`), `level`, `msg`,
and `tick_id`, which is null outside a tick. Every canopy process writes there, the commands the overseer and workers
run included, so one filter pulls out everything a tick did:

```sh
jq -c 'select(.tick_id == 12)' .canopy/canopy.log
```

Its `loop started` line names the loop's pid. A live tick rotates the log past `retention.log_max_mib`, 50 MiB, to
`canopy.log.1`, the newest, keeping `retention.log_keep`, three. The overseer's own output for each tick is on
[the tick's page](ticks#a-ticks-page).

The daemon writes what it would have printed to `.canopy/daemon.log`, a line for each event: a tick, each decision
that changes something, the attention list changing, a poll, a pause. canopy appends to it and never rotates it, so it
grows until you empty it (`: > .canopy/daemon.log` is safe while it runs).

## One tick by hand

`canopy tick` runs one tick and prints how it ended and what it cost. `canopy tick --dry-run` runs the overseer and
dispatches nothing, and `canopy decisions` then prints what it decided. That's the cheapest way to find out what the
loop would do without letting it. A hand tick fits between a running loop's ticks; while a tick or a poll holds the
lock, yours says `lock_busy` and does nothing.

## Pausing

`canopy pause` stops the loop starting ticks, and `canopy resume` lets it start again, at once if its wait has run
out. They're the header's **Pause** and **Resume**, and `p` at the terminal. A tick already running finishes, and every
worker carries on. While paused, the loop doesn't poll your tracker either, but `t`, **Tick now**, and a hand
`canopy tick` still run one. The pause lives in the journal, so it outlives a restart: if a fresh loop sits there doing
nothing, check you didn't leave it paused last night.

## Reloading the config

The loop reads its config when it starts. `kill -HUP` on its pid, or **Reload** in [Settings](settings#config), reads
it again; a tick that's running finishes on the config it started with. A config that doesn't load leaves the loop on
the one it had and says why. Changes to `serve.*` wait for a restart, since the web server starts once, with the loop.
[Config files](config-files) has the keys.

## Garbage collection

canopy cleans up after itself on live ticks. At most once a day a tick runs the pass, which removes a run's log,
prompt, and diff after `retention.run_files_days`, 30; a tick's after `retention.tick_files_days`, 7, or as long as a
run's for one that didn't close `ok`; and the journal's routine rows, such as connector runs, after
`retention.journal_days`, 90. Set `[retention]` in your own config, not the workspace file, and `0` keeps that kind
forever. A dry tick never runs the pass, and a pass that fails leaves the tick to carry on: a full disk is when you
need it most.

The pass never removes the record of what happened: ticks, decisions, runs, messages, and anything a guard counts stay
for good. Nor does it delete a branch.

`canopy gc` takes exactly one of:

- `--dry-run`: what canopy keeps, what the next pass would remove, and the remote branches canopy made that nothing
  uses any more, for you to delete. `--json` prints it as JSON.
- `--vacuum`: gives the journal's free pages back to the disk, while no tick or run is going and there's room for a
  copy of the journal.
- `--git`: packs each primary clone's loose objects and small packs, pruning nothing, skipping a repository while a
  slot of its pool is leased.
- `--caches`: empties each sandbox role's cache that no live run is using.
