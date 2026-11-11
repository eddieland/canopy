# M73. Questions answered by the operator's own provider

DESIGN §4, §5, §12, §13, §22, §25, and §27, TRUST_MODEL T1, T2, T3, T6, T7, and T8, D003, D009, D016, D023, D124,
D130. Asked for by the operator (2026-11-11): beside their OpenCode subscription, they would like to put some
questions, about a plan or about where canopy stands, to their company's internally hosted provider. Its models are a
lower tier, but a question there carries none of OpenCode's overhead and spends nothing of the subscription. It should
be opt-in, and change nothing for anyone who does not use it. They believe the provider's proxy speaks OpenAI's API;
it takes a JWT from Entra, cached on their machine, as a bearer token. A question must be able to reach MCP tools,
canopy's own reads above all, when it needs them.

Today a question is put to an agent the runtime runs. The operator asks from a session of their own, with the canopy
skill (§13), or has a chore read canopy's reports (§27). Either pays for the runtime's system prompt and every tool's
schema before the question is read, on the subscription's models. Nothing in canopy asks a model directly, and nothing
should inside the harness: the core never calls a model (§4), and opens no connection (T2, D130).

So the question is answered by a separate program canopy ships (§5, D003), which the harness runs as a command and
reads the output of, as it runs a sink or a connector. It is not a second runtime (D009): no role of the loop runs on
it, and it runs none of canopy's agent definitions.

## Stages

Three, each in its own PRs. Stage 1 waits on stage 0, and stage 2 on stage 1 in real use.

- **Stage 0, the provider, read.** The operator's, against their proxy, since no fake says what it speaks. A probe,
  the new member's first command, run by hand, that sends nothing of canopy's: one plain question, and one that offers
  a single tool. It records, for `MEASUREMENTS.md`:
  - whether the proxy answers OpenAI's chat completions, with tool calls, and whether it streams;
  - where the cached token lives and what yields it, a file or a command, how long one lasts, and what a request with
    a lapsed one is answered;
  - the tokens each of the two questions cost, as the proxy counts them, beside the same two asked of a `canopy-chore`
    run on the subscription, which is the overhead this milestone is to save;
  - and whether the runtime itself can be pointed at the proxy as a provider of its own, with that token. If it can,
    `[runtime.models]` already puts a role on it with no code, and the operator says whether the overhead left is
    worth the rest of this milestone.
- **Stage 1, `canopy ask`.**
  - *The keys.* An `[ask]` table, private (T7, D016): the provider's base URL, its model, and the command that prints
    the token. With no table, the default, `canopy ask` says it is not configured and does nothing; no other command,
    the loop, the web UI, the journal, or an install changes: no migration, no row, no prompt, no definition. `canopy
    config show` leaves the keys out, as it leaves every key that names a host or a command.
  - *The command.* `canopy ask [REF] TEXT`, the operator's (§22): refused inside a tick or a run, and no tool serves
    it to an agent. `-` reads the question from stdin; with no TEXT it asks in turn until the terminal closes, each
    question hearing the ones before. With a REF, any subject `canopy show` takes (D075), what `canopy show REF`
    prints, a ticket's plan with it (§25), opens the prompt, so a small model need not find it by a call. The answer
    is printed as text, with control and hidden characters dropped, then the tokens it cost. It is written to no
    journal row and no file, and read by no agent.
  - *The program.* A workspace member, `packages/canopy-ask`, its script `canopy-ask`, run only as a command, through
    `procs`. It alone speaks to the provider, through `canopy-http` (D130): chat completions, bound to the base URL's
    origin, https unless loopback, following no redirect. It has a short prompt of its own, recorded in
    `.agents/sizes.toml`, and no skill, persona, or memory. No SDK of the provider's: one request shape, validated as
    another program's output is (D026).
  - *The token.* The program runs the operator's command, as argv with no shell (D023), and holds what it prints in
    memory: sent only to that origin, never in argv, the environment of a child, a log, or the journal. A request
    refused for a lapsed token runs the command once more. canopy mints none: no login, no refresh token, no Entra
    client. The harness never reads it (T2).
  - *The tools.* The program is an MCP client over stdio alone, of the servers the harness names on its command line,
    never the model. Stage 1 names one: `canopy _mcp --ask`, canopy's read-only reports (§27) and the reads a question
    about a subject needs, `status` and `show`, a ticket's page with its conversation and plan among them. Asked
    with a REF, `show` answers for that subject alone, so text on its page cannot have another ticket's sent with it;
    asked with none, for any. It serves outside a tick, as the operator's own reads run, where canopy's other servers
    list nothing (D124), lists nothing inside a tick or a run, and writes nothing. `canopy-mcp` gains
    the client's half of the protocol, beside the server's (D124). The program has no shell, no file tool, and no web
    tool (D077): a tool is offered by exact name, and anything else a model calls is answered as an error.
  - *Bounds (T3).* The size of everything a request sends, the REF's page and the questions before among it, the
    rounds of tool calls a question may take, the size of a tool's result as the model is given it, the tokens of an
    answer, and the time a question may run, each with a default the `[ask]` table may lower.
    Past one, the program says which and stops.
- **Stage 2, asked from the web UI.** Only once stage 1 is in daily use, and the operator's to cut: a box on a plan's
  page and on the status page that puts the same question, with the page's subject as its REF, and shows the answer
  as text (D113). The listener then starts a process that reaches a provider, which T8 must say first.
- **Not in this milestone:** any role of the loop on the provider (the overseer, workers, planners, reviewers, and
  chores stay on the runtime, D009); the operator's other MCP servers, the tracker's or GitHub's, whose tokens the
  runtime holds (T2); an ask that acts, by any tool that writes; and answers kept, searched, or counted in `canopy
  spend`, which has no price for a provider the company runs.
- **Rejected:** the call from the harness (§4: the core never calls a model, and T2: it opens no connection); the
  provider's SDK or the `mcp` SDK (each its own HTTP stack, D124, D130); MSAL or any login of canopy's own (a
  credential flow in canopy, T2, for a token the operator's tools already cache); the token in canopy's config (a
  secret in a file canopy reads, T2); a runtime adapter so that roles could run on either (AGENTS.md, Do not
  build); and the provider's URL in the workspace file (one commit would send the journal's text to another host, T7).
- **TRUST_MODEL**, in the PR that builds stage 1, which says what it lets canopy do: send what the journal holds to a
  provider the operator names. T1 (the model reads ticket, plan, and run text, all of it data; it has read tools alone,
  so a steered model can do no more than answer wrongly, and its answer is shown as text, authorizes nothing, and enters
  no prompt); T2 (one more shipped program holds a credential, a model provider's, read from the operator's command and
  sent to one origin; the harness reads none); T3 (the bounds above; the provider's spend is the company's, uncounted);
  T6 (a question sends journal text, a private ticket's among it, to the provider named, which is not the runtime's;
  only the operator's private config names it, and with no `[ask]` table nothing is sent; the refusal inside a run reads
  the run's environment, so it stops a mistake, not an unsandboxed run, which runs as the operator and can already read
  the journal and the cached token itself, D076's residual; a sandboxed run cannot read the state directory, the journal
  with it (§24), and what else it is kept from is stage 1's to say); T7 (the `[ask]` keys are private: one runs a
  command, one chooses where text goes); T8 unchanged until stage 2. A `DECISIONS.md` entry with it: the one program
  that calls a model directly, and that no role of the loop runs on it. The design gains a short section for the command
  and its promises, a line in §5 for the member, a sentence in §27 for the server, and §12 the keys, with
  `examples/config.toml`; the guide a page; the operator's skill a row.
- **Tests with the fakes:** a fake provider played through `canopy-http`, as the Slack sink's tests play Slack, and a
  fake token command. With no `[ask]` table, the command refuses and the journal, the config report, and a dry tick
  are as before. A question answered with no tool call; one answered after a call of a report; a REF's page in the
  prompt; a tool the server does not list answered as an error; each bound stopping a question and saying which; a
  lapsed token fetched once more, and a second refusal reported; the token in no argv, log, or output; a redirect
  not followed, and plain http to another host refused; a reply that is not the shape expected reported, not
  crashed on; the command refused inside a tick and a run; `canopy _mcp --ask` listing nothing there, and writing
  nothing; the client's half of `canopy-mcp` against its own server; `[ask]` refused in the workspace file;
  `test_layers.py` for the new member and `test_prompt_sizes.py` for its prompt; `make install-check` with the member
  installed.

Accept: Stage 0's findings in `MEASUREMENTS.md`, from the operator's proxy, with their call recorded on the `Status:`
line before stage 1 starts: build it, or point the runtime at the proxy and stop. Live, once stage 1 is built: the
operator asks where canopy stands and is answered from the internal provider, with their OpenCode subscription's
spend unchanged in `canopy spend`; asks about a real plan by its ticket, and is answered from the plan's text; asks
something only a report holds, and the answer comes after a tool call; a question asked an hour after the last still
answers, on a fresh token; a second workspace of theirs with no `[ask]` table behaves as before; and the tokens of
the first two questions are in `MEASUREMENTS.md` beside stage 0's.

Status: not started. Drafted 2026-11-11 at the operator's ask, from the design and the servers as they stood; nothing
of the proxy was read, so that it speaks OpenAI's API, and how its token is cached, are the operator's account, for
stage 0 to confirm. Chosen conservatively, for the operator to change: the names (`canopy ask`, `[ask]`,
`canopy-ask`); a command that prints the token, rather than a path to the cache; canopy's own reads as the only tools;
a ticket's conversation among them, which a chore's reports leave out (§27); nothing kept of a question or its
answer; and the web UI last.
