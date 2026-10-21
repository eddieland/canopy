# M62. Artifacts, and comments on them back to the ticket

REQUIREMENTS R26, DESIGN §38, §22, §25, §30, and §35, TRUST_MODEL T1, T6, T7, and T8, D003, D069, D089. Asked for by
the operator (2026-10-17): workers publish artifacts people comment on, to Louvre, a hosted platform that is its own
program, or to a local store canopy ships, through the same MCP tools, and the comments come back to the ticket.
Stages 1 and 2 need nothing; stage 3 needs M36 and M37. Four stages, in order, each in its own PRs.

- **Stage 1, the local store.** A workspace member under `packages/` serving the tools below over stdio, with versions,
  anchors, and the comment feed, its artifacts under the state directory and out of the journal. Louvre builds the
  same contract in its own repository; canopy's tests run against the local store and a fake of the feed.
- **Stage 2, publishing.** A skill for the tools, `[artifacts]` in the private file, and the definitions of the roles
  `publish_roles` names allowing the tools by name; never the planner or a private ticket's worker, whose definitions
  deny the Louvre server by name. TRUST_MODEL T6, its PR saying what the change lets the loop do.
- **Stage 3, comments back (needs M36 and M37).** An `artifacts` source kind beside `tracker` and `vcs` (§30), run on
  the same schedule, reading the feed past its cursor and printing each change as an observation, with §30's `end`
  line. Each comment reaches its ticket's conversation in code as a tracker comment does (§35), quoting its passage;
  `authorized_authors` and the comment marks decide authority in code, and an unlisted author's comment is an
  attention item until the operator sends it on. TRUST_MODEL T1.
- **Stage 4, plans as artifacts.** A plan is an artifact in the local store, and the plan editor's threads are artifact
  threads.
- Rendering the local store's HTML in the web UI, from a second loopback origin in a sandboxed frame: TRUST_MODEL T8,
  in whichever stage first shows an artifact.
- Tests with the fakes: a new version keeps a thread's anchor, and a reworded passage reads `passage_gone`; the feed's
  cursor misses no change and repeats none across pages; a feed cut off before its `end` line keeps what was observed;
  a listed author's comment reaches the conversation as authority, an unlisted one's as an attention item, and one
  marked as an agent's or with every comment mark as neither; a private ticket's worker has no Louvre tools.

## The contract

What Louvre and the local store both serve. It moves to the store's own documentation once one is built.

| Record | Fields |
|---|---|
| Artifact | `id`, `title`, `namespace`, `origin` (at most 16 string pairs; canopy sets `canopy.workspace`, `canopy.ticket`, `canopy.run`), `latest_version` |
| Version | `artifact_id`, `n`, `content_type` (`text/html`, `text/markdown`), `sha256`, `text` (the rendered page's visible text, what anchors resolve against); immutable |
| Thread | `id`, `artifact_id`, `anchor` (none for the whole artifact), `anchored_version`, `state` (`open`, `resolved`) |
| Comment | `id`, `thread_id`, `seq`, `author`, `body` (at most 4,000 characters), `created_at`, `edited_at`, `deleted_at`, `via` (`web`, `mcp`) |
| Author | `id` (stable, from the store's sign-in), `display_name`, `kind` (`person`, `agent`), `on_behalf_of` |

An anchor is a W3C Web Annotation `TextQuoteSelector` over the version's `text`, whitespace collapsed: `exact`, and
`prefix` and `suffix` of at most 32 characters, as a plan's comments are. HTML anchors are taken inside the sandboxed
frame and checked against `text`, never markup.

| Tool | Input | Returns | Writes |
|---|---|---|---|
| `artifact_publish` | `title`, `content_type`, `content`, `origin`, `artifact_id` (to add a version) | `artifact_id`, `version`, `url` | yes |
| `artifact_read` | `artifact_id`, `version` | metadata, `content`, `text` | no |
| `artifact_list` | an `origin` filter, `cursor` | artifacts, newest first, paged | no |
| `thread_list` | `artifact_id`, `state`, `version` | threads, comments, each anchor's status (`found`, `passage_gone`) | no |
| `comment_feed` | an `origin` filter, `since`, `limit` (at most 200) | the changes after `since`, then an `end` line | no |
| `comment_reply` | `thread_id`, `body` | `comment_id`, `seq` | yes |
| `comment_create` | `artifact_id`, `anchor`, `body` | `thread_id`, `comment_id`, `seq` | yes |
| `thread_resolve` | `thread_id`, `resolved` | `state` | yes |

A refusal is a tool error with a code: `not_found`, `out_of_scope` (outside the token's namespace), `too_long`,
`anchor_not_found`, `read_only`. No tool deletes an artifact or shares one. The local store speaks stdio and opens no
socket; Louvre speaks MCP's streamable HTTP behind its token.

- **The feed's cursor.** `seq` is one sequence across the store, given in commit order to every change (a comment
  created, edited, or deleted; a thread resolved or reopened), and only once the change is visible, so nothing appears
  below a cursor a reader has passed. A deleted comment keeps its row with its body empty.
- **Each page** holds at most `limit` changes, oldest first, and ends `{"kind": "end", "through": <seq>}`; a page
  without one is incomplete. A change carries ids, the thread's anchor and state, the author, `via`, times, and the
  body, never the artifact's content.
- **Tokens.** The operator mints canopy's token in Louvre, bound to their account and one namespace, with scopes `read`,
  `publish`, and `comment`; the source's is `read` only. It lives in an operator-only file the runtime's MCP config
  reads, never in canopy's config, journal, or logs (TRUST_MODEL T2). A comment written with it is `kind: agent`, and
  canopy adds its comment marks (D069) too.

```toml
[artifacts]  # private (TRUST_MODEL T7)
mcp_server = "louvre"          # or the local store's
namespace = "canopy/operator"
authorized_authors = ["u_ana", "u_raj"]
publish_roles = ["implement"]
```

Accept: written with the design, before work starts. Live, once built: a worker publishes an artifact to Louvre for a
ticket, a listed author comments on a passage, the comment reaches the ticket's conversation, and a worker publishes a
new version that answers it, replies, and resolves the thread; an unlisted author's comment waits on the attention
list.

Status: not started.
