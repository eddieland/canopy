# Toy repositories

A plan, written 2026-10-16, for a set of toy repositories canopy can own outright, so the live checks in
`SCENARIOS.md` can be run on demand: tickets created freely, PRs opened and abandoned, everything reset afterwards.
Nothing here is built yet; the [Order of work](#order-of-work) says what comes first.

## Goals

- Every scenario that needs a real repository (S6, S8 to S21, S36, S37) can run on demand from a known starting state.
- One command resets that state, so a scenario can be repeated.
- A session costs cents in CI and a few dollars in model spend, and nothing runs while nobody is watching.
- Nothing in the toy setup can reach real work: its own org, its own token, its own queue label.

Cost is mostly the model, not CI. On 2026-10-13 the overseer was about 70% of agent spend, at a median tick of $0.18
to $0.35 (`MEASUREMENTS.md`), while a toy repository's check costs nothing on a public repository. So CI is kept tiny,
and the guardrails go on ticks.

## Settled

- **A new GitHub org, `canopy-toys`** (or the nearest free name), holding only these repositories. A fine-grained
  token can then cover the toys and nothing else.
- **Public repositories.** Standard GitHub-hosted runners are free on public repositories, and so are rulesets and
  branch protection, which a Free plan does not offer on private ones.
- **No second human account.** A bot stands in for the second person (see [The bot](#the-bot)).

## Where things live

- **`canopy-toys/kit`**: the template for each toy repository, the issue catalog, the bot's workflow, and the reset
  script. The script uses `gh`, so it stays out of canopy, which imports no GitHub client and ships nothing
  tracker-specific.
- **canopy** gets this file, and later a line per scenario in `SCENARIOS.md` naming the toy and issue that serves it.

## The repositories

Tiny and stdlib-only: nothing to install, so a slot needs no `setup_cmd` and CI needs no setup step.

| Repository | What it is | Scenarios |
| --- | --- | --- |
| `toy-calc` | A Python CLI calculator: about five modules, `unittest` tests, a CHANGELOG | One repository: S8 to S12, S16 to S21, S36 |
| `toy-api` | A JSON "orders" schema and its validator; owns the contract | Several repositories: S13 to S15, S37 |
| `toy-web` | Renders orders from a vendored copy of `toy-api`'s schema, pinned by a version file | Several repositories, joint runs |
| `toy-bazel` (optional) | One `py_binary` and its test under Bazel, with no CI | S7 |

The kit also ships the toy workspace's `canopy-workspace.toml` and `MAP.md`, with GitHub Issues as the tracker.

## CI

One workflow per repository, one job, about 15 seconds a run:

```yaml
on:
  pull_request:
  push: { branches: [main] }
concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }
permissions: { contents: read }
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - uses: actions/checkout@<pinned sha>
      - run: python3 -m unittest -v    # the runner's python, no setup-python
      - run: python3 ci/fetch_check.py # the outage switch, below
```

- No matrix, schedule, cache, or artifacts. Dependabot, Copilot review, and every other bot are off.
- `cancel-in-progress` keeps a worker's successive pushes from stacking runs.
- `check` is the one required status check, so "require status checks" is real.
- Switches that need no code change:
  - **A failing check for `fix-ci` (S9):** a catalog issue whose obvious fix breaks a test it says not to touch, and a
    `ci/must_fail` marker the reset script can commit to a branch.
  - **A staged CI outage (S37, the notice):** `fetch_check.py` fetches the URL in the repository variable
    `TOY_FETCH_URL`. Point it at an unreachable host to stage the outage, and back to end it.
- Actions in the org require approval to run for every outside contributor, so a drive-by fork cannot run anything.

## Repository settings

The kit's setup script applies these to each repository, and checks them on every reset:

- A ruleset on `main`: no direct pushes, no force pushes, no deletion; a PR required, with one approving review and the
  `check` status. The org admin bypasses it, and only the reset script uses that.
- Labels: `agent-ready-<you>-toy` (the toy queue label, never the real one), `needs-human`, and `agent`.
- Workflow permissions read-only by default; "Allow GitHub Actions to create and approve pull requests" on, for the bot.

This keeps TRUST_MODEL §7 whole: authors cannot approve their own PRs on GitHub, and the approval comes from the bot.

## The bot

S18 needs a reviewer canopy does not trust, and the ruleset needs an approver who is not the PR's author. Both are
`github-actions[bot]`, driven by one `workflow_dispatch` workflow in each toy repository:

```text
gh workflow run toy-bot.yml -R canopy-toys/toy-calc -f pr=12 -f action=comment -f body='Rename x to total.'
gh workflow run toy-bot.yml -R canopy-toys/toy-calc -f pr=12 -f action=approve
```

- Actions: `comment` (a review comment on a line), `review` (a review requesting changes), and `approve`.
- It needs no App, key, or secret: the workflow's own `GITHUB_TOKEN`, with `pull-requests: write` in that one workflow.
- Only someone with write access can dispatch it. The toy MCP token (below) is not given Actions write, so a worker
  cannot dispatch it to approve its own PR.
- An account ending in `[bot]` is never an authorized replier (the `tracker-github` skill), and it is not in
  `trust.trusted_reviewers`, so its comments wait as `untrusted_review`: the half of S18 a second person would play.
  The trusted half is the operator's own review comment.
- To verify in step 1: that a `github-actions[bot]` approval counts toward the ruleset's required review. If it does
  not, a GitHub App owned by the org (`canopy-toys-bot`) does the same with an installation token, at the cost of a
  private key the kit's script reads from the operator's keychain.

A GitHub App is also the answer if a scenario ever needs two distinct untrusted identities.

## The issue catalog

`kit/issues/<repo>/NN-slug.md`, each with front matter: the title, the scenario it serves, whether the queue label is
applied at seed time (`autolabel`, off by default), and the catalog slugs it is blocked by. Each is small enough for a
worker to finish in a few minutes.

| Scenario | Issue, and repository |
| --- | --- |
| S8 | "Add a `pow` subcommand" (calc): small and unambiguous |
| S9 | "Make division by zero exit 2" (calc), whose obvious fix breaks a test the issue says not to change |
| S10 | "Rename `--precision` to `--places`" (calc), with a commit to `main` the reset script lands after dispatch |
| S11 | "Add rounding modes; ask which default before starting" (calc) |
| S12 | "Add a `parse` module", then "Use `parse` in the CLI", blocked by the first (calc) |
| S13 | One small issue in each of api and web |
| S14 | "Add `currency` to orders": the schema in api and its rendering in web |
| S15 | The same shape as S14, with a comment from the operator asking for a split |
| S16 | Any issue the size of S8's, started with `canopy start` |
| S18 | Any open toy PR, with a bot comment and an operator comment on it |
| S19 to S21, S36 | Any toy PR, with `review.agent_prs` on |
| S37 | An open PR in each of api and web, written by the operator as the coworker's |

About fifteen in all. Nothing carries the queue label unless marked `autolabel`, so nothing starts until the operator
labels it.

## Reset

`kit/reset.sh <repo|all>`, with the operator's admin `gh`:

1. Close every open PR and delete every branch under `agent/`.
2. Force `main` back to the `seed` tag, through the ruleset's bypass.
3. Close every issue as not planned, then create the catalog again, rewriting catalog slugs to the new `#N`.
4. Print each scenario's new key, such as `S9 → GH-23`.

Issue numbers never repeat, so a reset pairs with a fresh toy workspace (remove it, `canopy init` again) rather than
`canopy forget` key by key.

## Kept apart, and cheap

- **Its own config root.** Run the toys as `XDG_CONFIG_HOME=~/canopy-toys/config canopy ...` (a shell alias). That
  gives them their own canopy user config, their own treehouse config, and their own OpenCode config, whose GitHub MCP
  server uses a fine-grained token on the `canopy-toys` org only: Issues, Pull requests, and Contents write, and no
  Actions or Administration. A toy loop cannot reach a real repository, and a real loop never sees a toy label.
- **The toy user config:** `max_workers = 1`, `max_chores = 0`, `loop.interval_minutes = 30`; a cheaper model on
  `worker_cmd` and `split_cmd` with `--model` (the overseer keeps the real one, since its judgment is what the
  scenarios test); `[review]` off except in the review scenarios.
- **Ticks on demand.** Prefer `canopy tick` or `canopy loop --ticks N` to a loop left running. An idle toy loop
  overnight is where money goes; S27 is the only scenario that needs one.
- **What a run costs:** S8 end to end is a few ticks and one worker, about $1 to $2 of model spend, and a few free
  minutes of CI.

## Order of work

1. Create the org and the kit repository; create the toy token; verify the bot's approval counts (above).
2. `toy-calc` alone: its template, CI, ruleset, bot workflow, about eight catalog issues, and the reset script. Prove
   it with S8 and S9, first `--dry-run`, then for real.
3. `toy-api` and `toy-web`. Prove them with S13 and S14.
4. The rest of the catalog (S10, S11, S12, S15, S18, S37), and the reset script's conflicting commit for S10.
5. In `SCENARIOS.md`, name the toy and issue for each scenario.
6. `toy-bazel`, only if S7 is wanted.

## Open

- The org's name, if `canopy-toys` is taken.
- The cheaper model for toy workers.
