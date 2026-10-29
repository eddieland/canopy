# canopy-github

canopy's GitHub programs (DESIGN §29, §30): `canopy-connect-github` reads PRs and branches into canopy, or a
repository's issues as its tracker, and `canopy-post-github` posts the replies and reviews the operator approved, word
for word. canopy runs them as commands
and never imports them, so the harness holds no token and opens no connection (TRUST_MODEL T2, D003).

They are installed beside canopy: `uv tool install` puts both on `PATH`. Each reads the token `gh` holds for the host
the PR's URL, the repository's clone URL, or `--repo` names, when it runs, and talks to that host's GraphQL API, so GitHub
Enterprise works as github.com does. Run `gh auth login` for each host. They take no token from argv or canopy's
config, only the one `gh` answers for that host, once `gh auth status` names it; `gh` itself answers `GH_TOKEN` or
`GH_ENTERPRISE_TOKEN` when one is set in the environment canopy runs them in.

## Config

Unset, canopy uses both for its `vcs` source. Naming them, in `~/.config/canopy/config.toml`, looks like this; with
GitHub Issues as the tracker, a `tracker` source given the repository reads its issues, and its `post_cmd` lets canopy
post a ticket's drafts to them too ([examples/config.toml](../../examples/config.toml)):

```toml
[connect.sources.github]
kind = "vcs"
cmd = "canopy-connect-github"
post_cmd = "canopy-post-github"

[connect.sources.issues]
kind = "tracker"
cmd = "canopy-connect-github --repo acme/api"
post_cmd = "canopy-post-github"
```

## `canopy-connect-github`

Reads, and writes nothing to GitHub. On stdin, one JSON object naming what to observe, each key optional, but
`branch_prefix` is required once `repositories` names one:

```json
{"prs": ["https://github.com/acme/api/pull/7"],
 "repositories": [{"name": "api", "url": "git@github.com:acme/api.git"}], "branch_prefix": "canopy/",
 "review_query": "repo:acme/api is:pr is:open author:@me"}
```

On stdout, one JSON line per observation, in the shapes [DESIGN §30](../../docs/design/CONNECTORS.md) gives: for each
PR, a `pr` line, a `check` line per check at its head, and a `review` line per review and review comment; for each
repository, a `branch` line per branch under the prefix; last, an `end` line naming what was read whole. What could not
be read whole prints only its error on stderr, so a cut-off read never looks like a PR with no checks. A PR's or a
review's author is its login, a bot's ending `[bot]` as in `trust.trusted_reviewers`.

Exit codes: 0 everything was read; 1 something was not, as the `end` line says; 2 stdin or the command line is not
usable, and nothing was read.

## `canopy-connect-github --repo OWNER/NAME`

The `tracker` source for that repository's GitHub Issues (`HOST/OWNER/NAME` for GitHub Enterprise): a ticket's key is
`GH-` and its issue's number, so issue 12 is `GH-12`, as the `tracker-github` skill has it. It reads, and writes nothing
to GitHub. On stdin, what canopy asks any tracker source, each key optional; the query is GitHub's search syntax:

```json
{"query": "repo:acme/api is:issue is:open label:agent", "tickets": [{"key": "GH-12", "comments_since": "2026-10-18T10:00:00Z"}]}
```

On stdout, as `canopy-connect-jira` prints Jira's: for each ticket asked, a `ticket` line, each label with when its
timeline last added it, and a `comment` line per comment since `comments_since`; a `ticket` line for each open issue
the query returns, PRs passed over, and for each blocker one of them names; last, an `end` line naming what was read
whole. A blocker is an issue GitHub's issue dependencies say blocks it, or one a line of its body names,
`Blocked by #N`. A key names an issue of this repository alone, so a query that returns another repository's issue is
not read, and a ticket an open issue of another repository blocks is not read whole: it stays stale, and canopy
dispatches nothing on it. A comment's author is its login, a bot's ending `[bot]`.

The same exit codes, 2 also when `--repo` is not a repository's name or `gh` holds no token for its host.

## `canopy-post-github`

Posts one PR's drafts as one review, or one ticket's as one issue comment. A reply's reaction is added on its own,
before the review, since GitHub has no pending reaction, so drafts that are only reactions open no review. On stdin,
one JSON object:

- a PR's: `{"pr": URL, "body": TEXT | null, "replies": [{"comment": ID, "text": TEXT | null, "reaction": REACTION |
  null}, ...], "delete_pending": ID | null}`, with `commit` and `comments` for a review of a PR canopy reviewed (§34),
  and `"submit": false` to leave the review pending for the operator to submit on GitHub;
- an issue's: `{"issue": URL, "ticket": KEY, "body": TEXT}`.

On stdout, one JSON line for each thing it posts, then `end`, which says whether it submitted. No `end` line means the
outcome is unknown: the submit may have reached GitHub. The module docstring in
[post.py](src/canopy_github/post.py) holds every field and line.

It never approves, requests changes, resolves a thread, or deletes a review but the pending one it is handed, or one it
opened and could not fill.

Exit codes: 0 posted; 1 GitHub refused, or the outcome is unknown, as the `end` line says; 2 stdin or the command line
is not usable, `gh` holds no token for the host, or a reply names a comment with no thread, and nothing was posted.
