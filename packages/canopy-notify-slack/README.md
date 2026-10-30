# canopy-notify-slack

canopy's Slack programs (DESIGN §20, §30): `canopy-notify-slack`, a notification sink that posts what canopy sends it to
a Slack channel, and `canopy-connect-slack`, the `slack` connector, which reads the operator's replies in the sink's
threads. canopy runs both as commands and never imports them, so the process that holds the journal never opens a
connection or reads the secret (D035).

They are installed beside canopy: `uv tool install` puts both on `PATH`. The web UI's guide,
[Slack](../../ui/src/guide/slack.md), walks through making the Slack app, the webhook or bot token, and the config;
this file is the reference.

## Secrets

Each secret is read from a file that belongs to the operator and that nobody else can read, never from argv, the
environment, or canopy's config. A file that is not a regular file of yours, or that group or others can read, is
refused.

- `--webhook-file`, by default `$XDG_CONFIG_HOME/canopy/slack-webhook`: an incoming webhook's URL.
- `--token-file`, by default `$XDG_CONFIG_HOME/canopy/slack-token`: a bot token, `xoxb-...`, for `--channel`. The
  connector reads the same file.

## `canopy-notify-slack`

Reads one message in canopy's `json` format on stdin and posts it as one Slack message, in Block Kit built from the
fields canopy sends. With `--threads`, it posts each part of it in the thread it is about, starting that thread first
when it has none today, so one message can make several posts.

```toml
[notify.sinks.slack]
cmd = "canopy-notify-slack --channel C0123ABCD --threads --broadcast blocked"
events = ["attention", "loop", "runs", "reviews"]
```

- `--webhook-file PATH`: post to this incoming webhook, the default without `--channel`.
- `--channel ID`: post with the bot token, through `chat.postMessage`, to this channel.
- `--token-file PATH`: with `--channel`, the bot token.
- `--username`, `--icon-emoji`: with `--channel`, post under this name and emoji (Slack's `chat:write.customize`).
- `--threads`: with `--channel`, post each ticket's and review's messages in its own thread, a new one each day.
- `--broadcast KIND`: with `--threads`, also show a reply in the channel when it holds `attention`, `plan`, or
  `blocked`; repeat it for more than one.

With `--threads`, the sink records its threads in `$XDG_STATE_HOME/canopy/slack-threads.json` and keeps each for a
week. Text from the journal is escaped and set `verbatim`, so it cannot mention a person or `@channel`, or show one
link and point at another.

Exit codes: 0 posted; 1 the post failed, with Slack's reply on stderr; 2 the command line, the secret file, the
channel, the threads file, or the message is not usable. canopy retries anything but 0 on its next tick.

## `canopy-connect-slack`

Reads, and posts nothing. It needs the sink's bot token with `channels:history`, or `groups:history` for a private
channel, beside `chat:write`.

```toml
[connect.sources.slack]
kind = "slack"
cmd = "canopy-connect-slack --channel C0123ABCD"
operators = ["U0123ABCD"]
```

`--channel` is the sink's own `--channel` id; `--days`, by default 3, is how far back it reads. On stdin, one JSON
object: `repo`, `operators`, the Slack user ids whose replies it prints, and optionally `tickets`. On stdout, in the
shape [DESIGN §30](../../docs/design/CONNECTORS.md) gives, a `reply` line for each message one of `operators` wrote in
a ticket's thread, or in the channel starting with a mention of the bot (`@canopy PROJ-123 use the staging config`),
then an `end` line naming what was read to its last page. Nobody else's words leave the process, and neither do a
bot's.

Exit codes: 0 everything was read; 1 something was not, as the `end` line says; 2 the command line, the token file,
the threads file, or stdin is not usable, and nothing was read.
