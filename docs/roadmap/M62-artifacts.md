# M62. Artifacts, and comments on them back to the ticket

REQUIREMENTS R26, DESIGN §38, §22, §25, §30, and §35, TRUST_MODEL T1, T6, T7, and T8, D003, D069, D089. Asked for by
the operator (2026-10-17): workers publish artifacts people comment on, to Louvre, a hosted platform that is its own
program, or to a local store canopy ships, through the same MCP tools, and the comments come back to the ticket.
Stages 1 and 2 need nothing; stage 3 needs M36 and M37. Three stages, in order, each in its own PRs.

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
- **Plans stay canopy's.** A fourth stage, plans as artifacts, was dropped at the operator's word (2026-10-24). A plan
  stays §25's Markdown file, its threads in the journal, for operators who use no store and those who prefer canopy's
  editor. Buy-in from others comes after the plan: an artifact a worker publishes when the operator asks for one, the
  worker then ending `blocked` until they reply. Whether buy-in holds the `implement` in code, or is asked as a Louvre
  decision, waits on that being tried on a real ticket.
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
definition serves every kind its agent runs. Stage 3 started (2026-10-23) ahead of M37, at the operator's word, with
the half that needs only M36: the `artifacts` source, `canopy-artifacts feed` for the local store, run after the `vcs`
source each tick and poll, reads the feed past its cursor into `observed_artifact_threads` and
`observed_artifact_comments`, in shadow, recording its runs, raising `connector_failed`, and named in `canopy status`
with the change it has read through. Each change says whether its passage is in the latest version, so a reworded one
reads `passage_gone`. Chosen conservatively: a refused change holds the cursor before it, so the feed waits on it with
`connector_failed` until a run reads it, rather than skipping it; a run reads at most 1,000 changes, the next reading
on; and a thread's `passage_gone` is seen only when a change to it is read, since a new version is no change.
Built (2026-10-24), on M37's comments recorded in the conversation: each comment on an artifact whose origin names a
ticket the journal holds reaches that ticket's conversation once, as first read, quoting its passage, source
`artifact` (or `worker` when it carries the workers' marks) on the channel `artifacts`, as data that authorizes
nothing. Chosen conservatively: a ticket the journal lacks gets none, since the origin is the worker's word; a comment
first read deleted is not recorded; and the passage is quoted cut to 300 characters.
Built (2026-10-24): `authorized_authors` and the comment marks decide authority in code, read as config says now, as
`trust.authorized_repliers` is. On a public ticket a listed person's comment is authority as an authorized reply is:
the overseer is shown it in the ticket's `operator` key as `artifact_comments`, a `resume` for `reply` may cite it by
its message (`message=`), the derivation reads it as `human_replied`, and the public worker hears it with the
operator's messages, marked an instruction. A comment the store marks an agent's, or with every comment mark, is
neither authority nor an item; anyone else's raises `untrusted_artifact_comment` about its ticket, harness-raised,
naming its authors and never its text, until the operator replies on the ticket after it. Chosen conservatively: a
private ticket's comments are never authority, a listed author's included, and each person's raises the item; a
comment deleted since counts for nothing; a verb's instruction, such as `canopy send`'s, sends nothing on; and a
listed author's reply in an unlisted person's thread is authority for its own words only, §38's open question.
Built (2026-10-24): canopy setting an artifact's ticket per run. Each run whose agent `publish_roles` lets publish is
given `CANOPY_ARTIFACT_ORIGIN`, its workspace, ticket, and run as a JSON object, which OpenCode passes to a local MCP
server (read in 1.19.3's and 2.1.4's source), and `canopy-artifacts serve` sets those pairs over the worker's, under
its own `--origin`'s. Chosen conservatively, for the operator to change: the feed reader does not check the run's pairs
against the journal, since a store that sets them leaves the worker none to forge; a private ticket's worker and the
planner are given none; and how Louvre takes them is Louvre's, through its MCP config. Left: the live check in Accept.
