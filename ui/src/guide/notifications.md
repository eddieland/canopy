# Notifications

canopy can tell you what changed without you watching this UI: after each tick it hands a message to each notification
sink you've configured. This page covers what it sends, the sinks that ship with canopy, writing your own, and what
happens when one breaks.

## What canopy tells you

After every tick, each sink gets at most one message, and only when it has something to say: the
[attention list](attention)'s changes since that sink last heard, the events it takes in the order they happened, and
a [digest](#batching-and-digests) when one is due. A quiet tick sends nothing, which is how you'll know it was quiet.

Each sink hears of each attention item once, when it opens, and once more when it resolves. A message lists at most 20
attention lines and 20 events; the rest are counted, with a pointer to `attention.md` and `canopy status`. Events more
than a day old by the time a sink finally takes them are counted rather than listed, since a day-old run start is
history, not news.

## Sinks

A sink is a command that reads one message on stdin. canopy runs it with no shell: `cmd` is split into words the way a
shell would split them, and that's all, so a pipe, `$HOME`, or `~` reaches the command as plain characters. Exit 0
means delivered; anything else, a 60-second timeout included, means try again next tick.

Each sink is a table of its own under `[notify.sinks]`, named with lowercase letters, digits, and hyphens. You can have
five at most. They run one after another while the tick still holds its lock, so a slow sink is a slow loop.

Every `notify` key is yours alone, so sinks go in `~/.config/canopy/config.toml` or `.canopy/config.toml`, never the
shared workspace file ([why](slack#where-the-config-goes)). **Reload** in [Settings](settings#config) picks up a
change. No page of this UI lists your sinks: they live in your config, and in `canopy status`.

### The desktop sink

`canopy-notify-desktop` is installed with canopy and shows each message as one desktop notification, through
`notify-send` on Linux or `osascript` on macOS.

```toml
[notify.sinks.desktop]
cmd = "canopy-notify-desktop"
events = ["attention", "loop", "runs"]
```

It reads either [format](#formats). With `json`, the notification is titled `canopy:` and then your workspace's
folder name; it shows up to 12 lines of the message, cut at 1,000 characters. If `notify-send` isn't installed, the
sink fails every tick, and the third failure in a row is [news to your other sinks](#when-a-sink-fails). Run the loop
on a server and this is the wrong sink: a notification on a machine with no screen is a tree falling in an empty
forest.

### Slack

`canopy-notify-slack` posts to a channel, threads by ticket, and takes your replies back. It has a page of its own:
[Slack](slack).

### Your own command

Any program that reads stdin can be a sink. `logger` writes each line to the system log:

```toml
[notify.sinks.syslog]
cmd = "logger -t canopy"
format = "text"
events = ["attention", "loop"]
```

Exit 0 only once the message really went somewhere. canopy records what a sink was told only on a 0, so a nonzero exit
gets the same news again next tick, with whatever happened since. The end of what your command writes to stderr shows
in `canopy status` and `canopy notify test`, so make it say why.

### The one-line shorthand

`notify.cmd` under `[notify]` is the oldest way to get notified, and still works: it's a sink named `default` that
takes only the attention list, as `text`. Set it or a `[notify.sinks.default]` table, not both; canopy refuses the
config otherwise. It counts toward the five.

## Choosing what a sink hears

`events` lists the groups a sink takes: `attention`, `runs`, `reviews`, `chores`, `tasks`, `loop`, and `replies`, which
only matters with Slack. Leave it out and you get `["attention", "loop"]`. What each group holds is on the Slack page,
under [Choosing what it hears](slack#choosing-what-it-hears); it's the same for every sink.

A new sink starts from now. If it takes `attention`, its first message lists every item open on the list, since it
hasn't heard of any, but it gets none of the events from before it existed. canopy doesn't record events of a group no
sink takes, so adding `runs` to a sink later doesn't bring back the runs you missed. Take a sink out of the config and
canopy forgets it; put it back, or rename it, and it starts over as new.

## Batching and digests

Two optional keys per sink, the same for every kind. `batch_minutes` holds what can wait and sends it together, at
most once per that many minutes; anything that needs you goes at once and takes the held lot with it
([details](slack#batching)). `digest_every_minutes`, 60 or more, sends a summary of the loop's ticks, runs, spend, and
open items on that interval, even when nothing happened, so a digest that stops arriving tells you the loop did. With
`digest_min_usd` it waits for spend instead ([details](slack#digests)).

## Formats

`format` decides what a sink reads on stdin.

- `json`, the default: one object with the attention changes, the events, and the digest as fields, each ticket with
  its title, plus `text`, the same message as lines. Its `version` changes only when a field changes incompatibly, so a
  sink should ignore fields it doesn't know. While the loop serves this UI, items and events carry links to their pages
  ([how](slack#links-back-here)).
- `text`: lines for a person, the last naming the full attention list. Pick it for a command that only forwards text.

## Testing a sink

`canopy notify test` sends a test message to every sink, or `canopy notify test desktop` to the one you name, now,
outside any tick. It prints a line per sink, `delivered` or `failed` with why, exits 1 if any failed, and changes
nothing in the journal. A `text` sink receives this:

```text
canopy: 1 event
* canopy test message for /home/you/acme; nothing is wrong
Full list: /home/you/acme/.canopy/attention.md
```

It's refused inside a tick or a run, so no agent can page you.

## When a sink fails

Nothing is lost. A failed delivery moves nothing, so the next tick tries again with everything the sink missed.
`canopy status` lists each sink with its last delivery, how many have failed in a row and the last error, and how many
events wait for it.

The third failure in a row records a `loop` event naming the sink and its error, which every sink that takes `loop`
hears at once, batching or not. A sink can't report its own outage, so give your main one a second sink that takes
`loop`, of a different kind: Slack being down is not news Slack will deliver. A sink that hangs costs every tick its
60 seconds, so fix it or take it out of the config. Slack's own error messages are under
[Troubleshooting](slack#troubleshooting).
