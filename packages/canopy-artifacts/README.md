# canopy-artifacts

canopy's local artifact store (DESIGN §38): pages workers publish for people to read, and the comments people leave on
them, served as MCP tools over stdio. Louvre, the hosted store, serves the same tools over MCP's streamable HTTP behind
its token, so a skill written for one works against the other. This file is the contract both serve.

```sh
canopy-artifacts serve --store DIR [--namespace NS] [--agent NAME] [--origin KEY=VALUE ...] [--read-only]
```

The agent runtime's MCP config starts it, and it serves until stdin closes. It opens no socket. `--store` is a
directory of the operator's that nobody else can read, made if it is not there: canopy's state directory in use, never
the journal. A symlink, another owner's directory, or one open to group or others is refused (D053), with exit 2.

The options are the scope a Louvre token carries, set by whoever writes the MCP config, never by a tool's caller:

- `--namespace` (default `local`): where artifacts are made, and the only namespace a call reads or writes.
- `--agent` (default `agent`): every comment and resolution written here is the author `agent:NAME`, `kind: agent`,
  on behalf of `operator`. The local store's tools never write as a person: a comment through them is an agent's, as
  one written with a Louvre token is, so it is never authority (§38, D069).
- `--origin KEY=VALUE`, repeated: pairs set on every artifact made here, over the caller's.
- `--read-only`: every write is refused with `read_only`, as a `read` token's are.

In a run canopy starts, the runtime starts `serve` with the run's environment, which no tool call can change, and
`serve` reads the run from it, so canopy, not the worker, names the workspace, ticket, and run: `CANOPY_WORKSPACE` sets
`canopy.workspace`, `CANOPY_TICKET` `canopy.ticket`, and `CANOPY_RUN_ID` `canopy.run`, each over the caller's pair and
`--origin`'s. A variable unset or empty sets nothing, so outside a run the caller's pairs stand.

```sh
canopy-artifacts feed --store DIR [--namespace NS] [--origin KEY=VALUE ...] [--most N]
```

canopy's `artifacts` source (DESIGN §30), configured as `[connect.sources.<name>]` with `kind = "artifacts"`. Given
`{"since": SEQ}` on stdin, it prints the comment feed's changes after SEQ, a JSON object to a line, paging the feed
until a page is not full or `--most` (default 1,000) are printed, then the last page's `end` line, which names where
the next run reads from. `--origin` reads only the artifacts whose origin holds the pair. It never writes, as a
`read` token cannot. A request it cannot read, or a store it cannot open, prints nothing and exits 2.

## Records

| Record | Fields |
|---|---|
| Artifact | `id`, `title`, `namespace`, `origin` (at most 16 string pairs; canopy sets `canopy.workspace`, `canopy.ticket`, `canopy.run`), `latest_version`, `created_at` |
| Version | `artifact_id`, `n`, `content_type` (`text/html`, `text/markdown`), `sha256`, `text` (the rendered page's visible text, what anchors resolve against), `created_at`; immutable |
| Thread | `id`, `artifact_id`, `anchor` (null for the whole artifact), `anchored_version`, `state` (`open`, `resolved`) |
| Comment | `id`, `thread_id`, `seq`, `author`, `body` (at most 4,000 characters), `created_at`, `edited_at`, `deleted_at`, `via` (`web`, `mcp`) |
| Author | `id` (stable, from the store's sign-in), `display_name`, `kind` (`person`, `agent`), `on_behalf_of` |

An artifact's origin is set when it is made, and a new version keeps it; its title is its latest version's. A
comment's `seq` is that of the latest change to it. Times are ISO 8601, in UTC.

## Anchors

An anchor is a W3C Web Annotation `TextQuoteSelector` over a version's `text`: `exact`, and `prefix` and `suffix` of at
most 32 characters, each with its whitespace collapsed, as a plan's comments are. HTML anchors are taken inside the
sandboxed frame and checked against `text`, never markup.

- A version's `text` is what a reader sees, each run of whitespace one space. For HTML it is read from the markup: tags
  are no text, a block's tags part words, and `script`, `style`, `template`, and `title` show nothing. The local store
  takes Markdown's `text` as its source until it renders Markdown.
- An anchor is found by its words. Where they are more than once, the copy whose `prefix` and `suffix` match best
  wins, and the first of those that tie. Words found nowhere are `passage_gone`, and never move to other words.
- `comment_create` anchors on the latest version, and refuses words not in it with `anchor_not_found`.

## Tools

| Tool | Input | Returns | Writes |
|---|---|---|---|
| `artifact_publish` | `title`, `content_type`, `content`, `origin`, `artifact_id` (to add a version) | `artifact_id`, `version`, `url` | yes |
| `artifact_read` | `artifact_id`, `version` | `artifact`, `version`, `content`, `text` | no |
| `artifact_list` | an `origin` filter, `cursor` | `artifacts`, newest first, and `next_cursor` (null on the last page) | no |
| `thread_list` | `artifact_id`, `state`, `version` | `threads`, each with its `comments` and its `anchor_status` (`found`, `passage_gone`; null with no anchor) | no |
| `comment_feed` | an `origin` filter, `since`, `limit` (at most 200) | the changes after `since`, then an `end` line | no |
| `comment_reply` | `thread_id`, `body` | `comment_id`, `seq` | yes |
| `comment_create` | `artifact_id`, `anchor`, `body` | `thread_id`, `comment_id`, `seq` | yes |
| `thread_resolve` | `thread_id`, `resolved` | `state` | yes |

A tool's result is one JSON object, or for `comment_feed` one JSON object to a line. An origin filter matches an
artifact whose origin holds every pair of it. A version omitted is the latest. The local store's `url` names a version,
`canopy-artifacts:ID/N`, and opens nothing: it serves no page yet.

A refusal is a tool error whose text is `{"code": ..., "message": ...}`, with a code: `not_found`, `out_of_scope`
(outside the token's namespace), `too_long`, `anchor_not_found`, `read_only`, or `invalid` (arguments the tool cannot
take, such as a field it does not have, a blank body, or an origin given with `artifact_id`). No tool deletes an
artifact or shares one.

## The comment feed

- **The cursor.** `seq` is one sequence across the store, given in commit order to every change (a comment created,
  edited, or deleted; a thread resolved or reopened), and only once the change is visible, so nothing appears below a
  cursor a reader has passed. Resolving a thread already resolved, or reopening one open, is no change. A deleted
  comment keeps its row with its body empty.
- **Each page** holds at most `limit` changes, oldest first, and ends `{"kind": "end", "through": <seq>}`; a page
  without one is incomplete. `through` is the last change's `seq` when the page is full, and otherwise the store's
  newest, past changes the filter or the namespace left out; the next page reads from it.
- **A change** carries its `kind`, `seq`, and `at`; the artifact's id and origin; the thread's id, anchor,
  `anchored_version`, state, and `anchor_status` in the artifact's latest version, as `thread_list` gives it; the
  comment's id, body, and times, null for a thread's change; and the `author` and `via` of the change. The comment and
  thread are as they are when read, so a deleted comment's body is empty in every change to it, and a passage reworded
  since reads `passage_gone` in each. Never the artifact's content.

## Louvre's tokens

The operator mints canopy's token in Louvre, bound to their account and one namespace, with scopes `read`, `publish`,
and `comment`; the comment source's is `read` only. It lives in an operator-only file the runtime's MCP config reads,
never in canopy's config, journal, or logs (TRUST_MODEL T2). A comment written with it is `kind: agent`, and canopy
adds its comment marks (D069) too.

## Not in the local store yet

The web channel: people's comments (`via: web`, `kind: person`), editing and deleting a comment, and rendering a
version's HTML, which the web UI will do from a second loopback origin in a sandboxed frame (TRUST_MODEL T8). The schema
and the feed already hold edits and deletions.
