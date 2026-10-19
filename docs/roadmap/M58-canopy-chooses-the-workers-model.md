# M58. canopy chooses the worker's model

REQUIREMENTS R23, DESIGN §8, §11, §12, §13, and §22, TRUST_MODEL T1, T5, T7, and T8, D026, D040. Needs M33 and M44.
Asked for by the operator (issue #418): canary a model change by running one ticket on another model and comparing the
result. Today a worker's model is OpenCode's default unless the operator adds a model option to `runtime.worker_cmd`
or `worker_cmd_suffix` (§12), which every worker run then takes, which each operator repeats in their own template,
sandboxed ones included, and which nothing records: the journal cannot say which model a run used. Sketch only; the
design comes first, in §13 beside where the runtime finds canopy's definitions.

- **Stage 0, a source read.** Of the pinned OpenCode (1.19.3), recorded on the `Status:` line: what `opencode models`
  prints, for which providers, how it fails when a provider cannot be reached, and whether it needs the network; that a
  `model:` key in an agent's frontmatter is the model `opencode run --agent` uses, and which wins when the command line
  also passes `--model`; and whether any `--format json` event names the model that served a call. Issue #275 found
  that `step_start` and `step_finish` carry only ids, snapshot, cost, and tokens, and that the session stores each
  message's `providerID` and `modelID`, which `opencode export` prints; Stage 0 confirms both on the pinned version.
- **canopy sets the model, not the template.** When `core/definitions.py` renders a run's snapshot, it writes a
  `model:` key into the frontmatter of the worker definitions this milestone covers (Open, below), as it renders the
  rebase rules and the private worker's tracker tools today. The digest covers the rendered text, so each model gets
  its own immutable snapshot (D040), and a run's snapshot names the model it asked for. `worker_cmd` and its prefix
  and suffix stay as they are, so custom and sandboxed templates keep working, though a template's `--model` beats the
  definition's `model:` (§13, What OpenCode does with a model). No model set renders no key: the runtime's default, as
  today, which is config's `model` or else the model the operator last picked in OpenCode's TUI.
- **A default.** `runtime.worker_model`, a `provider/model` id, empty by default, private as every `runtime` key is
  (T7), so a shared workspace file cannot choose what the operator's spend buys.
- **The operator's override per ticket.** `canopy model KEY provider/model` and `canopy model KEY --clear`, a journal
  fact on the ticket. It covers every run of the ticket that this milestone covers (`implement` and `resume`, and
  `plan` and `split` if they are covered) until it is cleared, so a canary ticket stays on one model. Like `stop`,
  `reply`, and `grant`, it refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set, so neither the
  overseer nor a worker chooses a model, and `canopy dispatch` gets no model flag. M55's triage stays out of it: a
  model is the operator's setting, never an agent's choice. A web UI control may follow, under T8.
- **What OpenCode has.** Models come and go, so canopy reads the list from OpenCode rather than holding one:
  `opencode models`, through `infra/procs.py` with a timeout, its output validated (D026). `canopy models` prints it.
  It works offline, from OpenCode's cache or the catalog built into it, and reaches no provider for most, so a listed
  model can still fail when called. Setting an override refuses a model the list does not hold. Dispatch checks the
  run's model again, since the list may have changed: a model that is gone refuses the run with an attention item
  naming it. OpenCode itself would refuse that run before its first call and exit 1, never falling back, so the check
  turns a failed run into an attention item and keeps the slot. Config load never reads the list, so it stays fast.
- **Recorded on the run.** A migration adds `model` to `runs`: what canopy asked for, empty for the runtime's default.
  No event names the model a call went to; the session records it for each message, and `opencode export` prints it
  (§13). Whether the run keeps that too is open, below. `canopy status` and the web UI's run page show it, and
  `canopy spend` breaks each kind's cost down by model.
- **Out of scope** (issue #418): two models side by side on one ticket, since one worker per ticket stays; the overseer
  or a ticket's labels choosing a model; comparison reports beyond the spend split.
- **Open, for the operator.** Which agents: the issue proposes the worker, the private worker, and the splitter; the
  planner (M44) came since, and its `plan_cmd` already takes the worker prefix and suffix (§12). The reviewer (§21
  recommends a model other than the worker's), the overseer (M40's open model per run), and chores could reuse the
  mechanism later.
- **Open for the design.** What the run records as served: the events name no model, so it is the session's record,
  read with `opencode export` after the run ends, the first OpenCode-only command canopy would run after every run
  (session titles turned one down, §13), or only what canopy asked for, which says nothing of a template's `--model`
  or of the default. When dispatch reads the list (each dispatch, or once a tick), in which directory, since a
  repository's config can change it for its worktrees, and what a dispatch with a model set does when
  `opencode models` fails or times out; being offline is not a failure, since the list comes from a cache. Whether a
  template that also passes `--model`, which wins, is refused, warned about, or left alone.
- **TRUST_MODEL**, in the PR that builds it: T1 (the model is the operator's choice alone, from config or the
  override; no agent sets it, and `canopy model` refuses inside a run), T7 (`runtime.worker_model` private), and T8 if
  the web UI's control is built.
- Tests with the fakes: a fake `opencode models`; `runtime.worker_model` renders `model:` into the covered definitions
  and none when empty, a snapshot, with a digest of its own per model; an override reaching every covered kind of the
  ticket's runs until cleared; `canopy model` refusing a model not listed, and `inside_run`; a dispatch whose model has
  gone refused with its attention item and no fallback; a failed list read, as the design settles it; the run's
  `model` in `canopy status`, a snapshot, and in the spend split by model.
- **Follows from this, not built here.** Issue #275: once canopy knows a worker's model before the run starts, the
  commit trailer (§8, `trust.commit_trailer_name`) can name it, with no change to the shipped prompts.

Accept: Stage 0 recorded, and the design written before work starts. Live, once built: with `runtime.worker_model`
empty, the operator sets one labeled ticket to a model other than the default with `canopy model`; its `implement`,
and a `resume` after a review comment, both run on that model, their records name it, and each session's own record
agrees; `canopy spend` shows their cost under that model; a model not in `opencode models` is refused when set, and one
dropped from the provider config after it was set refuses the ticket's next dispatch with an attention item.

Status: in progress. Stage 0's source read is done (2026-10-19, OpenCode 1.19.3, §13 What OpenCode does with a
model). A `model:` in the definition is the model `opencode run --agent` uses, and `opencode models` prints, offline,
one `provider/model` a line for the providers with a key, a login, or config, the same list a run's model is looked up
in. It changed the plan in three places: a template's `--model` beats the definition's, so a template that passes one
silently overrides canopy's choice; no `--format json` event names the model, only the session's record that
`opencode export` prints, so recording what served takes a command after the run; and OpenCode itself refuses an
unlisted model before the first call and exits 1, never falling back, so canopy's check at dispatch turns a failed
run into an attention item, and listing reaches no provider, so a listed model can still fail when called. The design
remains.
