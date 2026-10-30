"""A worker's or a planner's model (DESIGN §13, Each agent's model).

The model is its ticket's override for its agent, else `runtime.models`' for it, written into the agent's definition,
recorded on the run, and looked up in the runtime's list before the run starts, never fallen back from: a model the list
lacks, or a list that cannot be read, refuses the run with an attention item, spending no attempt and leasing no slot;
with a variant, the variant too. Only the operator sets the override, with `canopy model`, never an agent. canopy's
commit trailer names it, and a worker following an approved plan names its planner's on a trailer of its own, while the
operator has not named the trailer themselves.
"""

import json
from pathlib import Path

from canopy.core import definitions
from canopy.core.config import load
from canopy.core.vocab import ResumeReason, RunKind
from tests.canopy.helpers import KEY, agent_runs, listed, planner_does, pool_statuses, trailers_on
from tests.canopy.review_helpers import CLEAN, feature_commit, head, reviewer_reports
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches, pushes, reviews
from tests.conftest import CanopyEnv, GitPool

MODEL = "acme/fake-model-1"
OTHER = "acme/fake-model-2"
PLAN = dispatches(kind=RunKind.PLAN)
#: A resume that needs no cursor and no review: its PR conflicts with its base.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT])


def snapshot_of(scenario: Scenario, run: Ran) -> str:
    """The digest of the snapshot made for `run`: the config it ran under, and its prompt's body (DESIGN §13)."""
    cfg = load(scenario.env.root, scenario.env.user_file)
    bodies, _ = definitions.run_prompt(run.prompt, cfg.runtime.worker_cmd)
    return definitions.digest(cfg, bodies=bodies)


def test_a_run_on_a_chosen_model_records_it_and_its_definition_names_it(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    # A line that is no model, as a plugin may print, is passed over.
    listed(opencode_state, "a plugin says hello", MODEL, OTHER)
    scenario.configures(runtime={"models": {"worker": MODEL}})
    run = scenario.run(worker=pushes())
    assert run.row["model"] == MODEL
    # What the run records is what it ran on: the snapshot made for the config it ran under names the model.
    digest = snapshot_of(scenario, run)
    snapshot = scenario.env.root / ".canopy" / definitions.RUNTIME_DIR / digest
    assert f'\nmodel: "{MODEL}"\n' in (snapshot / "agents" / "canopy-worker.md").read_text()
    # The list is read in the workspace root, not in the run's slot, whose own runtime config could change it: at the
    # ask, and again as the tick starts the run (DESIGN §40).
    assert calls(opencode_state) == [(["models"], str(scenario.env.root))] * 2
    assert f"  model {MODEL}  log {run.row['log_path']}\n" in scenario.operator("status").out
    # Its commits credit the model that did the work (TRUST_MODEL T5).
    assert f"`Co-authored-by: {MODEL} (canopy worker) <noreply@canopy.invalid>`" in run.prompt_file.read_text()


def test_a_run_with_no_model_chosen_goes_to_the_runtimes_default_and_reads_no_list(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    run = scenario.run(worker=pushes())
    assert run.row["model"] is None
    assert calls(opencode_state) == []
    assert "  model " not in scenario.operator("status").out
    assert "`Co-authored-by: canopy worker <noreply@canopy.invalid>`" in run.prompt_file.read_text()


def test_a_trailer_name_the_operator_set_is_used_as_set_whatever_the_model(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL)
    scenario.configures(
        runtime={"models": {"worker": MODEL}},
        trust={"commit_trailer_name": "Acme Agent", "commit_trailer_email": "agent@acme.test"},
    )
    prompt = scenario.run(worker=pushes()).prompt_file.read_text()
    assert "`Co-authored-by: Acme Agent <agent@acme.test>`" in prompt
    assert MODEL not in prompt


def test_each_agents_model_reaches_its_runs_and_no_other(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.configures(runtime={"models": {"planner": OTHER}})
    plan = scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    assert plan.row["model"] == OTHER
    scenario.operator("plan", KEY, "--skip")
    assert scenario.run(worker=pushes()).row["model"] is None


def test_a_worker_following_an_approved_plan_credits_the_planners_model_and_its_own(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.configures(runtime={"models": {"planner": OTHER, "worker": MODEL}})
    scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    scenario.operator("plan", KEY, "--approve")
    prompt = scenario.run(worker=pushes()).prompt_file.read_text()
    worker = f"Co-authored-by: {MODEL} (canopy worker) <noreply@canopy.invalid>"
    planner = f"Co-authored-by: {OTHER} (canopy planner) <noreply@canopy.invalid>"
    assert f"`{worker}`" in prompt
    assert f"`{planner}`" in prompt
    # git adds both, as the prompt names them.
    assert trailers_on(git_pool.origin, "agent/PROJ-1-work") == [[worker, planner]]


def test_a_model_the_runtime_does_not_list_is_refused_with_an_attention_item(
    scenario: Scenario,
    opencode_state: Path,
    treehouse_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, OTHER)
    scenario.configures(runtime={"models": {"worker": MODEL}})
    reason = (
        f"OpenCode does not list the model {MODEL} chosen in runtime.models, so a run on it would fail before its "
        "first call; nothing ran on another model. Choose a model it lists, or set up its provider"
    )
    # Never the runtime's default instead: a canary's run on a model nobody chose would read as the canary's.
    refused = scenario.refuses(dispatches())
    assert refused == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.attention() == [(KEY, "model_missing")]
    # No attempt spent and no slot leased.
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]
    # A dry run refuses it as a live tick would.
    dry = scenario.refuses(dispatches(), dry_run=True)
    assert dry == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    listed(opencode_state, OTHER, MODEL)
    assert scenario.run(worker=pushes()).row["model"] == MODEL


def test_a_run_at_a_variant_records_it_and_its_definition_names_it(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER, variants={MODEL: ["low", "high"]})
    scenario.configures(runtime={"models": {"worker": f"{MODEL}@high"}})
    run = scenario.run(worker=pushes())
    assert run.row["model"] == f"{MODEL}@high"
    digest = snapshot_of(scenario, run)
    worker = scenario.env.root / ".canopy" / definitions.RUNTIME_DIR / digest / "agents" / "canopy-worker.md"
    assert f'\nmodel: "{MODEL}"\nvariant: "high"\n' in worker.read_text()
    # The variants are read only when one is chosen: the runtime drops one its model lacks without a word.
    assert calls(opencode_state) == [(["models", "--verbose"], str(scenario.env.root))] * 2
    assert f"`Co-authored-by: {MODEL}@high (canopy worker) <noreply@canopy.invalid>`" in run.prompt_file.read_text()


def test_a_variant_its_model_does_not_list_is_refused_with_an_attention_item(
    scenario: Scenario,
    opencode_state: Path,
    treehouse_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, variants={MODEL: ["low"]})
    scenario.configures(runtime={"models": {"worker": f"{MODEL}@high"}})
    reason = (
        f"OpenCode lists the model {MODEL} chosen in runtime.models but not its variant high (it lists low); nothing "
        "ran. Choose a variant it lists"
    )
    refused = scenario.refuses(dispatches())
    assert refused == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.attention() == [(KEY, "model_missing")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_a_list_that_cannot_be_read_refuses_the_run(scenario: Scenario, opencode_state: Path) -> None:
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    scenario.configures(runtime={"models": {"worker": MODEL}})
    reason = (
        f"could not look up the model {MODEL} chosen in runtime.models: `opencode models` exited 1. Nothing ran on "
        "another model; the work resumes once the list can be read"
    )
    refused = scenario.refuses(dispatches())
    assert refused == [("refused:model_list_failed", reason), ("attention:model_list_failed", reason)]
    assert scenario.attention() == [(KEY, "model_list_failed")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_an_override_reaches_every_run_of_its_agent_for_the_ticket_until_cleared_and_no_other(
    scenario: Scenario,
    opencode_state: Path,
    agent_log: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    # A canary: the ticket's workers on another model than every other ticket's, which config leaves at the default.
    said = scenario.operator("model", KEY, OTHER).out
    assert said == f"{KEY}'s worker runs use {OTHER} from their next run: this ticket's override.\n"
    plan = scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    assert plan.row["model"] is None
    assert ran_on(agent_log, "canopy-planner") is None
    scenario.operator("plan", KEY, "--skip")
    first = scenario.run(worker=pushes())
    assert first.row["model"] == OTHER
    # What the run recorded is what it ran on: its definition names the override's model.
    assert ran_on(agent_log) == OTHER
    assert scenario.run(RESUME, worker=pushes()).row["model"] == OTHER
    assert scenario.run(dispatches("PROJ-2"), worker=pushes()).row["model"] is None
    assert ran_on(agent_log) is None
    # It outlasts a forget, as the ticket's persona does.
    scenario.operator("forget", KEY)
    assert scenario.operator("model", KEY).out.splitlines()[1] == f"  worker    {OTHER}  (this ticket's override)"
    said = scenario.operator("model", KEY, "--clear").out
    assert said == f"{KEY}'s worker runs use OpenCode's default from their next run: nothing sets one.\n"
    assert scenario.run(worker=pushes()).row["model"] is None


def test_an_override_takes_the_place_of_the_agents_model_in_config(
    scenario: Scenario,
    opencode_state: Path,
    agent_log: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.configures(runtime={"models": {"planner": MODEL, "worker": MODEL}})
    scenario.operator("model", KEY, OTHER, "--agent", "planner")
    assert scenario.operator("model", KEY).out == (
        f"{KEY}'s models, from each agent's next run:\n"
        f"  worker    {MODEL}  ([runtime.models])\n"
        f"  planner   {OTHER}  (this ticket's override)\n"
        "  reviewer  OpenCode's default  (nothing sets one)\n"
    )
    assert scenario.operator("model", KEY, "--agent", "reviewer").out.splitlines()[1:] == [
        "  reviewer  OpenCode's default  (nothing sets one)",
    ]
    plan = scenario.run(PLAN, worker=planner_does(plan="# Plan for PROJ-1\n\nAdd the button.\n"))
    assert plan.row["model"] == OTHER
    assert ran_on(agent_log, "canopy-planner") == OTHER
    said = scenario.operator("model", KEY, "--agent", "planner", "--clear").out
    assert said == f"{KEY}'s planner runs use {MODEL} from their next run: [runtime.models].\n"


def test_canopy_model_refuses_a_model_not_listed_an_unknown_agent_and_inside_a_run(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    listed(opencode_state, OTHER)
    err = scenario.operator("model", KEY, MODEL, code=1).err
    assert err == (
        f"Error: model refused (unknown_model): OpenCode does not list the model {MODEL}: name one `canopy models` "
        "lists, or set up its provider\n"
    )
    variant = scenario.operator("model", KEY, f"{OTHER}@high", code=1).err
    assert variant == (
        f"Error: model refused (unknown_model): OpenCode lists the model {OTHER} but not its variant high (it lists "
        "none for it): name one it lists, or the model alone\n"
    )
    # The overseer and chores work on no one ticket, so take only their model in [runtime.models].
    unknown = scenario.operator("model", KEY, OTHER, "--agent", "overseer", code=2).err
    assert "'overseer' is not one of 'worker', 'planner', 'reviewer'" in unknown
    assert "give MODEL or --clear" in scenario.operator("model", KEY, OTHER, "--clear", code=2).err
    assert "model refused (unsupported)" in scenario.operator("model", "chore:deps", OTHER, code=1).err
    # No agent chooses a model, the overseer's own ticket's least of all (TRUST_MODEL T1), and the list is not read.
    before = calls(opencode_state)
    err = scenario.overseer("model", KEY, OTHER, "--agent", "reviewer", code=1).err
    assert "model refused (inside_run): CANOPY_TICK_ID is set" in err
    assert calls(opencode_state) == before
    # Nor a dispatch: it has no model flag.
    assert "No such option '--model'" in scenario.overseer(*dispatches()[1:], "--model", OTHER, code=2).err
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    err = scenario.operator("model", KEY, OTHER, code=1).err
    assert err == (
        f"Error: model refused (model_list_failed): could not read the models OpenCode lists, to look {OTHER} up: "
        "`opencode models` exited 1\n"
    )
    assert scenario.conn.execute("SELECT count(*) FROM ticket_overrides").fetchone()[0] == 0


def test_an_override_at_a_variant_reaches_the_tickets_runs_and_one_naming_none_drops_configs(
    scenario: Scenario,
    opencode_state: Path,
    agent_log: Path,
    git_pool: GitPool,
) -> None:
    """The canary of an effort: config's model at `high`, one ticket's at `low`, then at the model's default."""
    listed(opencode_state, MODEL, OTHER, variants={MODEL: ["low", "high"]})
    scenario.configures(runtime={"models": {"worker": f"{MODEL}@high"}})
    said = scenario.operator("model", KEY, f"{MODEL}@low").out
    assert said == f"{KEY}'s worker runs use {MODEL}@low from their next run: this ticket's override.\n"
    # The variants were read to look it up, as they are again when the run starts.
    assert calls(opencode_state) == [(["models", "--verbose"], str(scenario.env.root))]
    assert scenario.run(worker=pushes()).row["model"] == f"{MODEL}@low"
    assert ran_on(agent_log) == f"{MODEL}@low"
    err = scenario.operator("model", KEY, f"{MODEL}@max", code=1).err
    assert err == (
        f"Error: model refused (unknown_model): OpenCode lists the model {MODEL} but not its variant max (it lists "
        "high, low): name one it lists, or the model alone\n"
    )
    # The override takes config's whole model: naming no variant runs at the model's default, and says so.
    said = scenario.operator("model", KEY, MODEL).out
    assert said == (
        f"{KEY}'s worker runs use {MODEL} from their next run: this ticket's override (config's variant `high` no "
        "longer applies).\n"
    )
    assert scenario.run(RESUME, worker=pushes()).row["model"] == MODEL
    assert ran_on(agent_log) == MODEL
    said = scenario.operator("model", KEY, "--clear").out
    assert said == f"{KEY}'s worker runs use {MODEL}@high from their next run: [runtime.models].\n"


def test_an_override_whose_variant_was_dropped_refuses_the_tickets_next_dispatch(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, variants={MODEL: ["low", "high"]})
    scenario.operator("model", KEY, f"{MODEL}@low")
    listed(opencode_state, MODEL, variants={MODEL: ["high"]})
    reason = (
        f"OpenCode lists the model {MODEL} chosen for {KEY}'s worker runs (`canopy model {KEY}`) but not its variant "
        "low (it lists high); nothing ran. Choose a variant it lists"
    )
    assert scenario.refuses(dispatches()) == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_an_override_whose_model_was_dropped_refuses_the_tickets_next_dispatch(
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    listed(opencode_state, MODEL, OTHER)
    scenario.operator("model", KEY, OTHER)
    assert scenario.run(worker=pushes()).row["model"] == OTHER
    listed(opencode_state, MODEL)
    reason = (
        f"OpenCode does not list the model {OTHER} chosen for {KEY}'s worker runs (`canopy model {KEY}`), so a run "
        "on it would fail before its first call; nothing ran on another model. Choose a model it lists, or set up its "
        "provider"
    )
    # Never config's model or the runtime's default instead: the operator chose this one for this ticket.
    assert scenario.refuses(RESUME) == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.attention() == [(KEY, "model_missing")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_a_tickets_reviewer_override_reaches_its_reviews_alone(
    reviewing: CanopyEnv,
    scenario: Scenario,
    opencode_state: Path,
    agent_log: Path,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    del reviewing
    listed(opencode_state, MODEL, OTHER)
    scenario.operator("model", KEY, OTHER, "--agent", "reviewer")
    # A review of a PR with no ticket never takes it.
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert ran_on(agent_log, "canopy-reviewer") is None
    scenario.review(reviews(feature_commit(git_pool, tmp_path), ticket=KEY), reviewer=reviewer_reports(CLEAN))
    assert ran_on(agent_log, "canopy-reviewer") == OTHER
    # Nor does a worker's run: the override is the reviewer's alone.
    assert scenario.run(worker=pushes()).row["model"] is None
    assert ran_on(agent_log) is None


def test_a_reviewer_override_whose_model_was_dropped_refuses_the_review_as_it_starts(
    reviewing: CanopyEnv,
    scenario: Scenario,
    opencode_state: Path,
    treehouse_state: Path,
    git_pool: GitPool,
) -> None:
    del reviewing
    scenario.configures(runtime={"models": {"reviewer": MODEL}})
    listed(opencode_state, MODEL, OTHER)
    scenario.operator("model", KEY, OTHER, "--agent", "reviewer")
    listed(opencode_state, MODEL)
    reason = (
        f"OpenCode does not list the model {OTHER} chosen for {KEY}'s reviewer runs (`canopy model {KEY} --agent "
        "reviewer`), so a run on it would fail before its first call; nothing ran on another model. Choose a model it "
        "lists, or set up its provider"
    )
    # Never config's model or the runtime's default instead, and the PR spends none of its reviews.
    refused = scenario.refuses(reviews(head(git_pool), ticket=KEY))
    assert refused == [("refused:model_missing", reason), ("attention:model_missing", reason)]
    assert scenario.attention() == [(KEY, "model_missing")]
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert pool_statuses(treehouse_state) == ["available", "available"]
    # A dry run refuses it as a live tick would.
    dry = scenario.refuses(reviews(head(git_pool), ticket=KEY), dry_run=True)
    assert dry == [("refused:model_missing", reason), ("attention:model_missing", reason)]


def test_a_reviewers_model_in_config_the_runtime_does_not_list_refuses_a_review_of_any_pr(
    reviewing: CanopyEnv,
    scenario: Scenario,
    opencode_state: Path,
    git_pool: GitPool,
) -> None:
    del reviewing
    listed(opencode_state, OTHER)
    scenario.configures(runtime={"models": {"reviewer": MODEL}})
    reason = (
        f"OpenCode does not list the model {MODEL} chosen in runtime.models, so a run on it would fail before its "
        "first call; nothing ran on another model. Choose a model it lists, or set up its provider"
    )
    # A PR with no ticket takes config's model, and is refused on it too.
    refused = scenario.refuses(reviews(head(git_pool)))
    assert refused[0] == ("refused:model_missing", reason)
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    listed(opencode_state, OTHER, MODEL)
    scenario.review(reviews(head(git_pool)), reviewer=reviewer_reports(CLEAN))
    assert scenario.conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 1


def calls(state: Path) -> list[tuple[list[str], str]]:
    """Each `opencode models` the fake ran, with the directory it ran in."""
    log = state.with_name("opencode.jsonl")
    if not log.exists():
        return []
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    return [(e["argv"], e["cwd"]) for e in entries if e["argv"][:1] == ["models"]]


def ran_on(agent_log: Path, agent: str = "canopy-worker") -> str | None:
    """The model the definition of the latest run of `agent` names, as it loaded it; None when it names none.

    A variant it names follows the model's id after an `@`, as config spells it.
    """
    run = [r for r in agent_runs(agent_log) if f"--agent {agent}" in " ".join(r["argv"])][-1]
    text = (Path(run["env"]["OPENCODE_CONFIG_DIR"]) / "agents" / f"{agent}.md").read_text()
    found = [line for line in text.splitlines() if line.startswith("model: ")]
    variant = [line for line in text.splitlines() if line.startswith("variant: ")]
    if not found:
        return None
    model = json.loads(found[0].removeprefix("model: "))
    return f"{model}@{json.loads(variant[0].removeprefix('variant: '))}" if variant else model
