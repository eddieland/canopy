# Settings

A handful of things you set from the browser: how the UI looks and sends, a notice for every worker, your limits and
trust settings, reloading your config, and the fun. It also shows, read only, which model each agent runs on. It opens
from the rail's foot, beside the guide. The theme, the clock, the send key, your review personas, and the fun are kept
in this browser; everything else canopy reads from its config files, as it always did.

## Theme

**Light**, **Dark**, or **System**, which follows your machine. Every open tab follows along. The button at the right
of the header flips it too.

Each theme also has a palette, picked apart. The defaults tint the canvas with the accent's hue: **Lavender** in light,
**Indigo** in dark. Light can also be **Off-white**, a warm paper, a soft green **Sage**, or the light side of
**Solarized**, **Nord**, **Gruvbox**, or **Rosé Pine** (its Dawn variant). Dark can be a plain **Grey**, a near
**Black** for an OLED screen, a deep green **Forest**, a wine-dark **Plum**, or the dark side of **Solarized**,
**Gruvbox**, or **Monokai**. Only the background, surfaces, and text change; every status color stays where you
learned it. Scheme purists will notice the bases sit a shade off the spec, so the status colors stay readable on them.
Nord's dark side didn't make it: moved far enough for that, it was Indigo with a different name. Rosé Pine's and
Dracula's dark sides missed out the same way.

## Time

How every time of day on the page reads: **24-hour** (`14:05`, the default) or **12-hour** (`2:05 PM`). **Show time
zone** puts the zone after each one, as your browser abbreviates it (`14:05 EDT`), which settles the question of whose
2 PM it was before anyone has to ask. The line above the switches shows the time now, as it will read. Every time
follows along, the ones you hover for included. Ages (`3m ago`) don't change; minutes are minutes everywhere.

## Replies

Which key sends what you write: **Enter**, **Ctrl+Enter** (⌘+Enter on a Mac), or **Button only**, if you've ever
sent half a sentence to a worker and would rather not again. It holds in every box you write in to send: a reply, a
note, a comment on a plan, the notes on a review request, a draft or a lesson in your words, and the notice to workers.
Shift+Enter always makes a new line. The key you pick shows on each send button.

## Reviews

The [personas](tickets#choosing-a-persona) a review you request on the
[reviews page](pull-requests#asking-for-a-review), or from a PR's page, is written in. Check one, say `skeptic`, and
both start with it checked; check several and each request gets a review in each. You can still pick others for one
request, and **Use the default** leaves it to `[personas] reviewer` in your config.

This is yours, not the loop's: it lives in this browser, your config doesn't set it, and the reviews canopy runs on
its own PRs never read it. A persona you prefer that canopy would refuse to run, or one whose file you've since
deleted, is named here and left out of each request rather than refused.

## Notice to workers

Tell every run dispatched from now on about something going on outside the work, such as a CI outage: "Artifactory is
down: CI builds that fetch dependencies will likely fail." Workers, reviews, and chores hear it, and the overseer holds
off sending a resume after a failure the notice explains. This is `canopy notice TEXT --for DURATION`.

Pick how long it lasts, **1 hour**, **4 hours**, or **1 day**, and press **Set notice**. It lapses on its own, and
setting another replaces it. While it's in force, a banner above every page shows it, with **Edit**, **Renew**, and
**Clear**: see [the banner](overview#the-header) for what each does.
A run already going keeps the prompt it started with, so a notice reaches only the runs after it. The CLI can set one
for up to a week, for outages with ambitions.

## Limits and trust

**Open** takes you to a page of its own for the numbers you change most: how many workers, chores, and reviews run at
once, each pool's slots, how many tries a ticket gets, how much you may attach to one, how often the loop ticks, and
the monthly budget the [spend page](reports#the-spend-page) tracks, with any alerts short of or past it. You can add and
drop alerts freely here: the 100% one isn't in the list, so dropping everything still leaves it. It also holds the
trust settings, which from here only get stricter: you can drop a trusted reviewer or an authorized replier, never add
one, and turn `trust.rebase` off but not on. A stolen session that could add a replier would keep steering your
workers after you changed the secret, so adding one stays an edit to the file.

Each row says where its value comes from and how far the page will take it. Counts stop at a ceiling (32 workers, 10
attempts, a $10,000 budget) and paces at a floor (a tick every 2 minutes); the file can still set anything, so the page
is for the changes you actually make, not for setting a record. Repositories get a count of their own only when you
pick one, so a workspace of fifty repositories shows the two that differ.

**Save** writes `.canopy/config.toml`, this workspace's own file, editing it in place so your comments and layout stay,
then reloads the loop as **Reload** below does. It never touches `canopy-workspace.toml` or
`~/.config/canopy/config.toml`; a value that came from the latter is copied into the workspace's file, where it wins for
this workspace alone. The file as it was is kept beside it as `config.toml.bak`, so undoing a save is a `mv` and a
Reload. If the file changed since the page read it, the save is refused rather than guessing which of you meant it.

## Models

Which model each agent runs on, as `[runtime.models]` chooses it: a row each for the worker (both workers, and a
task's runs), the planner, the reviewer, the overseer, and `chore`, which covers every chore without a model of its
own, then a row for each chore. Each row names the model and the variant it runs at, `provider/model@high` in the file,
or says `runtime default` when nothing sets one and the runtime picks, which is a choice, just not yours. A chore with
a `model` in its own table is marked **own model**; one whose command runs an agent of your own names that agent
instead, since its own definition chooses (see [chores](chores#setting-one-up)).

```toml
[runtime.models]
worker = "anthropic/claude-sonnet-4-5"
reviewer = "openai/gpt-5@high"
chore = "anthropic/claude-haiku-4-5"
```

The panel only reads. The line under it names the file to edit: the user file serves every workspace, and
`.canopy/config.toml` this one alone; the workspace file can't choose a model, since a model is what your spend buys
and which provider sees the code. It shows what the loop runs on, so an edit appears after **Reload**, and applies from
each agent's next run; a run already going keeps its model. One ticket's override is set on
[its page](tickets#choosing-a-model) and never shows here. **Show the runtime's models** lists what you can name, as
`canopy models` prints it, read only when you open it, since each read starts the runtime.

## Config

The loop reads your workspace's `canopy-workspace.toml` and your `config.toml` when it starts. **Reload** reads them
again, as `kill -HUP` on the loop does; a tick that's running finishes first. It says what changed, and which changes
wait for a restart. A file that doesn't load changes nothing, and the error names its file and key, so a typo costs you
a fix, not a loop. [Config files](config-files) lists every key.

## Fun

Sprig starts off and the rest starts on. None of it does anything useful, by design.

- **Ticker**: joke headlines crawling across the header, with a speed, a gap between headlines, and topics to pick
  from. **Tips** mixes real tips about canopy in with the jokes.
- **Sprig**: a small wire figure at the foot of the rail, with a tip for every page. None of them help. Click it for
  a new one, picked at random like the ticker's headlines, or **Don't show me tips again** to turn it off.
  **Ghost**, beside **Sprig** below the ticker's topics, puts a Destiny Ghost in its place: it floats where Sprig
  stands, with a tip for every page in a voice of its own, and helps exactly as much. The checkbox takes the name of
  whoever is sitting there. Sprig keeps the hats.
- **Quips**: a worker run's row in the rail says what it's doing as a quip, `planning in pencil`, instead of plain
  `planning`. Each ticket keeps its quip for a phase and gets a new one with the next, in every tab, so nothing
  changes its story while you watch. A run waiting on you gets the plain words; it isn't doing anything. Hover a
  quip for the plain words too.
- **The hat shop**: every dollar canopy spends is a dollar towards Sprig's hats. All sales are final.

The switch in the panel's header does exactly what you'd fear. Sprig, if it's on, brought glow sticks.

## Session

How long this browser stays signed in, and **Sign out**. [Signing in](signing-in) covers the secret and how to sign
every browser out at once.
