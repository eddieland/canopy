# M58. canopy chooses each agent's model

REQUIREMENTS R23, DESIGN §13 (Each agent's model), §8, §11, §12, §14, §21, §22, and §25, TRUST_MODEL T1, T5, T7, and T8,
D026, D040. Needs M33 and M44. Asked for by the operator (issue #418): canary a model change by running one ticket on
another model and comparing the result. Today a worker's model is OpenCode's default unless the operator adds a model
option to `runtime.worker_cmd` or `worker_cmd_suffix` (§12), which every worker run then takes, which each operator
repeats in their own template, sandboxed ones included, and which nothing records: the journal cannot say which model a
run used. Designed in §13, beside where the runtime finds canopy's definitions.

In practice (the operator, 2026-10-19): every `runtime` command template carries a model option set by hand, and since
nothing records it, the operator cannot tell which model did which run, or say whether one model works better than
another. Recording each run's model, with `canopy spend` split by it, is what answers that; the per-ticket override is
for the canary after it.

- **Stage 0, a source read.** Of the pinned OpenCode (1.19.3), recorded on the `Status:` line: what `opencode models`
  prints, for which providers, how it fails when a provider cannot be reached, and whether it needs the network; that a
  `model:` key in an agent's frontmatter is the model `opencode run --agent` uses, and which wins when the command line
  also passes `--model`; and whether any `--format json` event names the model that served a call. Issue #275 found
  that `step_start` and `step_finish` carry only ids, snapshot, cost, and tokens, and that the session stores each
  message's `providerID` and `modelID`, which `opencode export` prints; Stage 0 confirms both on the pinned version.
- **Every agent** (the operator, 2026-10-19): `worker` (the public and the private worker), `planner`,
  `reviewer`, `overseer`, and `chore` (§13, Each agent's model).
- **canopy sets the model, not the template.** When `core/definitions.py` renders a run's snapshot, it writes a
  `model:` key into the frontmatter of each agent's definitions, as it renders the rebase rules and the private
  worker's tracker tools today. The digest covers the rendered text, so each set of models gets its own immutable
  snapshot (D040), and a run's snapshot names the model it asked for. The templates stay as they are, so custom and
  sandboxed templates keep working, though a template's `--model` beats the definition's `model:` (§13, Each agent's
  model), so a `--model` in any `runtime` template or the worker prefix or suffix is a config error naming
  the key and the `runtime.models` key to set instead. No model set renders no key: the runtime's default, as today,
  which is config's `model` or else the model the operator last picked in OpenCode's TUI.
- **A default per agent.** `[runtime.models]`, one `provider/model` id per agent name, each empty by default, private
  as every `runtime` key is (T7), so a shared workspace file cannot choose what the operator's spend buys.
- **The operator's override per ticket.** `canopy model KEY provider/model` for the ticket's workers, `--agent NAME`
  for its planner or reviewer, and `--clear`, a journal fact on the ticket and agent, which may be
  set before canopy has seen the ticket and outlasts `canopy forget`. It covers every run of that agent for the ticket
  until it is cleared, so a canary ticket stays on one model. The overseer and chores work on no one ticket and take
  only their default. Like `stop`, `reply`, and `grant`, it refuses as `inside_run` when `CANOPY_TICK_ID` or
  `CANOPY_RUN_ID` is set, so no agent chooses a model, and `canopy dispatch` gets no model flag: a model is the
  operator's setting, never an agent's choice.
- **The web UI's control** (the operator, 2026-10-19): the ticket page's Model panel shows each of the ticket's
  agents' next model and where it comes from, and sets or clears the override through `canopy model`'s function, its
  choices read from `opencode models` when the control opens (T8). The settings page shows `[runtime.models]`
  read-only, since config stays the operator's file to edit until M41 writes it.
- **What OpenCode has.** Models come and go, so canopy reads the list from OpenCode rather than holding one:
  `opencode models`, through `infra/procs.py` in the workspace root with a 30-second timeout, its output validated
  (D026). `canopy models` prints it.
  It works offline, from OpenCode's cache or the catalog built into it, and reaches no provider for most, so a listed
  model can still fail when called. Setting an override refuses a model the list does not hold. Each run's start
  checks its model again (each dispatch, review, chore, and a tick's overseer), since the list may have changed: a
  model that is gone refuses the run as `model_missing`, and a read that fails as `model_list_failed`, each with an
  attention item of its name. OpenCode itself would refuse that run before its first call and exit 1, never falling
  back, so the check turns a failed run into an attention item and keeps the slot. Config load never reads the list,
  so it stays fast.
- **Recorded on the run, as the session says** (the operator, 2026-10-20). No event names the model a call went to;
  the session records it for each message, and `opencode export` prints it (§13). After each live tick canopy reads a
  few ended runs' sessions, the newest never-read first, past runs among them, and records each model that wrote a
  run's replies with what they cost, so runs on the runtime's default and on a template's own `--model` are attributed
  too, and a run on two models splits between them. `canopy spend` breaks each kind's cost down by model (built,
  2026-10-20); `canopy status` and the web UI's run, review, chore, and tick pages show it.
- **Out of scope** (issue #418): two models side by side on one ticket, since one worker per ticket stays; the overseer
  or a ticket's labels choosing a model; comparison reports beyond the spend split.
- **TRUST_MODEL**, in the PR that builds it: T1 (every agent's model is the operator's choice alone, from config, the
  override, or the ticket page's control; no agent sets one, the overseer's own included, and `canopy model` refuses
  inside a run), T5 (a run records what canopy asked for), T7 (`runtime.models` private), and T8 (the web UI's override
  write, and its read of the model list).
- Tests with the fakes: a fake `opencode models`; each `runtime.models` key renders `model:` into its agent's
  definitions and none when empty, a snapshot, with a digest of its own per set of models; an override reaching every
  run of its agent for the ticket until cleared, and no other agent's; `canopy model KEY` printing each agent's next
  model and where it comes from; `canopy model` refusing a model not listed, an unknown agent, and `inside_run`; a
  dispatch whose model has gone refused `model_missing` with its attention item and no fallback, and a review, a chore,
  and a tick's overseer not started so, the tick ending with a status of its own in `core/vocab.py`; a failed or
  timed-out list read refused `model_list_failed`; any template, prefix, or suffix passing `--model` a config error; the
  web API's override write refusing as the CLI does, and the ticket page's Model panel (Vitest and Playwright); the
  run's `model` in `canopy status`, a snapshot, and in the spend split by model.
- **Follows from this, not built here.** Issue #275: once canopy knows a worker's model before the run starts, the
  commit trailer (§8, `trust.commit_trailer_name`) can name it, with no change to the shipped prompts.

Accept: Stage 0 recorded, and the design written before work starts. Live, once built: with `runtime.models.worker`
empty, the operator sets one labeled ticket to a model other than the default from its page in the web UI; its
`implement`, and a `resume` after a review comment, both run on that model, their records name it, and each session's
own record agrees; `canopy spend` shows their cost under that model; a model not in `opencode models` is refused when
set, and one dropped from the provider config after it was set refuses the ticket's next dispatch with an attention
item; with `runtime.models.reviewer` set, the PR's review runs on that model and names it.

Status: in progress. Stage 0's source read is done (2026-10-19, OpenCode 1.19.3, §13 Each agent's
model). A `model:` in the definition is the model `opencode run --agent` uses, and `opencode models` prints, offline,
one `provider/model` a line for the providers with a key, a login, or config, the same list a run's model is looked up
in. It changed the plan in three places: a template's `--model` beats the definition's, so a template that passes one
silently overrides canopy's choice; no `--format json` event names the model, only the session's record that
`opencode export` prints, so recording what served takes a command after the run; and OpenCode itself refuses an
unlisted model before the first call and exits 1, never falling back, so canopy's check at dispatch turns a failed
run into an attention item, and listing reaches no provider, so a listed model can still fail when called. Designed
2026-10-19 (DESIGN §13, Each agent's model). The design settles that the run records only the model canopy asked for,
not the session's record, which `opencode export` would read after every run; that a covered template, prefix, or
suffix passing `--model` is a config error, so what is recorded is what runs; and that dispatch reads `opencode models`
at each dispatch with a model set, in the workspace root rather than a repository's clone or slot, and fails closed,
refusing `model_list_failed` when the read fails as it refuses `model_missing`. The operator settled the two points
left open (2026-10-19): every agent's model can be set, from `[runtime.models]` and per ticket for the ticket's own
agents, and the web UI's control is built with it, on the ticket's page. The commit trailer naming the model
(issue #275) follows from this, not built here. The operator settled the last two open points (2026-10-20): a run
records the models its session says served it, not only what canopy asked for, since cost attribution needs what
served; and past runs are attributed from their sessions too, a few each tick. Of the pinned OpenCode's source
(2026-10-20): `opencode export` finds a session by its id alone, in the one database that holds every project's, so
any directory finds it; it prints each assistant message's `providerID`, `modelID`, and `cost`, and with `--sanitize`
redacts its text, reasoning, tool output, and paths; a session it lacks is `Session not found` on stderr and exit 1.
The sandbox's templates share OpenCode's data directory, so sandboxed runs are found too. Subagent sessions are not in
their parent's export. Built (2026-10-20): the read, from `opencode export --sanitize` after each live tick, five
runs a tick at most, a failed read tried again a day later up to three reads, and `canopy spend`'s split by model.
Built (2026-10-21): the web UI's run, tick, chore run, and review run pages, and the runs list, name each run's models,
each with its share of the cost when there are several, or why none is named yet; and the spend page splits each
kind's cost by model, as `canopy spend` does. Built (2026-10-22): the choosing from config. `[runtime.models]`, one
private `provider/model` per agent (`worker` covering both workers and a task's runs), is rendered as `model:` into
each agent's definition, so each set of models gets its own snapshot; a `--model`, or a `-m` among `opencode run`'s
own arguments, in any `runtime` template, prefix, or suffix is a config error naming the key to set instead; each
dispatch whose agent has a model reads `opencode models` in the workspace root (30 seconds, stdout through a file,
lines that are no model passed over) and refuses `model_missing` or `model_list_failed`, each with its attention item,
spending no attempt and leasing no slot, in a dry run too; and the run records the model asked for, `runs.model`, which
`canopy status` shows on running and recent runs. OpenCode 2's list is not read yet, so under it a chosen model
refuses as `model_list_failed`. Not built yet: the per-ticket override (`canopy model`, a `ticket_overrides` row of
kind `model`) and the ticket page's Model panel; `canopy models`; the settings page's read-only `[runtime.models]`; the
check before a review, a chore, a task's run, and a tick's overseer, with its tick status; `canopy status` naming the
models that served a run; and TRUST_MODEL T8.
