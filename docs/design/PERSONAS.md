# Personas

Part of the canopy design, normative like all of it: the voice a planner, a reviewer, or a worker writes in, and who
chooses it. Sections are numbered across the whole design; the [README](README.md) has the map. Previous:
[Connectors](CONNECTORS.md).

## 31. Personas

Designed, not built (REQUIREMENTS R24, ROADMAP M60).

A persona is a short Markdown file of voice and emphasis: how an agent writes its plan, its PR, its findings, and its
comments, and what it weighs most while it works. The operator wants to give planning, reviews, or implementation a
flair of its own, such as a reviewer that presses harder on failure paths or a worker that keeps every diff as small as
the ticket allows, without copying a prompt to get it (§12, Prompt overrides).

### What a persona reaches

- The planner, the reviewer, and the workers that implement and resume, public and private. Not the overseer, whose
  prompt is policy and is cached across ticks (§13), nor a triage or a chore, which write verdicts and
  findings rather than prose a person reads.
- The prompt's obligations come before it, and the prompt says so, as it does before the standing instructions (§12).
  A persona changes how an agent writes and where it looks hardest. It never changes the authorization check, the
  result contract, commit attribution, the tools a definition allows, or what makes a review's verdict; the harness's
  guards and its validation of the result hold whatever a persona says.
- One persona per run, bounded in size, so it cannot crowd out the task.

### canopy's own persona

canopy's voice today is spread through its prompts, such as the reviewer reading a change as an adversary, or a worker
leaving alone the PR text it was not asked to change. That voice moves into a shipped persona, `canopy`, which every
run gets unless another is chosen, and the prompts keep only the task, its obligations, and its contracts. A chosen
persona then replaces canopy's voice rather than arguing with it. What a guard or a contract leans on stays in the
prompt, the reviewer's rules for a finding among it.

Rejected: an empty default over today's prompts, where a chosen persona and the built-in voice pull against each other
and the result turns on which the model weighs more.

### Where personas come from

canopy ships a few beside its prompts (§5), `canopy` among them. A file of the same name in the operator's personas
directory shadows a shipped one, and a new name adds to the set, as prompt overrides do (§12). The directory and the
choice of persona are private config (TRUST_MODEL T7): a persona is instructions in every run it reaches, so a shared
workspace file can neither supply one nor choose one.

### Who chooses

- **The operator alone.** A run's persona is its ticket's override for its agent, else that agent's default in
  `[personas]`, else `canopy`, fixed when the run starts. The override is set only by the operator, from
  `canopy persona` or the ticket's page, and refused inside an agent run (T1). The overseer, a dispatch, ticket text,
  and labels choose none.
- **No silent fallback.** Setting a persona that names no file is refused, and a run whose persona's file is gone by
  the time it starts is refused with an attention item, spending no attempt and leasing no slot. It never falls back
  to `canopy`, since a run in a voice nobody chose would read as the chosen one's.
- **What is recorded is what ran.** Each run and review records its persona's name and a digest of its text, so the
  operator can compare one persona's work with another's, and a persona edited between runs splits them into before
  and after.
- A prompt override that cannot carry a persona still serves runs whose persona is `canopy`, which keep the voice the
  override already holds; a run given any other persona refuses it as `bad_prompt` rather than run without the
  persona (§8).

Rejected: the overseer choosing a persona per dispatch from the operator's set (ticket text could steer it toward a
lenient reviewer, T1); a persona that also names a model (§13 chooses models on their own, and two settings of one
model would need a rule for which wins); a persona per repository in the shared map (T7).

### Open

- Whether a review the operator requests of a coworker's PR (§21, Review requests) can take a persona of its own, or
  only the reviewer's default.
