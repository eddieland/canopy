# Artifacts

Part of the canopy design, normative like all of it: pages workers publish for people to read, the comments people
leave on them, and how those comments come back to a ticket. Sections are numbered across the whole design; the
[README](README.md) has the map. Previous: [The harness decides](HARNESS_DECIDES.md). Next: [A tick without the
overseer](WITHOUT_THE_OVERSEER.md).

## 38. Artifacts and Louvre

The local store, publishing from runs, and comments back to the ticket are built (ROADMAP M62). On the local store
canopy names an artifact's workspace, ticket, and run from the run that publishes it, in the environment the runtime
starts the store's server with, so the worker does not choose them. Louvre's server is reached over the network and
is not given the run, so there the ticket a comment reaches is still the publishing worker's word.

An **artifact** is a page a worker publishes for people to read: a report, a design, an HTML mock-up. People comment
on its passages, and the comments come back to the ticket that produced it, where they count as review feedback does.
An artifact lives in one of two **stores** that serve the same MCP tools:

- **Louvre**, a hosted artifact platform for the operator's organization: a separate program, in its own repository,
  with its own sign-in, deployment, and security model. canopy does not build, ship, or run it; this section says what
  canopy needs of it.
- **The local store**, a workspace member canopy ships (D041), for the operator alone. Its artifacts sit under the
  operator-only state directory (D053), outside the journal, since nothing a worker writes reaches the journal while
  it runs (§27).

### Principles

- **canopy pulls; Louvre never calls canopy.** No listener for an outside system (§3, TRUST_MODEL T8): canopy reads
  comments on its own schedule, as it reads the tracker. Louvre may offer webhooks to others; canopy does not use them.
- **Authority stays with the source (§22, D072).** A comment is Louvre's fact. Whether it may steer a worker is decided
  by canopy, in code, from the author's Louvre identity, never by Louvre.
- **One tool surface, two stores.** The tools are the same against Louvre or the local store, so a skill written for one
  works against the other; only the MCP server the runtime's config names differs. The harness imports neither (D003).
- **Untrusted content stays contained.** An artifact's HTML and a comment's text are text, never instructions
  (TRUST_MODEL T1). HTML renders only on an origin of its own, in a sandboxed frame.

### The round trip

```text
Louvre (hosted)                         canopy (the operator's machine)

someone comments on a passage
        |
comment feed (every change, by seq) --> the artifacts source reads it (§30)
                                                |
                                        author listed? (checked in code) --no--> attention list
                                                | yes                              | the operator sends it on
                                        ticket conversation  <---------------------+
                                        (a message, its passage quoted)
                                                |
artifact updated  <---------------------- a worker revises it
(new version, reply, thread resolved)
```

### What canopy needs of a store

The contract in full, field by field and tool by tool, is the local store's README
([packages/canopy-artifacts](../../packages/canopy-artifacts/README.md)). What canopy relies on:

- **Versions and origin.** A revision is a new version of the same artifact, so its threads carry over. Each artifact
  carries origin keys canopy sets (workspace, ticket, run), opaque to the store, which a reader filters on.
- **Anchors by words.** A thread is anchored by its passage's words and the text either side, as a plan's comments are
  (§25), never by a position. On a new version a thread is looked for again by its words; one not found is
  `passage_gone` and never moves to other words.
- **A comment feed.** Every change to a comment or thread, under an origin filter, after a cursor that only goes up and
  leaves no gap behind it, paged, and ending with an `end` line naming what it covered: §30's connector contract, so a
  feed cut short never reads as comments gone.
- **Who wrote it.** Each comment's author is an id the store authenticated, stable for the life of the account, and a
  comment written with a token is marked as an agent's, on behalf of the person who minted it.
- **Tokens bound to a namespace.** canopy's token reads, publishes, and comments only within its namespace, which
  bounds what a steered worker can leak or deface (TRUST_MODEL T6). No tool deletes an artifact or changes who may see
  it: people do that in Louvre.

### canopy's part

Artifacts are a channel (§22). Comments come in through an `artifacts` source, a connector beside the tracker's and
GitHub's (§30), polled between ticks as they are, and reach the conversation in code as tracker comments do (§35),
each quoting its passage. The overseer judges each as it judges review feedback; a worker that acts on them publishes
a new version, replies on the threads it addressed, and resolves them.

- **Whose comment counts.** Louvre authors the operator lists, in private config (TRUST_MODEL T7), are authority, as an
  authorized replier's comment is: shown to the overseer with the operator's messages, citable by a `resume` for
  `reply`, and heard by the worker. Anyone else's is untrusted feedback that waits on the attention list until the
  operator sends it on in a reply (D089). A comment marked as an agent's, or carrying every comment mark (D069), is
  never authority, nor is any comment on a private ticket, which only the operator authorizes (§22). Each comment
  counts by its own author, decided in code from the store's id. On the local store, comments are the operator's,
  behind the listener secret (T8).
- **Which runs publish.** Only the agents the operator names in private config hold the tools, each by its exact
  name, and every other definition denies the store's server whole. Never the planner or a private ticket's worker,
  so nothing of a private ticket reaches a store (§22).
- **Rendering locally.** The web UI renders journal text as text (D113). The local store's HTML is served from a second
  loopback origin, in a frame sandboxed without same-origin access or network, behind the listener secret (T8).

### Open

- Louvre's design system: public, so the web UI depends on it from npm, or internal, so canopy copies its components
  in. An install from git must still build without the organization's registry (D046, D079).
- A listed author's reply in a thread an unlisted person opened: authority for the thread, or only for its own words.
  Until settled, only its own words.
- What Louvre keeps of an artifact whose ticket canopy forgets (`canopy forget`).
- Whether Louvre is the name.
- Whether a private ticket may publish to the local store alone, which needs a second server in config.
