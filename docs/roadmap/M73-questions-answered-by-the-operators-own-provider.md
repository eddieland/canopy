# M73. Questions answered by the operator's own provider

DESIGN §4, §5, §12, §13, §22, §25, and §27, TRUST_MODEL T1, T2, T3, T6, T7, and T8, D003, D009, D016, D023, D124,
D130. Asked for by the operator (2026-11-11): beside their OpenCode subscription, they would like to put some
questions, about a plan or about where canopy stands, to their company's internally hosted provider. Its models are a
lower tier, but a question there carries none of OpenCode's overhead and spends nothing of the subscription. It should
be opt-in, and change nothing for anyone who does not use it. They believe the provider's proxy speaks OpenAI's API;
it takes a JWT from Entra, cached on their machine, as a bearer token. A question must be able to reach MCP tools,
canopy's own reads above all, when it needs them. Said since (2026-11-12): it is a feature of the web UI, a box where
they ask about canopy's status, a ticket, or a plan; skipping the runtime is the point, its system prompt, its tools'
schemas, and its start-up among what a question must not pay for, so an answer arrives with no runtime started; and
it replaces none of the loop's agents.

Today a question is put to an agent the runtime runs. The operator asks from a session of their own, with the canopy
skill (§13), or has a chore read canopy's reports (§27). Either pays for the runtime's system prompt and every tool's
schema before the question is read, on the subscription's models, and waits for a runtime to start. Nothing in canopy
asks a model directly, and nothing should inside the harness: the core never calls a model (§4), and opens no
connection (T2, D130).

So the question is answered by a separate program canopy ships (§5, D003), which the harness runs as a command and
reads the output of, as it runs a sink or a connector. It is not a second runtime (D009): no role of the loop runs on
it, and it runs none of canopy's agent definitions.

## Stages

Four, each in its own PRs, in order. The milestone is done when the box answers, stage 2; stage 3 follows it.

- **Stage 0, the provider, read.** The operator's, against their proxy, since no fake says what it speaks. It
  confirms what stage 1 depends on; it does not decide whether stage 1 is built. A script run by hand and not shipped,
  its text kept with the measurement, so `packages/canopy-ask` starts in stage 1 with the request's shape known. It
  sends nothing of canopy's: one plain question, and one that offers a single tool. It records, for `MEASUREMENTS.md`:
  - whether the proxy answers OpenAI's chat completions, with tool calls; whether it streams, and whether a streamed
    reply carries its token counts;
  - the time to the first token and to the whole answer, which the box's live check is held to;
  - where the cached token lives and what yields it, a file or a command, how long one lasts, and what a request with
    a lapsed one is answered;
  - the tokens each of the two questions cost, as the proxy counts them, beside the same two asked of a `canopy-chore`
    run on the subscription: the saving the bypass is for;
  - and, as a fact, that the runtime can be pointed at the proxy as a provider of its own, which the operator says it
    can (2026-11-12). That is outside this milestone and no reason to stop: a chore's own `model` key can already put
    a chore there with no code, but a runtime still starts for each question.
- **Stage 1, `canopy ask`, with no tools.** The seam the web UI is built on, and what the fakes test without a
  browser.
  - *The keys.* An `[ask]` table, private (T7, D016): the provider's base URL, its model, and the command that prints
    the token. With no table, the default, `canopy ask` says it is not configured and does nothing; no other command,
    the loop, the web UI, the journal, or an install changes: no migration, no row, no prompt, no definition. `canopy
    config show` leaves the keys out, as it leaves every key that names a host or a command.
  - *The command.* `canopy ask [REF] TEXT`, the operator's (§22): refused inside a tick or a run, and no tool serves
    it to an agent. `-` reads the question from stdin. One question, one answer: it keeps no earlier turn. With a
    REF, any subject `canopy show` takes (D075), what `canopy show REF` prints, a ticket's plan with it (§25), opens
    the prompt; with none, what `canopy status` prints. One request, and no tool. The answer is written to no journal
    row and no file, and read by no agent.
  - *Its output.* The answer is printed as it arrives, where stage 0 finds the proxy streams, as text with control
    and hidden characters dropped, chunk by chunk, then the tokens it cost. With `--json`, a line for each event: a
    piece of the answer, its end with the tokens, or a refusal with its kind (not configured, a bound passed, the
    token's command failed, the provider's error), which the web's server reads as another program's output (D026).
  - *The program.* A workspace member, `packages/canopy-ask`, its script `canopy-ask`, run only as a command, through
    `procs`. It alone speaks to the provider, through `canopy-http` (D130): chat completions, bound to the base URL's
    origin, https unless loopback, following no redirect. It has a short prompt of its own, recorded in
    `.agents/sizes.toml`, and no skill, persona, or memory. No SDK of the provider's: one request shape, validated as
    another program's output is (D026). It has no shell, no file tool, and no web tool (D077).
  - *The token.* The program runs the operator's command, as argv with no shell (D023), and holds what it prints in
    memory: sent only to that origin, never in argv, the environment of a child, a log, or the journal. A request
    refused for a lapsed token runs the command once more. canopy mints none: no login, no refresh token, no Entra
    client. The harness never reads it (T2).
  - *Bounds (T3).* The size of everything a request sends, the REF's page among it, the tokens of an answer, and the
    time a question may run, each with a default the `[ask]` table may lower. Past one, the program says which and
    stops.
- **Stage 2, the box in the web UI.** The feature. On the status page, a ticket's page, and a plan's page, a box
  that puts the operator's question, the page's subject as its REF, the status page's with none.
  - With no `[ask]` table there is no box, and the API has no ask to serve: the UI of anyone who has not opted in is
    as it was.
  - Only the operator's action starts an ask: a write, which the session, its token, and the Origin check guard as
    any write (T8), never a page load, a link, or text on a page. The server passes the question and the REF to
    `canopy ask`, and nothing else: it never reads the token and never names the provider, which stay with the
    program and the private config.
  - The answer comes back as that write's reply, a piece at a time, so the page shows it as it arrives and a page
    closed or left ends the request, and the ask's process with it. No second channel is added for it.
  - It is shown as text (D113), no Markdown, set apart and marked as a model's answer, so it cannot pass for the
    journal's text beside it. Nothing is kept: a reload loses it, and a follow-up hears no earlier turn. Kept
    answers, or turns a page holds, would be new text to guard, and are the operator's to ask for.
  - *Bounds (T3).* Two asks at once for a workspace, a third refused with a line saying so; each still held to
    stage 1's bounds.
  - `ui/AGENTS.md` holds what the stage owes: unit tests and a spec for the box, `ui/DESIGN.md` for where it sits,
    and a guide page in the guide's voice.
- **Stage 3, tools, for questions that span tickets.** What the operator asked for, after the box rather than before
  it: tool calling is where a lower-tier model is least reliable, and a page's question is mostly answered from its
  subject in the prompt. Mainly the status page's gain.
  - The program becomes an MCP client over stdio alone, of the servers the harness names on its command line, never
    the model. It names one: `canopy _mcp --ask`, canopy's read-only reports (§27) and `status` and `show`, a
    ticket's page with its conversation and plan among them, each the function its command prints from (D124).
    `canopy-mcp` gains the client's half of the protocol, beside the server's.
  - Asked with a REF, `show` answers for that subject alone, so text on its page cannot have another ticket's sent
    with it; asked with none, for any.
  - The server serves outside a tick, as the operator's own reads run, where canopy's other servers list nothing
    (D124); lists nothing inside a tick or a run; and writes nothing. It cannot tell the operator's ask from another
    process running as the operator, whether a terminal or the web's server started it: it serves what `canopy show`
    and `canopy status` already print to any such process, and nothing more.
  - A tool is offered by exact name, and anything else a model calls is answered as an error. Two more bounds: the
    rounds of tool calls a question may take, and the size of a tool's result as the model is given it.
- **Not in this milestone:** any role of the loop on the provider (the overseer, workers, planners, reviewers, and
  chores stay on the runtime, D009); the operator's other MCP servers, the tracker's or GitHub's, whose tokens the
  runtime holds (T2); an ask that acts, by any tool that writes; a conversation in the terminal; and answers kept,
  searched, or counted in `canopy spend`, which has no price for a provider the company runs.
- **Rejected:** the call from the harness (§4: the core never calls a model, and T2: it opens no connection); the
  runtime pointed at the proxy with a lean agent (it saves the subscription, not the runtime's start-up or its
  prompt, and gives no answer within a page's patience); the provider's SDK or the `mcp` SDK (each its own HTTP
  stack, D124, D130); MSAL or any login of canopy's own (a credential flow in canopy, T2, for a token the operator's
  tools already cache); the token in canopy's config (a secret in a file canopy reads, T2); a runtime adapter so that
  roles could run on either (AGENTS.md, Do not build); the provider's URL in the workspace file (one commit would send
  the journal's text to another host, T7); and the call from the browser (the token and the provider's address would
  reach the page).
- **TRUST_MODEL**, changed by the PRs that build stages 1 and 2, each saying what it lets canopy do: send what the
  journal holds to a provider the operator names, and start that from the web UI.
  - T1: the model reads ticket, plan, and run text, all of it data. It has no tool in stages 1 and 2 and read tools
    alone in stage 3, so a steered model can do no more than answer wrongly. Its answer is shown as text, marked as
    a model's beside the journal's own, authorizes nothing, and enters no prompt.
  - T2: one more shipped program holds a credential, a model provider's, read from the operator's command and sent to
    one origin; the harness and the web's server read none.
  - T3: the bounds above; the provider's spend is the company's, uncounted.
  - T6: a question sends journal text, a private ticket's among it, to the provider named, which is not the
    runtime's; only the operator's private config names it, and with no `[ask]` table nothing is sent. The refusal
    inside a run reads the run's environment, so it stops a mistake, not an unsandboxed run, which runs as the
    operator and can already read the journal and the cached token itself, D076's residual; a sandboxed run cannot
    read the state directory, the journal with it (§24), and what else it is kept from is stage 1's to say.
  - T7: the `[ask]` keys are private, and no write of the web's sets them (D128): one runs a command, one chooses
    where text goes.
  - T8, in stage 2's PR: the listener starts a process that sends journal text to a host off the machine, which it
    has never done; only for a write the session check accepted, as it runs the operator's dictation command; with
    the question and the REF alone, each validated, the question bounded; never more than two at once; and the
    answer served to that session, as text. A stolen session can ask, and so spend the provider's tokens and read
    what an answer says of the journal, which it could already read page by page: the residual.

  A `DECISIONS.md` entry with stage 1: the one program that calls a model directly, and that no role of the loop runs
  on it. The design gains a short section for the command, the box, and their promises, a line in §5 for the member,
  a sentence in §27 for the server with stage 3, and §12 the keys, with `examples/config.toml`; the operator's skill a
  row.
- **Tests with the fakes:** a fake provider played through `canopy-http`, as the Slack sink's tests play Slack, and a
  fake token command.
  - Stage 1: with no `[ask]` table, the command refuses and the journal, the config report, and a dry tick are as
    before; a REF's page in the prompt, and the status with none; an answer streamed and one whole; each event of
    `--json`, each refusal's kind among them; a control character dropped across two chunks; each bound stopping a
    question and saying which; a lapsed token fetched once more, and a second refusal reported; the token in no argv,
    log, or output; a redirect not followed, and plain http to another host refused; a reply that is not the shape
    expected reported, not crashed on; the command refused inside a tick and a run; `[ask]` refused in the workspace
    file; `test_layers.py` for the new member and `test_prompt_sizes.py` for its prompt; `make install-check` with
    the member installed.
  - Stage 2, through the web's mock `backend` and the UI's own tests: no box and no route's answer with no `[ask]`
    table; the route refused without the session's token, as any write; the question and the REF alone passed on; an
    answer shown as it arrives, as text, marked as a model's; a refusal shown as its line; a third ask at once
    refused; the ask's process ended when its request is closed.
  - Stage 3: a question answered after a call of a report; a tool the server does not list answered as an error;
    `show` refused for another subject when a REF was given; the two bounds; `canopy _mcp --ask` listing nothing
    inside a tick or a run, and writing nothing; the client's half of `canopy-mcp` against its own server.

Accept: Stage 0's findings in `MEASUREMENTS.md`, from the operator's proxy, and on the `Status:` line that it speaks
what stage 1 needs, before stage 1 starts. Live, once stage 2 is built: the operator asks where canopy stands from
the status page, and about a real ticket and a real plan from their pages, and is answered there from the internal
provider, each answer starting within a time the operator names once stage 0 has measured the proxy; their OpenCode
subscription's spend is unchanged in `canopy spend`; a question asked an hour after the last still answers, on a
fresh token; a second workspace of theirs with no `[ask]` table shows no box and behaves as before; and the tokens
of two questions are in `MEASUREMENTS.md` beside stage 0's. Stage 3's, after: the operator asks something that spans
tickets and only a report holds, and the answer comes after a tool call.

Status: not started. Drafted 2026-11-11 at the operator's ask, from the design and the servers as they stood; nothing
of the proxy was read, so that it speaks OpenAI's API, and how its token is cached, are the operator's account, for
stage 0 to confirm. Reshaped 2026-11-12 on what the operator said since: the runtime can be pointed at the proxy,
and the feature is still to bypass it and be asked from the web UI. Chosen conservatively, for the operator to
change: the names (`canopy ask`, `[ask]`, `canopy-ask`); a command that prints the token, rather than a path to the
cache; no tools until the box answers, an order and not a cut; canopy's own reads as the only tools then, a ticket's
conversation among them, which a chore's reports leave out (§27); and nothing kept of a question or its answer.
