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

What Louvre and the local store both serve, in full: records, anchors, tools, refusal codes, the comment feed, and
Louvre's tokens. Once stage 1 built the store, it moved to the store's README,
[packages/canopy-artifacts](../../packages/canopy-artifacts/README.md). Stage 2's config:

```toml
[artifacts]  # private (TRUST_MODEL T7)
mcp_server = "louvre"          # or the local store's
namespace = "canopy/operator"
authorized_authors = ["u_ana", "u_raj"]
publish_roles = ["worker"]     # an agent, as runtime.allow_bash names one
```

Accept: written with the design, before work starts. Live, once built: a worker publishes an artifact to Louvre for a
ticket, a listed author comments on a passage, the comment reaches the ticket's conversation, and a worker publishes a
new version that answers it, replies, and resolves the thread; an unlisted author's comment waits on the attention
list.

Status: in progress. Stage 1 is built (2026-10-22): `canopy-artifacts serve`, the local store, serves the eight
tools over stdio from a directory of the operator's, with versions, anchors, and the feed, and the contract is its
README. Every comment through its tools is an agent's on the operator's behalf; people's comments wait for the web
channel. Stage 2 is built (2026-10-22): `[artifacts]` in the private file, the `canopy-artifacts` skill, and the public
worker, the one agent `publish_roles` may name, allowed the store's tools by exact name, but the feed; every other
definition denies the server whole, and the store's skill with it. `publish_roles` names agents, not run kinds: a
definition serves every kind its agent runs. Stage 3 is next, once M36 and M37 are done.
