# canopy-github

canopy's GitHub programs (DESIGN §29, §30): `canopy-connect-github` reads PRs and branches into canopy, and
`canopy-post-github` posts the replies and reviews the operator approved, word for word. canopy runs them as commands
and never imports them, so the harness holds no token and opens no connection (TRUST_MODEL T2, D003).

They are installed beside canopy: `uv tool install` puts both on `PATH`. Each reads the token `gh` holds for the host
the PR's URL or the repository's clone URL names, when it runs, and talks to that host's GraphQL API, so GitHub
Enterprise works as github.com does. Run `gh auth login` for each host; they never take a token from argv, the
environment, or canopy's config.

## Config

Unset, canopy uses both for its `vcs` source. Naming them, in `~/.config/canopy/config.toml`, looks like this; a
`tracker` source with `post_cmd` lets canopy post a ticket's drafts to GitHub Issues too
([examples/config.toml](../../examples/config.toml)):

```toml
[connect.sources.github]
kind = "vcs"
cmd = "canopy-connect-github"
post_cmd = "canopy-post-github"
```

## `canopy-connect-github`

Reads, and writes nothing to GitHub. On stdin, one JSON object naming what to observe, each key optional:

```json
{"prs": ["https://github.com/acme/api/pull/7"],
 "repositories": [{"name": "api", "url": "git@github.com:acme/api.git"}], "branch_prefix": "canopy/",
 "review_query": "repo:acme/api is:pr is:open author:@me"}
```

On stdout, one JSON line per observation, in the shapes [DESIGN §30](../../docs/design/CONNECTORS.md) gives: for each
PR, a `pr` line, a `check` line per check at its head, and a `review` line per review and review comment; for each
repository, a `branch` line per branch under the prefix; last, an `end` line naming what was read whole. What could not
be read whole prints only its error on stderr, so a cut-off read never looks like a PR with no checks.

Exit codes: 0 everything was read; 1 something was not, as the `end` line says; 2 stdin or the command line is not
usable, and nothing was read.

## `canopy-post-github`

Posts one PR's drafts as one review, or one ticket's as one issue comment. On stdin, one JSON object:

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
