# Artifacts

Part of the canopy design, normative like all of it: artifacts canopy's workers publish, the people who comment on
them, and how those comments come back to a ticket. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [Agent memory](MEMORY.md).

## 29. Artifacts and Louvre (M53)

Designed, not built (ROADMAP M53, REQUIREMENTS R20). Until it is built, a worker's output reaches people as a PR, a
ticket comment, or a plan (§25), and nothing here describes canopy as it is.

An **artifact** is a page a worker publishes for people to read: a report, a design, an HTML mock-up, a plan. People
comment on its passages, and their comments come back to the ticket that produced it, where the overseer treats them
like review feedback.

Artifacts live in one of two stores that serve the same MCP tools:

- **Louvre**, a hosted artifact platform for the operator's organization. A separate program with its own repository,
  deployment, sign-in, and security model. canopy does not build, ship, or run it. This section is the contract canopy
  needs of it.
- **The local store**, `canopy-artifacts`, a uv workspace member (D041) that canopy ships: artifacts under the
  operator-only state directory (D053), for the operator alone. Artifacts stay out of the journal, since a worker
  writes nothing that reaches the journal while it runs (§27).

### Principles

1. **canopy pulls; Louvre never calls canopy.** canopy runs no listener for outside systems (§3, TRUST_MODEL T8).
   What canopy learns from Louvre it asks for, on its own schedule, as it reads the tracker. Louvre may offer webhooks
   to other consumers; canopy does not use them.
2. **Authority stays with the source (§22, D072).** A comment is a fact about Louvre, read from Louvre. Whether it may
   steer a worker is decided by canopy, in code, from the author's Louvre identity, never by Louvre.
3. **One tool surface, two stores.** The tools below are defined once: the same names, inputs, and results against
   Louvre or the local store. A skill written for one works against the other; only the MCP server the runtime's
   config names differs. The harness imports neither (D003): agents reach both through the runtime's MCP.
4. **Untrusted content stays contained.** An artifact's HTML and a comment's text are model or human text, never
   instructions (TRUST_MODEL T1). HTML renders only on an origin of its own, in a sandboxed frame. Comment bodies reach
   canopy as bounded text, labeled by source and author.

### The round trip

```text
Louvre (hosted)                         canopy (the operator's machine)

someone comments on a passage
        |
comment feed (every change, by seq) --> tick reads the feed (comment_feed after its cursor)
                                                |
                                        author listed? (checked in code) --no--> attention list
                                                | yes                              | the operator sends it on
                                        ticket conversation  <---------------------+
                                        (a message, its passage quoted)
                                                |
artifact updated  <---------------------- worker revises (the overseer dispatches it)
(new version, reply, thread resolved)
```

### Data model

Six records, each with a stable opaque id. A revision is a new version of the same artifact, never a new artifact,
so threads carry over.

| Record | Fields | Notes |
|---|---|---|
| Artifact | `id`, `title`, `namespace`, `origin`, `created_at`, `created_by`, `latest_version` | What people share and comment on. `namespace` bounds tokens (Identity, below). |
| Version | `artifact_id`, `n` (1, 2, 3, ...), `content_type` (`text/html`, `text/markdown`), `sha256`, `text`, `created_at`, `created_by` | Immutable. `text` is the rendered page's visible text, what anchors resolve against. |
| Origin | string keys and values, at most 16 pairs, each at most 256 characters | Opaque to the store, filterable. canopy sets `canopy.workspace`, `canopy.ticket`, `canopy.run`. |
| Thread | `id`, `artifact_id`, `anchor` (none for the whole artifact), `anchored_version`, `state` (`open`, `resolved`), `resolved_by`, `resolved_at` | One discussion on one passage. |
| Comment | `id`, `thread_id`, `seq`, `author`, `body` (at most 4,000 characters), `created_at`, `edited_at`, `deleted_at`, `via` (`web`, `mcp`) | `seq` is the feed's cursor (Comment feed, below). |
| Author | `id` (stable, from the store's sign-in), `display_name`, `kind` (`person`, `agent`), `on_behalf_of` | A token's comments are `kind: agent`, on behalf of the person who minted it. |

A deleted comment keeps its row, its `body` empty and `deleted_at` set, so a reader that saw it learns it went. An
edit sets `edited_at` and puts the comment at the feed's head again.

### Anchors

A thread anchors by the words it is on, never by a position: the W3C Web Annotation `TextQuoteSelector`, which is how
a plan's comments anchor today (§25).

```json
{"exact": "retries three times before giving up", "prefix": "the sink ", "suffix": ", then logs"}
```

- `exact`, `prefix`, and `suffix` come from the version's `text` with whitespace collapsed to single spaces. `prefix`
  and `suffix` are at most 32 characters, as a plan's are.
- Resolving: find `exact` in the version's text; where it occurs more than once, the occurrence whose surroundings
  best match `prefix` and `suffix` wins.
- On a new version, each open thread is looked for again by its words. Found, its `anchored_version` moves to the new
  one. Not found, the thread is `passage_gone` on that version and stays where it was. It never moves to other words:
  a reworded passage may no longer be what the comment was about.
- HTML: anchors are taken from the rendered page's text, inside the sandboxed frame, and posted out of it. The store
  stores and checks them against `text`, never against markup.

### Tools

Eight tools, the same in both stores. Each is typed by its input schema. A refusal is a tool result with
`isError: true` and a short code, as canopy's own tools return one (§27).

| Tool | Input | Returns | Writes |
|---|---|---|---|
| `artifact_publish` | `title`, `content_type`, `content`, `origin`, `artifact_id` (to add a version) | `artifact_id`, `version`, `url` | yes |
| `artifact_read` | `artifact_id`, `version` (default the latest) | its metadata, `content`, `text` | no |
| `artifact_list` | an `origin` filter, `cursor` | artifacts, newest first, paged | no |
| `thread_list` | `artifact_id`, `state` (`open`, `resolved`, `all`), `version` | threads, their comments, and each anchor's status (`found`, `passage_gone`) | no |
| `comment_feed` | an `origin` filter, `since` (a `seq`), `limit` (at most 200) | the changes after `since`, then an `end` line | no |
| `comment_reply` | `thread_id`, `body` | `comment_id`, `seq` | yes |
| `comment_create` | `artifact_id`, `anchor` (optional), `body` | `thread_id`, `comment_id`, `seq` | yes |
| `thread_resolve` | `thread_id`, `resolved` (true or false) | `state` | yes |

Refusal codes: `not_found`, `out_of_scope` (outside the token's namespace), `too_long`, `anchor_not_found`,
`read_only` (a token without the scope), and `operator_only` (the local store, for a tool that only makes sense with
more than one person, such as sharing, should one be added). No tool deletes an artifact: only a person deletes one, in
Louvre's own pages, so no agent can erase what people commented on.

The transports differ, the tools do not. The local store speaks stdio, started by the runtime as a child of the agent
as canopy's `_mcp` is (§27), and opens no socket. Louvre speaks MCP's streamable HTTP behind its token.

### Comment feed

`comment_feed` is the one call canopy makes each tick. It returns every change to comments and threads under an
origin filter since a cursor, so one call covers every artifact a workspace published.

- **The cursor.** `seq` is one sequence across the store, given in commit order to every change: a comment created,
  edited, or deleted; a thread resolved or reopened. A comment edited later appears again with a higher `seq`. A
  reader keeps the highest `seq` it has written down and passes it as `since`.
- **No gaps behind the cursor.** A `seq` is given only when its change is visible to readers, so no change appears
  below a cursor a reader has passed. Otherwise a slow transaction would be skipped for good.
- **Paging.** At most `limit` changes, oldest first; `more: true` means call again from the last `seq`.
- **The end line.** Each page ends with `{"kind": "end", "through": <seq>, "origin": {...}}`, naming what it covered.
  A page cut off without one is incomplete, never "nothing else changed": the connector rule of M36.
- **What a change carries.** Ids, the thread's anchor and state, the author record, `via`, times, and the body cut at
  4,000 characters. Never the artifact's content, which a reader fetches with `artifact_read` when it needs it.

One JSON line per change, as M36's connector contract expects:

```json
{"kind": "comment", "seq": 4182, "artifact_id": "a_7Qf", "origin": {"canopy.workspace": "w1", "canopy.ticket": "PAY-142"}, "thread_id": "t_19", "comment_id": "c_88", "change": "created", "anchor": {"exact": "retries three times", "prefix": "the sink ", "suffix": ", then logs"}, "anchor_status": "found", "author": {"id": "u_ana", "kind": "person"}, "via": "web", "at": "2026-10-16T14:02:11Z", "body": "Should this back off instead?"}
{"kind": "end", "through": 4182, "origin": {"canopy.workspace": "w1"}}
```

### Identity, tokens, and scopes

Every comment has an author the store authenticated, and every token canopy uses is bound to one namespace, so canopy
can trust who wrote a comment and the store bounds what canopy's agents write.

- **People** sign in to Louvre through the organization's identity provider. `author.id` is stable for the life of
  the account and never reused, so canopy can list ids in config.
- **canopy's token** is a personal access token the operator mints in Louvre, tied to their account and one
  namespace (say `canopy/operator`). It lives in an operator-only file the runtime's MCP config reads, never in
  canopy's config, journal, or logs (TRUST_MODEL T2).
- **Scopes**, per token: `read` (read, list, the feed), `publish`, and `comment` (reply, create, resolve). The
  connector's token is `read` only. A worker that publishes holds all three.
- **The namespace** bounds every call: a token cannot read, publish, or comment outside it, which limits what a
  steered worker can leak or deface (T6).
- **Marks.** A comment written with a token is `kind: agent`, on behalf of the operator, and Louvre's pages show it
  so. canopy adds its comment marks (D069) to the body as well, so its own replies never read as authority, whichever
  way they come back.
- **Sharing** is Louvre's alone: who may view or comment on a namespace's artifacts is set by people in Louvre's
  pages, never by a tool.

### canopy's part

A comment on a canopy artifact lands in its ticket's conversation as a message, its passage quoted, and the overseer
treats it like review feedback. canopy decides in code whether it may steer a worker.

**A channel in §22.**

| Channel | In | Out | Proves the author by |
|---|---|---|---|
| artifacts | comments, from the feed | worker replies, new versions, resolved threads | Louvre `author.id`s the operator lists; on the local store, the listener secret (T8) |

**Whose comment counts.**

- Louvre, a listed author: authority, as an authorized replier's tracker comment is.
- Louvre, anyone else: untrusted feedback. It goes on the attention list and reaches a worker only when the operator
  sends it on, as an untrusted reviewer's does (D089).
- `kind: agent`, or a body with every comment mark: never authority, whoever's token wrote it.
- The local store: the operator's own words, written behind the listener secret, so authority, as a plan's comments
  are (§25).

**Config**, private (TRUST_MODEL T7), in the workspace's private file:

```toml
[artifacts]
mcp_server = "louvre"          # or "canopy-artifacts", the local store
namespace = "canopy/operator"
authorized_authors = ["u_ana", "u_raj"]
publish_roles = ["implement"]  # never the private worker or the planner
```

**Private tickets** publish to the local store only, so nothing about one reaches Louvre: §22's rule that a private
ticket writes nothing outside canopy.

**From a comment to work.** The overseer reads the new messages and judges each: a change, a question, or nothing to
do. A change dispatches a worker whose prompt carries the threads with their passages, as Ask for changes does for a
plan (§25). The worker publishes a new version, replies on each thread it addressed, and resolves it. Capacity,
attempt limits, and cooldowns hold as for any run.

**Latency.** A comment is seen on the next tick that reads the feed, and while the loop idles its wait doubles up to
`loop.idle_max_minutes`. If that proves too slow, the connector can run during the wait every
`connect.every_minutes` (M36), and a new comment ends the wait as an operator's message does (§22, Waking the loop).
Still no listener.

**Rendering locally.** The web UI renders journal text as text (D113) and serves a CSP built on that. The local store's
HTML is shown from a second loopback port, its own origin, in a frame sandboxed without same-origin access or network,
behind the listener secret (T8). That is a TRUST_MODEL T8 change, with the operator's approval note.

### Open

- Louvre's design system: public, so canopy's web UI depends on it from npm, or internal, so canopy copies its
  components in through a shadcn registry. An install from git must still build without the organization's registry
  (D046, D079).
- A listed author's reply in a thread an unlisted person opened: authority for the thread, or only for its own words?
- Whether workers comment on passages of their own artifacts (`comment_create`), or only reply and resolve.
- What Louvre keeps of an artifact whose ticket canopy forgets (`canopy forget`): nothing changes, or a mark on it.
- Whether comments on a version older than the latest reach canopy as they are, or only once anchored again on the
  latest.
- Whether Louvre is the name.
