# Settings

A handful of things you set from the browser: how the UI looks and sends, a notice for every worker, reloading your
config, and the fun. It opens from the rail's foot, beside the guide. The theme, the send key, and the fun are kept in
this browser; everything else canopy reads from its config files, as it always did.

## Theme

**Light**, **Dark**, or **System**, which follows your machine. Every open tab follows along. The button at the right
of the header flips it too.

## Replies

Which key sends a reply, a note, or a comment: **Enter**, **Ctrl+Enter** (⌘+Enter on a Mac), or **Button only**, if
you've ever sent half a sentence to a worker and would rather not again. Shift+Enter always makes a new line. The key
you pick shows on each send button.

## Notice to workers

Tell every run dispatched from now on about something going on outside the work, such as a CI outage: "Artifactory is
down: CI builds that fetch dependencies will likely fail." Workers, reviews, and chores hear it, and the overseer holds
off sending a resume after a failure the notice explains. This is `canopy notice TEXT --for DURATION`.

Pick how long it lasts, **1 hour**, **4 hours**, or **1 day**, and press **Set notice**. It lapses on its own, and
setting another replaces it. While it's in force, a banner above every page shows it, with **Clear** to end it early.
A run already going keeps the prompt it started with, so a notice reaches only the runs after it. The CLI can set one
for up to a week, for outages with ambitions.

## Config

The loop reads your workspace's `canopy-workspace.toml` and your `config.toml` when it starts. **Reload** reads them
again, as `kill -HUP` on the loop does; a tick that's running finishes first. It says what changed, and which changes
wait for a restart. A file that doesn't load changes nothing, and the error names its file and key, so a typo costs you
a fix, not a loop. [Config files](config-files) lists every key.

## Fun

Off by default, and none of it does anything useful, by design.

- **Ticker**: joke headlines crawling across the header, with a speed, a gap between headlines, and topics to pick
  from. **Tips** mixes real tips about canopy in with the jokes.
- **Sprig**: a small wire figure at the foot of the rail, with a tip for every page. None of them help. Click it for
  a new one, picked at random like the ticker's headlines, or **Don't show me tips again** to turn it off.
- **The hat shop**: every dollar canopy spends is a dollar towards Sprig's hats. All sales are final.

The switch in the panel's header does exactly what you'd fear. Sprig, if it's on, brought glow sticks.

## Session

How long this browser stays signed in, and **Sign out**. [Signing in](signing-in) covers the secret and how to sign
every browser out at once.
