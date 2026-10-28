"""`canopy review eval`: the reviewer scored on the operator's own cases (DESIGN §21, Scoring the reviewer).

A case, one of `review.eval_cases` in private config, is a PR at a commit: a `bug` case, a change that was reverted or
fixed forward, with the lines its bug is on as the operator confirmed them; or a `clean` case, one the operator knows
is sound. An eval reviews each case as a review is done (`execute`): in a slot of its repository's pool, checked out
detached at the commit with its links out of the checkout removed, the reviewer in a directory of its own that links to
it, its result line validated and judged. Its prompt is the reviewer's as a first review of a PR no ticket owns gets
it, with no notice, notes, or previous review, so every eval of a case reads the same text but for what it compares:
the prompt, the persona, and the model.

An eval records nothing in the journal. With no review run, no draft, attention item, notification, hold, request's
end, or `resume` comes of it, and nothing the loop reads changes. Its slot is leased as `HOLDER`, a holder reconcile
leaves alone, and the eval returns it, or the next eval does if this one died holding it. Each case starts under the
guards that hold any review's start (`start.check_room`), though the loop does not count the eval among its running
reviews. The score is written to `<state_dir>/review-evals/`, with digests of the prompt and the persona and the model,
so two evals can be compared. It gates nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from canopy.core import agent_models, config, definitions, hostgit, personas, pools, prompts
from canopy.core import review_result as result
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import lock, logs, procs, resources
from canopy.infra.text import printable
from canopy.reviews import execute, start
from canopy.runtime import agents, invocation, stdout

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from canopy.core.config import EvalCase
    from canopy.core.context import Context
    from canopy.runtime.agents import Model
    from canopy.runtime.report import Usage

#: How many lines from a confirmed line a finding's location may be and still find the bug: a reviewer often names the
#: line a defect starts on, or the call that reaches it, a line or two from the one the fix changed.
TOLERANCE: Final = 3
#: The lease holder of an eval's slot: not a `canopy:` holder, so a tick's reconcile does not return it as a dead run's.
HOLDER: Final = "canopy-eval"
#: The remote-tracking branch an eval's checkout names the case's base by, which `{{BASE}}` names to the reviewer.
BASE_BRANCH: Final = "canopy-eval-base"
#: Where evals keep their results, and each one's prompts and logs, in the state directory.
EVALS_DIR: Final = "review-evals"
#: Held while an eval runs, so two never take each other's slots for left behind.
LOCK_FILE: Final = "review-eval.lock"
#: A finding's severities, the most serious first.
SEVERITIES: Final = ("blocking", "major", "minor")
#: The status of a case no review started for: a guard refused it, or its slot could not be leased.
REFUSED: Final = "refused"
_GIT_TIMEOUT_SECONDS: Final = 300


class EvalError(Exception):
    """The eval cannot start: no cases, an unknown one, a persona or model it cannot use, or another eval running."""


@dataclass(frozen=True)
class Setup:
    """What every case of one eval is reviewed with: the prompt, the persona, the model, and the cases."""

    #: The reviewer's prompt file, the operator's override or canopy's.
    prompt: Path
    #: The sha256 of the prompt file's text and the operator's standing instructions to reviewers, in hex.
    prompt_digest: str
    persona: personas.Persona
    #: The model the reviewer runs on, as config spells it; None for the runtime's default.
    model: str | None
    #: Each agent's model by its name for the reviewer's definitions; None for config's.
    models: Mapping[str, Model] | None
    cases: Sequence[EvalCase]

    @property
    def yours(self) -> bool:
        """Whether the prompt is the operator's override rather than canopy's."""
        return not self.prompt.is_relative_to(resources.prompts_dir())


@dataclass(frozen=True)
class Scored:
    """One case's review and what it scored."""

    case: EvalCase
    #: How its review ended, a review run's status, or `REFUSED` when none started.
    status: str
    #: The harness's note on how it ended, or why it was refused.
    note: str = ""
    #: On a bug case, the location of the first finding on a confirmed line, and its severity; None when it missed.
    found: tuple[str, str] | None = None
    #: Its findings by severity.
    findings: Mapping[str, int] = field(default_factory=dict)
    cost_usd: float | None = None

    @property
    def scored(self) -> bool:
        """Whether the review ended `done`, so the case counts: any other ending says nothing of the reviewer."""
        return self.status == ReviewRunStatus.DONE


@dataclass(frozen=True)
class Eval:
    """One eval: what it ran with, each case's score, and where it was saved."""

    setup: Setup
    started_at: str
    scored: Sequence[Scored]
    #: The JSON file it was saved to.
    saved: Path

    @property
    def recall(self) -> tuple[int, int]:
        """The bug cases scored whose bug was found, and the bug cases scored."""
        bugs = [s for s in self.scored if s.scored and s.case.kind == "bug"]
        return sum(s.found is not None for s in bugs), len(bugs)

    @property
    def false_alarms(self) -> tuple[int, int, Counter[str]]:
        """The clean cases scored with any finding, the clean cases scored, and their findings by severity."""
        clean = [s for s in self.scored if s.scored and s.case.kind == "clean"]
        by_severity: Counter[str] = Counter()
        for s in clean:
            by_severity.update(s.findings)
        return sum(any(s.findings.values()) for s in clean), len(clean), by_severity

    def as_json(self) -> dict[str, object]:
        """Return the eval as one JSON object, as it is saved.

        Returns:
            What it ran with, its recall and false alarms, and each case's score.
        """
        found, bugs = self.recall
        alarmed, clean, by_severity = self.false_alarms
        costs = [s.cost_usd for s in self.scored if s.cost_usd is not None]
        return {
            "started_at": self.started_at,
            **setup_json(self.setup),
            "recall": {"found": found, "of": bugs},
            "false_alarms": {"cases": alarmed, "of": clean, **{s: by_severity[s] for s in SEVERITIES}},
            "cost_usd": round(sum(costs), 4) if costs else None,
            "cases": [
                {
                    **case_json(s.case),
                    "status": s.status,
                    "note": s.note,
                    "found": {"location": s.found[0], "severity": s.found[1]} if s.found is not None else None,
                    "findings": {k: s.findings.get(k, 0) for k in SEVERITIES},
                    "cost_usd": s.cost_usd,
                }
                for s in self.scored
            ],
        }


def prepare(ctx: Context, *, names: Sequence[str] = (), persona: str | None = None, model: str | None = None) -> Setup:
    """Choose what the eval runs: the cases `names` gives, every one without, in `persona` on `model`.

    `persona` and `model` default to config's for the reviewer. A model is looked up in the runtime's list, as a
    worker's is, so a score never belongs to a model the runtime put in its place.

    Returns:
        The prompt, its digest, the persona, the model, and the cases.

    Raises:
        EvalError: there are no cases, `names` names one that is not, the persona or the prompt cannot be used, or
            the model is not one the runtime lists, or the reviewer's command runs no agent of canopy's to give it to.
    """
    cfg = ctx.config
    cases = _chosen_cases(cfg.review.eval_cases, names)
    try:
        chosen = personas.load(cfg, persona) if persona is not None else personas.chosen(cfg, "reviewer")
    except personas.PersonaError as e:
        raise EvalError(f"{e.guard}: {e.reason}") from e
    name, models = _model(ctx, model)
    path = prompts.prompt_path(cfg, prompts.REVIEWER)
    try:
        text = path.read_text(encoding="utf-8")
        instructions = prompts.reviewer_instructions(cfg)
    except (OSError, UnicodeDecodeError, prompts.PromptError) as e:
        raise EvalError(f"the reviewer's prompt cannot be read: {e}") from e
    digest = hashlib.sha256(f"{text}\0{instructions}".encode()).hexdigest()
    setup = Setup(path, digest, chosen, name, models, cases)
    try:
        # Rendered once now, so a prompt that cannot be used refuses the eval rather than every case.
        _render(ctx, setup, cases[0], Path("checkout"))
    except prompts.PromptError as e:
        raise EvalError(f"bad_prompt: {e}") from e
    return setup


def run(ctx: Context, setup: Setup, *, reviewing: Callable[[EvalCase], None] | None = None) -> Eval:
    """Review each of `setup`'s cases in turn, score it, and save the eval to the state directory.

    `reviewing` is told of each case as its review starts. A case a guard refuses, or whose slot cannot be leased, is
    not scored, and the next is tried; so is one whose review ends any way but `done`.

    Returns:
        The eval, as saved.

    Raises:
        EvalError: another eval is running.
    """
    log = logs.for_tick(None)
    try:
        with lock.hold(ctx.state_dir / LOCK_FILE):
            started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            where = _eval_dir(ctx, started_at)
            _return_left(ctx, {c.repo for c in setup.cases}, log)
            scored: list[Scored] = []
            for case in setup.cases:
                if reviewing is not None:
                    reviewing(case)
                scored.append(_review(ctx, setup, case, where, log))
                log.info(
                    "review eval case",
                    extra={"case": case.name, "status": scored[-1].status, "found": scored[-1].found is not None},
                )
            done = Eval(setup, started_at, scored, where.with_suffix(".json"))
            logs.write_private(done.saved, json.dumps(done.as_json(), indent=2) + "\n")
            return done
    except lock.LockBusyError as e:
        raise EvalError(f"another `canopy review eval` is running in this workspace ({e})") from e


def setup_json(setup: Setup) -> dict[str, object]:
    """Return what an eval runs with as JSON: the prompt, the persona, the model, and the tolerance.

    Returns:
        `prompt` with its path, digest, and whether it is the operator's; `persona` with its name and digest;
        `model`; and `tolerance`, in lines.
    """
    return {
        "prompt": {"path": str(setup.prompt), "digest": setup.prompt_digest, "yours": setup.yours},
        "persona": {"name": setup.persona.name, "digest": setup.persona.digest},
        "model": setup.model,
        "tolerance": TOLERANCE,
    }


def case_json(case: EvalCase) -> dict[str, object]:
    """Return a case as JSON.

    Returns:
        Its name, kind, PR, repository, commit, base, and confirmed lines.
    """
    return {
        "name": case.name,
        "kind": case.kind,
        "pr": case.pr,
        "repo": case.repo,
        "sha": case.sha,
        "base": case.base,
        "lines": list(case.lines),
    }


def planned(ctx: Context, setup: Setup) -> list[str]:
    """Return what an eval of `setup` would do, for `--dry-run`: what it runs with, and each case. It starts nothing.

    Returns:
        The lines to print: one for what it runs with, then one per case, saying why a case would be refused when its
        repository is unknown or not cloned.
    """
    found = [f"Would review {len(setup.cases)} cases, starting nothing now, with {_with(setup)}."]
    width = max(len(c.name) for c in setup.cases)
    for case in setup.cases:
        try:
            start.check_repo(ctx, case.repo)
            refused = ""
        except start.Refusal as e:
            refused = f"; refused, {e.guard}: {e.reason}"
        bug = f"; bug at {', '.join(case.lines)}" if case.lines else ""
        found.append(
            f"  {case.name:<{width}}  {case.kind:<5}  {case.pr} at {case.sha[:12]} from {case.base[:12]} in "
            f"{case.repo}{bug}{refused}",
        )
    return found


def lines(done: Eval) -> list[str]:
    """Return the eval as a Markdown section, to read or to paste into `docs/MEASUREMENTS.md` as a measurement.

    Returns:
        A heading, what it ran with, a table of each case's score, and its recall, false alarms, and cost.
    """
    found, bugs = done.recall
    alarmed, clean, by_severity = done.false_alarms
    costs = [s.cost_usd for s in done.scored if s.cost_usd is not None]
    cost = f" Cost ${sum(costs):.2f}." if costs else ""
    severities = ", ".join(f"{by_severity[s]} {s}" for s in SEVERITIES)
    return [
        f"## {done.started_at[:10]}: canopy review eval",
        "",
        f"With {_with(done.setup)}. A bug is found by a finding within {TOLERANCE} lines of a line it is on.",
        "",
        "| Case | Kind | Review | Score |",
        "| --- | --- | --- | --- |",
        *(f"| {s.case.name} | {s.case.kind} | {s.status} | {_cell(_score_text(s))} |" for s in done.scored),
        "",
        f"Recall: {found} of {bugs} bug cases. False alarms: {alarmed} of {clean} clean cases, {severities}.{cost}",
    ]


def _chosen_cases(cases: Sequence[EvalCase], names: Sequence[str]) -> list[EvalCase]:
    """Return the cases `names` names, in config's order, or every one when it names none.

    Raises:
        EvalError: there are no cases, or a name is no case's.
    """
    if not cases:
        raise EvalError("no eval cases: add [[review.eval_cases]] tables to your private config (.canopy/config.toml)")
    known = {c.name for c in cases}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise EvalError(f"no eval case named {', '.join(unknown)}; the cases are {', '.join(sorted(known))}")
    return [c for c in cases if not names or c.name in names]


def _model(ctx: Context, model: str | None) -> tuple[str | None, dict[str, Model] | None]:
    """The model the reviewer runs on, `model` or config's, and the models its definitions take for it.

    Returns:
        The model as config spells it, or None for the runtime's default; and the definitions' models, None for
        config's.

    Raises:
        EvalError: `model` is not a model, the reviewer's command runs no agent of canopy's to give it to, or the
            runtime does not list the model the reviewer would run on.
    """
    cfg = ctx.config
    template = cfg.runtime.review_cmd
    chosen = agent_models.of_template(cfg.runtime.models, template)
    models: dict[str, Model] | None = None
    where = "in runtime.models"
    if model is not None:
        try:
            agent_models.check_model(model)
        except ValueError as e:
            raise EvalError(str(e)) from e
        if invocation.agent_of(template) != agents.REVIEWER:
            raise EvalError(f"runtime.review_cmd runs no {agents.REVIEWER}, so --model has no reviewer to choose for")
        models = agent_models.of_run(cfg, template, model)
        chosen = agent_models.parse(model)
        where = "by --model"
    if chosen is None:
        return None, models
    try:
        agent_models.check(ctx.runner, ctx.workspace.root, chosen, version=ctx.config.runtime.version, chosen=where)
    except agent_models.ModelError as e:
        raise EvalError(f"{e.guard}: {e.reason}") from e
    return chosen.name, models


def _with(setup: Setup) -> str:
    """What an eval runs with, in words: its prompt, persona, and model, each digest cut to 12 characters.

    Returns:
        A phrase for a sentence.
    """
    whose = "yours" if setup.yours else "canopy's"
    model = f"model `{setup.model}`" if setup.model is not None else "the runtime's default model"
    return (
        f"prompt `{setup.prompt.name}` ({whose}) at {setup.prompt_digest[:12]}, "
        f"persona `{setup.persona.name}` at {setup.persona.digest[:12]}, and {model}"
    )


def _score_text(s: Scored) -> str:
    """One case's score in words.

    Returns:
        Where a bug case's bug was found, or that it was missed; how many false alarms a clean case had; or why a case
        is not scored.
    """
    if not s.scored:
        return f"not scored: {s.note}" if s.note else "not scored"
    total = sum(s.findings.values())
    if s.case.kind == "bug":
        if s.found is None:
            return f"missed, {total} findings elsewhere" if total else "missed: no findings"
        return f"found at `{s.found[0]}` ({s.found[1]})"
    if not total:
        return "no false alarms"
    counts = ", ".join(f"{s.findings[k]} {k}" for k in SEVERITIES if s.findings.get(k))
    return f"{total} false alarm{'s' if total > 1 else ''}: {counts}"


def _cell(text: str) -> str:
    """`text` as one cell of a Markdown table: printable, on one line, its pipes escaped.

    Returns:
        The cell's text.
    """
    return printable(text).replace("\n", " ").replace("|", "\\|")


def _eval_dir(ctx: Context, started_at: str) -> Path:
    """Make the private directory an eval keeps its prompts and logs in, named for when it started.

    Returns:
        `<state_dir>/review-evals/<time>/`, with a number after the time when one of that name is there already.

    Raises:
        EvalError: a thousand evals started in the same second.
    """
    parent = ctx.state_dir / EVALS_DIR
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = started_at.replace(":", "").replace("-", "")
    for n in range(1, 1000):
        where = parent / (stamp if n == 1 else f"{stamp}-{n}")
        with contextlib.suppress(FileExistsError):
            where.mkdir(mode=0o700)
            return where
    raise EvalError(f"{parent} holds too many evals started at {started_at}")


def _return_left(ctx: Context, repos: Iterable[str], log: logs.TickAdapter) -> None:
    """Return the slots an eval that died left leased as `HOLDER` in `repos`' pools: no eval holds one now."""
    for repo in sorted(repos):
        if ctx.workspace.repo(repo) is None:
            continue
        pool = ctx.pool(repo)
        try:
            for slot in pool.status():
                if slot.lease_holder == HOLDER and slot.lease_id:
                    outcome = pool.return_slot(slot.path, lease_id=slot.lease_id, lease_holder=slot.lease_holder)
                    fields = {"slot": str(slot.path), "repo": repo, "returned": outcome.value}
                    log.warning("review eval slot left leased; returned", extra=fields)
        except pools.PoolError as e:
            log.warning("review eval slots not read", extra={"repo": repo, "error": str(e)})


def _review(ctx: Context, setup: Setup, case: EvalCase, where: Path, log: logs.TickAdapter) -> Scored:
    """Review `case` in a slot leased for it, keeping its prompt and log in `where`, and score it.

    Returns:
        Its score; `REFUSED`, with the guard's reason, when a guard refused it or its slot could not be leased.
    """
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        try:
            repo = start.check_repo(ctx, case.repo)
            start.check_room(ctx, [], [])
            lease = _lease(ctx, repo)
        except start.Refusal as e:
            return Scored(case, REFUSED, f"{e.guard}: {e.reason}")
    cwd = where / case.name
    try:
        outcome, usage = _reviewed(ctx, setup, case, lease, where)
    finally:
        _drop_base(ctx.runner, lease.path)
        with contextlib.suppress(OSError):
            shutil.rmtree(cwd)
        try:
            ctx.pool(repo).return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
        except pools.PoolError as e:
            # The next eval returns it.
            log.error("review eval slot not returned", extra={"slot": str(lease.path), "error": str(e)})  # noqa: TRY400
    return _scored(case, outcome, usage)


def _lease(ctx: Context, repo: str) -> pools.Lease:
    """Lease a slot of `repo`'s pool as `HOLDER`, only when one is free, so an eval makes no slot the pool lacks.

    Returns:
        The lease.

    Raises:
        Refusal: (`no_slot`) none is free, or the pool could not be read or leased from.
    """
    pool = ctx.pool(repo)
    try:
        if not any(s.status == pools.AVAILABLE for s in pool.status()):
            raise start.Refusal("no_slot", f"no slot of {repo}'s pool is available")
        return pool.lease_as(HOLDER)
    except pools.PoolError as e:
        raise start.Refusal("no_slot", str(e)) from e


def _reviewed(
    ctx: Context,
    setup: Setup,
    case: EvalCase,
    lease: pools.Lease,
    where: Path,
) -> tuple[execute.Outcome, Usage | None]:
    """Run the reviewer on `case` in `lease`'s slot, as `execute` runs one, its prompt and log kept in `where`.

    Returns:
        How the review ended, and what it cost, if its runtime said.
    """
    slot = lease.path
    try:
        execute.check_out(ctx.runner, slot, case.sha)
        _set_base(ctx.runner, slot, case.base)
        cwd = where / case.name
        execute.reviewer_dir(ctx, cwd, slot)
        prompt = _render(ctx, setup, case, cwd / start.CHECKOUT_LINK)
        logs.write_private(where / f"{case.name}.prompt", prompt)
        process = execute.reviewer(
            ctx,
            prompt,
            slot,
            models=setup.models,
            title=f"review eval {case.name}",
            repo=case.repo,
            run=f"review-eval-{case.name}",
        )
        with logs.open_private(where / f"{case.name}.log") as out:
            out.write("--- reviewer stdout ---\n")
            out.flush()
            done = ctx.runner.run(
                process.argv,
                cwd=cwd,
                env=process.env,
                stdin=process.stdin,
                timeout=ctx.config.runtime.review_timeout_minutes * 60,
                on_line=lambda line: print(line, end="", file=out),
            )
            out.write(f"\n--- reviewer stderr ---\n{done.stderr}\n")
            out.write(f"--- reviewer exit {done.returncode}{' (timed out)' if done.timed_out else ''} ---\n")
    except execute.Unreviewable as e:
        return execute.Outcome(ReviewRunStatus.FAILED, None, str(e)), None
    except (
        execute.SetupError,
        prompts.PromptError,
        definitions.DefinitionsError,
        procs.ProcError,
        OSError,
    ) as e:
        return execute.Outcome(ReviewRunStatus.CRASHED, None, f"{type(e).__name__}: {e}"), None
    output = stdout.read(done.stdout, version=ctx.config.runtime.version)
    # An eval scores findings alone, so it names no changed paths: its impact is the reviewer's.
    return execute.reviewed(ctx, done, output, changed=(), repo=case.repo), output.usage


def _render(ctx: Context, setup: Setup, case: EvalCase, checkout: Path) -> str:
    """Render the reviewer's prompt for `case`, as a first review of a PR no ticket owns gets it.

    It carries no notice, which is about the loop's runs now, and no notes or previous review, which are the journal's:
    every eval of the case reads the same prompt but for the prompt file, the instructions, and the persona.

    Returns:
        The prompt.

    Raises:
        PromptError: it does not render.
    """
    cfg = ctx.config
    values = start.prompt_values(
        cfg,
        pr=case.pr,
        sha=case.sha,
        checkout=checkout,
        base=BASE_BRANCH,
        run="none: an eval records no run",
        ticket=None,
        attempt=1,
        limit=cfg.policy.max_reviews_per_pr,
        context=None,
    )
    return prompts.render_reviewer(cfg, values, persona=setup.persona)


def _set_base(runner: procs.Runner, slot: Path, base: str) -> None:
    """Fetch the case's base and name it `origin/BASE_BRANCH` in the checkout, where the reviewer's git tools read it.

    Raises:
        Unreviewable: git could not fetch the base, or name it.
        SetupError: git could not be run.
    """
    _git(runner, slot, "fetch", "--quiet", "origin", base)
    _git(runner, slot, "update-ref", f"refs/remotes/origin/{BASE_BRANCH}", base)


def _drop_base(runner: procs.Runner, slot: Path) -> None:
    """Delete `origin/BASE_BRANCH` from the checkout, if it is there: a worktree shares its refs with its clone."""
    with contextlib.suppress(execute.Unreviewable, execute.SetupError):
        _git(runner, slot, "update-ref", "-d", f"refs/remotes/origin/{BASE_BRANCH}")


def _git(runner: procs.Runner, slot: Path, *args: str) -> None:
    try:
        done = runner.run(hostgit.argv(*args), cwd=slot, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise execute.SetupError(f"git {args[0]}: {e}") from e
    if not done.ok:
        raise execute.Unreviewable(f"git {args[0]} failed: {(done.stderr.strip() or done.stdout.strip())[:500]}")


def _scored(case: EvalCase, outcome: execute.Outcome, usage: Usage | None) -> Scored:
    """Score `case` on how its review ended.

    A bug case scores on whether a finding is on a confirmed line, a clean one on its findings.

    Returns:
        The score, its findings counted by severity whether or not the review is scored.
    """
    cost = usage.cost_usd if usage is not None else None
    reported = outcome.result.findings if isinstance(outcome.result, result.ReviewResult) else []
    findings = Counter[str](f.severity for f in reported)
    hit = None
    if case.kind == "bug":
        spots = [_spot(line) for line in case.lines]
        hit = next(((f.location, f.severity) for f in reported if _on(_spot(f.location), spots)), None)
    return Scored(case, outcome.status, outcome.note, hit, dict(findings), cost)


def _spot(location: str) -> tuple[str, int, int] | None:
    """Where `location` names: its path, made plain, and its first and last line; None for no line, or no path.

    Returns:
        The path, the first line, and the last.
    """
    found = config.EVAL_LINE_RE.match(location.strip())
    if found is None:
        return None
    first = int(found["first"])
    last = int(found["last"]) if found["last"] is not None else first
    return str(PurePosixPath(os.path.normpath(found["path"]))), first, max(first, last)


def _on(spot: tuple[str, int, int] | None, confirmed: Iterable[tuple[str, int, int] | None]) -> bool:
    """Whether `spot` is in the same file as one of `confirmed`, within `TOLERANCE` lines of it.

    Returns:
        True when it overlaps one, widened by the tolerance on each side.
    """
    if spot is None:
        return False
    path, first, last = spot
    return any(
        c is not None and c[0] == path and first - TOLERANCE <= c[2] and c[1] <= last + TOLERANCE for c in confirmed
    )
