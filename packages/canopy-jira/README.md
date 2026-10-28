# canopy-jira

canopy's Jira connector (DESIGN §30): `canopy-connect-jira` reads Jira Cloud's tickets and comments into canopy's
journal. canopy runs it as a command, a `tracker` source's, and never imports it, so the harness holds no token and
opens no connection (TRUST_MODEL T2, D003). It writes nothing to Jira.

It is installed beside canopy: `uv tool install` puts it on `PATH`.

## Setup

1. Make an API token for your Atlassian account (Account settings, Security, API tokens).
2. Put your email and the token in a file of your own that nobody else can read, one line `EMAIL:API_TOKEN`:

   ```sh
   install -m 600 /dev/null ~/.config/canopy/jira-credentials   # then write the line in it with an editor
   ```

   The default is `$XDG_CONFIG_HOME/canopy/jira-credentials`; `--credentials-file` names another. A file that is not
   a regular file of yours, or that group or others can read, is refused. The credentials are never read from argv,
   the environment, or canopy's config.
3. Name the source in `~/.config/canopy/config.toml`, with the one site the credentials are sent to:

   ```toml
   [connect.sources.jira]
   kind = "tracker"
   cmd = "canopy-connect-jira --site acme.atlassian.net"
   ```

4. Run `canopy tick --dry-run`, and check that `canopy status` names the source with an `ok` run.

## Contract

On stdin, one JSON object naming what to observe, each key optional: `query`, in JQL, and `tickets`, each
`{"key": "PROJ-1", "comments_since": TIME}`.

On stdout, one JSON line per observation, in the shapes [DESIGN §30](../../docs/design/CONNECTORS.md) gives:

- for each ticket asked for and read whole, its `ticket` line, with each label and when it was last added, then a
  `comment` line for each comment at or after its `comments_since`, or for every comment without one;
- for each open ticket the query returned, read to its last page, its `ticket` line;
- for each ticket one of those is blocked by, its `ticket` line;
- last, an `end` line naming the tickets read whole and, when the query was read to its last page, the open tickets it
  returned, in its order.

A ticket that could not be read whole prints only its error on stderr, so a cut-off read never looks like a ticket with
no comments.

Exit codes: 0 everything was read; 1 something was not, as the `end` line says; 2 the site, the credentials file, or
stdin is not usable, and nothing was read.
