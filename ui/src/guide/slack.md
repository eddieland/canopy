# Slack

canopy can post to a Slack channel whenever something needs you or the loop does something worth hearing about: a new
attention item, a worker's question, a run ending, the loop failing. It's a notification sink, `canopy-notify-slack`,
installed with canopy. This page sets it up, picks what it hears, and explains what to do when it goes quiet.

## What you get

Each delivery is one Slack message, or, with [threads](#threads), one post per ticket. It's built in Block Kit from the
fields canopy sends, so it reads like a status board rather than a log:

- A line in small type naming the workspace and counting what's in it:
  `canopy · acme · 2 new · 1 resolved · 4 open · 3 events`. No big heading, so a busy channel reads as news rather
  than a column of titles.
- Each new [attention item](attention) on its own, after a bell: the ticket and its title in bold, the reason in words
  (`needs reviewer`), its detail, and, in small type under it, how long it's been open, in the reader's own time zone.
- The items that resolved, together, struck through, with `(dismissed)` on the ones you dismissed.
- Each event, led by an emoji for how it ended, so a channel scans by outcome: a check for `done`, a raised hand for a
  run waiting on you, with its question quoted, a cross for `failed`, an hourglass for a timeout. A proposed plan, an
  approved one, follow-ups filed, a chore's or a review's run, a task's, and the loop's own trouble each get a line of
  their own. The details you rarely need, such as a run's attempt and branch, sit in small type under it.
- A pull request on GitHub by its short name, `acme/api#7`, linked to it; any other link shows its whole address.
- A [digest](#digests), when one is due, as a grid: ticks, workers running, runs started and ended, what needs you,
  and what it all cost.
- An `open` link after each item, to its page in this UI, while the loop serves it ([below](#links-back-here)).

The same message goes along as plain lines too, which is what Slack shows in a notification and on a lock screen. A
message about one thing leads with it, so the lock screen says `run 41 ended failed`, not `1 event`.

## Webhook or bot token

The sink posts one of two ways. Pick one per sink.

- **An incoming webhook** is the quick one: a URL that posts to the one channel you chose when you made it, under the
  app's name and icon. Nothing to invite, no scopes to think about. It can't thread.
- **A bot token** posts with `chat.postMessage` to the channel you name with `--channel`. It takes a few more clicks,
  and gets you [threads](#threads), a name of your own with `--username`, and an emoji with `--icon-emoji`.

Start with a webhook. If the channel gets busy enough that you're scrolling past one ticket to find another, switch to
a bot token and turn threads on.

Either way, the secret lives in a file of its own that belongs to you and that nobody else can read. It's never in
canopy's config, on a command line, in the journal, or in a log, and canopy itself never opens it: only the sink does.
The sink refuses a file that someone else owns or that your group or anyone else can read, and says how to fix it.

## Setting up a webhook

1. At [api.slack.com/apps](https://api.slack.com/apps), **Create New App**, from scratch, in your workspace. Call it
   canopy; it's the name your posts go out under.
2. Under **Incoming Webhooks**, turn them on, then **Add New Webhook to Workspace** and pick the channel.
3. Copy the webhook URL. It starts `https://hooks.slack.com/services/`.
4. Put it in `~/.config/canopy/slack-webhook` (under `$XDG_CONFIG_HOME`, if you set it), readable by you alone, with
   the commands below.
5. Add the sink to your config, as below.
6. **Reload** in [Settings](settings#config), then send a test with `canopy notify test slack`
   ([below](#checking-it-works)).

```sh
mkdir -p ~/.config/canopy
install -m 600 /dev/null ~/.config/canopy/slack-webhook
$EDITOR ~/.config/canopy/slack-webhook
```

Making the empty file first, mode 600, means the URL is never readable by anyone else, even for the second it takes to
paste it. The file holds the URL and nothing else.

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack"
events = ["attention", "loop", "runs"]
```

A webhook kept elsewhere is `--webhook-file PATH`, such as one file per channel.

## Setting up a bot token

1. At [api.slack.com/apps](https://api.slack.com/apps), **Create New App**, from scratch, or reuse the one you made for
   a webhook.
2. Under **OAuth & Permissions**, add the bot token scope `chat:write`. Add `chat:write.customize` too only if you'll
   pass `--username` or `--icon-emoji`; that's the scope that lets an app post under another name.
3. **Install to Workspace**, and copy the **Bot User OAuth Token**. It starts `xoxb-`.
4. Put it in `~/.config/canopy/slack-token` the same way as the webhook above, mode 600.
5. In Slack, invite the app to the channel: `/invite @canopy`, with whatever you named it. A bot posts only where it
   was asked in.
6. Find the channel's id: open the channel's details, and it's at the foot of **About**, `C0123ABCD`. A name, `#canopy`,
   works too, but an id survives someone renaming the channel.
7. Add the sink to your config, as below.
8. **Reload**, and `canopy notify test slack`.

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack --channel C0123ABCD --threads --username canopy --icon-emoji :evergreen_tree:"
events = ["attention", "loop", "runs", "reviews"]
```

It has to be a bot token. A user token, `xoxp-`, acts as you, with every scope you ever granted it, and the sink
refuses one. Give the bot `chat:write` and nothing it doesn't use: the token can only post, so a leaked one can only
post. `--token-file PATH` reads a token from somewhere else.

## Where the config goes

Every `notify` key is yours alone, so a sink goes in `~/.config/canopy/config.toml`, for every workspace, or in
`.canopy/config.toml`, for this one. canopy refuses to run if `canopy-workspace.toml` sets one, and the error says where
it belongs: whoever can commit to a shared file shouldn't get to choose where your loop's news goes.
[Config files](config-files) has the rest of the keys.

A sink in your own config hears from every workspace you run a loop in. Each message names the workspace, and threads
are kept apart per workspace, so two loops sharing a channel don't share threads. You can have up to five sinks in
all, each a table of its own, named as you like: `[notify.sinks.team]` beside `[notify.sinks.slack]` is how one loop
posts to two channels.

## Choosing what it hears

`events` lists the groups a sink takes. Leave it out and you get `["attention", "loop"]`.

- `attention`: an item joined the attention list or left it. This is the one you want; it's everything that needs
  a human.
- `runs`: a worker started or ended, with a question when it ended waiting on you, a plan waiting on your approval
  or approved by its planner, and follow-up tickets a run filed.
- `reviews`: a review run ended, with its verdict and how many findings.
- `chores`: a chore's run ended, with how many findings. The findings themselves are attention items.
- `tasks`: a task's run ended, with its PR or its question.
- `replies`: what came of a reply you wrote in Slack: a mention recorded on its ticket, or any reply canopy refused,
  and why ([below](#replying-from-slack)).
- `loop`: ticks failing several in a row, and recovering; a sink failing; and the month's spend reaching its
  budget or one of its alerts ([the spend page](reports#the-spend-page)).

Each sink hears of each attention item once. A sink that was down for an hour gets the net change when it's back,
not every flicker in between: an item that came and went while it was down is news nobody needs. Events wait for it
too. A new sink starts from now, with no backlog, so adding one doesn't post the history of your week.

The sink needs `format = "json"`, which is the default: leave `format` out. With `text` it gets canopy's plain lines,
which it can't build a message from, and it refuses, saying so.

## Batching

A busy loop can post every few minutes. `batch_minutes = 15` sends at most one message per 15 minutes: what doesn't
need you now waits, then goes out together. What does need you goes at once, taking everything held with it: a new
attention item, a run that ended with a question, a plan to approve, and the loop or a sink failing. A sink that was
quiet through the window sends at once too, so batching never delays the first message after a lull.

## Digests

`digest_every_minutes = 240` posts a summary every four hours: how many ticks and how they ended, the workers running,
runs started and ended, the open attention list and its oldest item, the tickets done and waiting on you, and what the
runs cost by kind. The smallest interval is 60.

It's sent even when nothing happened, on purpose. canopy can't tell you it stopped ticking, because it stopped; a
digest that doesn't arrive can. If you'd rather hear about money than heartbeats, `digest_min_usd = 5` holds a due
digest until the runs since the last one cost $5 or more. That gives up the heartbeat, so keep it on a sink that isn't
the one you count on.

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack --channel C0123ABCD --threads"
events = ["attention", "loop", "runs"]
batch_minutes = 15
digest_every_minutes = 240
```

## Threads

With a bot token, `--threads` gives each ticket a thread of its own, and each PR a review reads. The first post about
it each day starts the thread in the channel, naming the ticket and its title, the workspace, and the day; that post and
everything after it about the ticket, the first item included, are replies. A new day starts a new thread, by your
machine's date, so yesterday's thread stays yesterday's and a long-running ticket doesn't grow one thread forever.

Some things stay in the channel, where you read them as they come: loop events, a chore's runs and its findings, an
attention item about a whole repository, and the digest.

A reply in a thread doesn't show in the channel, which is the point, until it's something you'd want to see anyway.
`--broadcast` names what also shows in the channel; give it once for each:

- `--broadcast attention`: a new attention item.
- `--broadcast plan`: a plan waiting on your approval.
- `--broadcast blocked`: a run that ended waiting on your answer.

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack --channel C0123ABCD --threads --broadcast blocked --broadcast plan"
events = ["attention", "loop", "runs", "reviews"]
```

The sink remembers its threads in `~/.local/state/canopy/slack-threads.json` (under `$XDG_STATE_HOME`, if you set it),
kept apart by channel and workspace. It posts only in today's, and keeps the rest for a week so a
[reply](#replying-from-slack) in yesterday's still reaches the ticket. canopy's journal knows nothing of them. Delete
the file and the worst that happens is a fresh thread for each ticket, and replies in the old ones going unread. If
Slack refuses a post halfway through a delivery, canopy sends the delivery again next tick, and the sink posts only
what it hadn't, so nobody reads the same run ending twice.

## Replying from Slack

With threads on, you can answer a ticket where you read about it: reply in its thread, and canopy takes it as if you'd
typed `canopy reply` with the same words. It answers the worker's waiting question, wakes the loop, and the next tick
sends a worker off with your reply as its instruction. On the ticket's page it reads `reply via slack`.

There's no server for Slack to call. A connector, `canopy-connect-slack`, installed beside the sink, reads the threads
on each of the loop's polls, every `connect.every_minutes`, two by default: an outbound call, the same kind the sink
makes to post. So a reply lands within a couple of minutes, not instantly, and only while `canopy loop` runs.

1. Give the bot one more scope under **OAuth & Permissions**: `channels:history` for a public channel, or
   `groups:history` for a private one. Reinstall the app when Slack asks. The token file stays as it is.
2. Find your own Slack member id: your profile, the three dots, **Copy member ID**. It looks like `U0123ABCD`.
3. Add a `slack` source to your config, its `--channel` exactly the sink's, and list yourself in `operators`.
4. Add `replies` to the sink's `events`, so it can tell you what came of a [mention](#tickets-without-a-thread) or a
   reply canopy refused.
5. **Reload**.

```toml
[connect.sources.slack]
kind = "slack"
cmd = "canopy-connect-slack --channel C0123ABCD"
operators = ["U0123ABCD"]
```

`operators` is the whole guard, and it's checked twice. canopy asks the connector for those ids' replies alone, so
a coworker's never even reaches canopy, and then checks every reply's id again itself, in code, so a connector that
prints more can't widen it. A bot's reply never counts either, even one posting under your name.
List only yourself. Whoever signs in as a listed account answers your workers as you, and "my laptop was unlocked" is a
story best told about somebody else's loop.

It reads replies in tickets' threads from the last three days (`--days`, up to seven), and only on tickets canopy
already knows. A reply in a review's thread, and anything about plans, starts, or grants, stay in canopy: approve a
plan on [its page](plans), not with a thumbs-up. Each Slack message counts once, so the connector rereading a thread
every poll records nothing twice, and an edit after canopy read it changes nothing; reply again instead. A reply over
4,000 characters is refused, as `canopy reply` refuses one. With `replies` in the sink's events, the sink says so in a
reply under yours, once; without it, only the loop's log does. A dry run reads the threads and records nothing.

### Tickets without a thread

A ticket only gets a thread once canopy has something to say about it, so the one you want to nudge often has none.
Mention the bot in the channel instead, then the ticket's key, then your reply:

```text
@canopy PROJ-123 use the staging config, not prod
```

That's the same reply, recorded the same way, on any ticket canopy knows, thread or not. The mention has to come first
and the key right after it, `PROJ-123:` works too; a message that mentions the bot anywhere else is just a message,
and so is one in a thread. It's read from the same last three days, and only from the ids in `operators`.

Since nothing in the channel would otherwise show it landed, the sink answers: it posts the reply in the ticket's
thread, starting one if it has to, so you see where it went. A mention canopy can't use, a key it has never heard of
or no key at all, gets a reply under your message saying why. Typos are the most common Slack-to-canopy protocol, and
this way they cost you a reply rather than a silent afternoon.

Give the sink its channel by id, not by name, for this: the sink files its threads under whatever `--channel` says,
and Slack's API reads only an id, so a sink set up with `#canopy` leaves the connector reading nothing at all.

## Links back here

While `canopy loop` serves this UI, each item and event in a message ends with `open`, a link to its page here: the
ticket, the run, the review, the chore. The links use the address the UI is served at. If you reach it some other way,
through an SSH forward or a proxy, set `serve.url` to that address and the links follow; it doesn't move the server.
Unlike the sinks, which a Reload picks up, a change to `serve.url` waits for the loop to restart. Without the UI
running, messages carry no links, and say everything they would otherwise.

The label is always the sink's own word, `open`, never text from the journal, so a link can't show one address and go
to another. Worth knowing before you share the channel: a link to `127.0.0.1` opens your loop only on your machine. On
a teammate's, it opens their own `127.0.0.1`, which is rarely what either of you hoped for.

## What reaches the channel

Ticket titles, attention items' details, a worker's question, a run's summary, a review's verdict, the PR it read, and
the month's spend. Much of that was written by agents, and some by whoever comments on your tickets. So point a sink
only at a channel whose readers may read all of that, and keep the secret file yours alone.

None of it can do anything in Slack. The sink escapes every piece of journal text, so an `@channel`, a mention, or a
link dressed up as another can't get through, even if a ticket's title tries. A URL in the text stays a plain link that
shows itself, and a PR's short name, `acme/api#7`, is read off its own address, never off the journal. And the people
in the channel can see what the loop does but can't steer it: nothing they write in Slack reaches canopy, unless you
list them as [operators](#replying-from-slack), which you shouldn't.

## Checking it works

`canopy notify test` sends a test message to every sink, or `canopy notify test slack` to one, now, outside any tick.
It changes nothing in the journal, and it prints how each went:

```text
slack: delivered
team: failed: exited 1: canopy-notify-slack: Slack refused the post: {"ok":false,"error":"not_in_channel"}
```

The test reads `canopy test message for` your workspace, then `nothing is wrong`, after a test tube, so nobody in the
channel panics. It's refused inside a tick or a run: no agent gets to page you.

`canopy status` lists each sink with its last delivery, how many in a row have failed and the last error, and how many
events are waiting for it.

When a delivery fails, nothing is lost: canopy tries again on the next tick, and the sink gets everything it missed.
The third failure in a row records a `loop` event saying that sink is failing, which reaches every other sink that
takes `loop` events. A Slack sink can't tell you Slack is down, so give it a second sink to tell on it, such as
`canopy-notify-desktop`.

## Troubleshooting

`canopy notify test` and `canopy status` show the sink's own words. What they mean:

- `cannot read the webhook file …` or `… token file …`: the file isn't there. The default is
  `~/.config/canopy/slack-webhook` or `slack-token`, under `$XDG_CONFIG_HOME` if you set it; with `--webhook-file` or
  `--token-file`, that path.
- `is readable by others; run: chmod 600 …`: run it.
- `belongs to someone else`: the file must be yours, not root's; make it again as you.
- `must hold one URL starting https://hooks.slack.com/` or `one Slack bot token starting xoxb-`: the file holds
  something else, often a token in the webhook file or a user token, `xoxp-`, in the token file.
- `Slack refused the post`, then Slack's reply. The `error` in it says why:
  - `not_in_channel`: invite the bot to the channel.
  - `channel_not_found`: the id is wrong, or it's a private channel the bot isn't in.
  - `missing_scope`: add the scope it names (`chat:write`, or `chat:write.customize` for `--username` and
    `--icon-emoji`), then reinstall the app.
  - `invalid_auth`, `token_revoked`, or `account_inactive`: the token is no good. Reinstall the app and copy the new
    one.
  - `HTTP 403`, `HTTP 404`, or `HTTP 410` from a webhook: it was revoked, or its channel archived. Make a new one.
- `cannot reach Slack`: no network from where the loop runs, or a proxy in the way. The sink gives Slack 30
  seconds.
- `stdin is not a canopy json message`: the sink has `format = "text"`. Remove the line.
- `--threads needs --channel`, `--broadcast needs --threads`, and the like: the options in `cmd` don't go
  together. Threads, a name, and an emoji all need a bot token.
- `could not start`: `canopy-notify-slack` isn't on the loop's `PATH`. It's installed beside `canopy`; give its
  full path in `cmd`, or install canopy again.
- `timed out`: canopy gives a sink 60 seconds, with the tick waiting on it. A sink that hangs every time delays
  every tick by a minute, so fix it or take it out of the config.
- Messages arrive with no `open` links: the loop isn't serving the UI, or `serve.url` points somewhere the link
  can't go.
- **A ticket has a new thread today**: that's the design, not a bug. Yesterday's is still there, and a reply in it
  still counts.
- `connector_failed` naming the `slack` source, with `missing_scope`: add `channels:history` or `groups:history` and
  reinstall the app. With `not_in_channel` or `channel_not_found`, its `--channel` isn't the sink's.
- A reply in a thread that never shows on the ticket: check that the id in `operators` is yours, that you replied in
  the thread rather than the channel, and that the ticket's thread is under a week old. `canopy status` shows the
  `slack` source's last run.

The sink exits 0 when Slack took the post, 1 when Slack refused it or couldn't be reached, and 2 when its command
line, its secret file, the channel, the threads file, or the message it was given isn't usable. canopy treats anything
but 0 as worth another try next tick.
