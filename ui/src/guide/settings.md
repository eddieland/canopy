# Settings

A handful of things you set from the browser: how the UI looks and sends, a notice for every worker, your limits and
trust settings, reloading your config, and the fun. It also shows, read only, which model each agent runs on and the
skills the runtime finds. It opens from the rail's foot, beside the guide. The theme, the clock, the send key, whether
attention lists chore findings, your review personas, and the fun are kept in this browser; everything else canopy reads
from its config files, as it always did.

## Theme

**Light**, **Dark**, or **System**, which follows your machine. Every open tab follows along. The button at the right
of the header flips it too, and hovering it offers the palettes of the theme you're looking at, so you can try a few
without leaving the page. The card stays put while you click through them; the other theme's are here.

Each theme also has a palette, picked apart. The defaults tint the canvas with the accent's hue: **Lavender** in light,
**Indigo** in dark. Light can also be **Off-white**, a warm paper, a soft green **Sage**, or the light side of
**Solarized**, **Nord**, **Gruvbox**, or **Rosé Pine** (its Dawn variant). Dark can be a plain **Grey**, a near
**Black** for an OLED screen, a deep green **Forest**, a wine-dark **Plum**, or the dark side of **Solarized**,
**Gruvbox**, or **Monokai**. The background, surfaces, text, and accent change. Schemes with an accent bring it:
Nord and Solarized their blues, Monokai its hot pink, Rosé Pine its dusty one, Gruvbox its purple, since its orange
looked like every run was blocked. The rest get one that suits them: ink blue on Off-white, heather on Sage and
in the Forest alike, steel blue on Grey, ultraviolet on Black, and orchid on Plum. Neither green one gets a green
accent, for the same reason Gruvbox lost its orange, and the Forest gave up its lake blue, which kept passing for a
ticket. Every status color stays where you learned it. Scheme purists
will notice the bases and accents sit a shade off the spec, so everything stays readable on them.
Nord's dark side didn't make it: moved far enough for that, it was Indigo with a different name. Rosé Pine's and
Dracula's dark sides missed out the same way.

A few palettes bring more than color. Dark **Gruvbox** has the crisp corners of an editor from the nineties, sets every
line in monospace as one would, and menus and cards cast a hard shadow with no blur. **Black** drops the panels'
outlines, since a step of lightness does the job on an OLED screen, rounds its corners, and lights what floats with its
ultraviolet, because a shadow on black is a shadow nobody sees. The rest cast a soft shadow under what floats. Gruvbox
turns the strip under the header into a stepped status bar and sets the name on a yellow block, and its section colors
fade to Gruvbox's own; Black makes it glow like a neon sign, and turns its section colors all the way up. The others
have a little of the same: Gruvbox's light side matches its dark one, monospace included, Solarized is crisp and flat,
Monokai crisp and monospaced with a neon glow, Nord's light side a calm fade through its blues, Grey one steel-blue
rule, Off-white panels lying on the page like paper, and Sage, Rosé Pine, Forest, and Plum round their corners, Plum
most of all. Layout and sizes never change with a palette, so nothing moves when you switch, except under Gruvbox and
Monokai, where monospace runs wider and a long line wraps a little sooner. Their text is drawn a step smaller to make
up some of the width; every line keeps its height, so nothing shifts up or down. This guide stays in its usual sans
under both: monospace suits a readout, and a manual set in it reads like one long log line.

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

## Attention

**Hide chore findings** leaves what your [chores](chores) find off the [attention](attention) list, its counter, and
the nav's badge, so the list holds only what needs you. Nothing is dismissed: each chore's page still lists its
findings, and the attention page says how many it left out, with a link back here, so a hidden finding is never
mistaken for none. It's this browser's alone. `canopy status` still lists every finding, and so does the next tab you
sign in from on another machine.

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

**Open** takes you to a page of its own for the numbers you change most: how many workers, chores, reviews, and tasks
run at once, each pool's slots, how many tries a ticket, a plan, or a review's draft gets, how much you may attach to
one, how often the loop ticks, how long a run may take before canopy stops it, and the monthly budget the
[spend page](reports#the-spend-page) tracks, with any alerts short of or past it. You can add and drop alerts freely
here: the 100% one isn't in the list, so dropping everything still leaves it.

It also holds the settings that only get stricter from here. **Plans** says which work waits on a plan you approve,
and how readily a planner may wave its own plan through: you can make tickets wait, or take the planner's say away,
but not the reverse. **Trust** lets you drop a trusted reviewer or an authorized replier, never add one, have workers
draft their review replies for you instead of posting them, turn `trust.rebase` off but not on, and cut the reruns of
flaky checks but not raise them. A stolen session that could add a replier would keep steering your workers after you
changed the secret, so adding one stays an edit to the file. A choice that would loosen is greyed out, so there's no
button to find out the hard way.

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
own, then a row for each chore. Each row names the model at the variant it runs at, `provider/model@high`, as the file
spells it, or says `runtime default` when nothing sets one and the runtime picks, which is a choice, just not yours.
A chore with a `model` in its own table is marked **own model**; one whose command runs an agent of your own names
that agent instead, since its own definition chooses (see [chores](chores#setting-one-up)).

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
`canopy models` prints it, read only when you open it, since asking starts the runtime; canopy then keeps that list
for five minutes, or until the loop reads its config again.

## Skills

Every skill the runtime finds for canopy's agents, on a page of its own: **Open** on the **Skills** panel. Each row
names the skill, says where its file is, and gives what its front matter says it is for, which is all an agent reads
before deciding to load it, so a vague one is a skill nobody loads. **Show SKILL.md** opens the instructions under
the row, as text.

Where a file is, on its chip:

- **canopy**: shipped with canopy, in the snapshot of its definitions the runtime reads. Edit it in canopy, not there.
- **workspace**: in the workspace's own runtime config, under its root.
- **home**: yours, in your home. Every session of yours loads it, canopy's or not.
- **built-in**: the runtime's own.
- **other**: anywhere else.

The runtime is asked as a run asks it, in the workspace root, so a skill a repository keeps for itself is missing here;
its runs, started in its worktrees, still get it. Every skill an agent is offered costs each of its model calls,
loaded or not, so one an agent never uses is cheaper denied to it, by name, in your runtime config. Which agent gets
which is `canopy agents`, which asks the runtime once for each agent and takes its time about it.

The page asks the runtime for its skills alone, once, when it opens, not on a timer; **Read again** asks afresh after
you've added one. The filter narrows the list by name or description. Nothing here changes a skill: add, edit, or deny
one in the runtime's own files.

## Config

The loop reads your workspace's `canopy-workspace.toml` and your `config.toml` when it starts. **Reload** reads them
again, as `kill -HUP` on the loop does; a tick that's running finishes first. It says what changed, and which changes
wait for a restart. A file that doesn't load changes nothing, and the error names its file and key, so a typo costs you
a fix, not a loop. [Config files](config-files) lists every key.

## Session

How long this browser stays signed in, and **Sign out**. [Signing in](signing-in) covers the secret and how to sign
every browser out at once.
