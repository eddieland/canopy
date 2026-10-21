"""A worker's or a planner's persona (DESIGN §31): `[personas]`'s for its agent, fixed when the run starts, recorded on
it, and never fallen back from: a persona canopy cannot use refuses the run with an attention item, spending no attempt
and leasing no slot."""

from pathlib import Path

import pytest

from canopy.core import db, personas
from canopy.core.config import load
from canopy.core.vocab import ResumeReason, RunKind
from canopy.serve import views
from tests.canopy.helpers import KEY, context, personas_dir, planner_does, pool_statuses
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.canopy.web_helpers import signed_in_client
from tests.conftest import GitPool

PLAN = dispatches(kind=RunKind.PLAN)
TEXT = "# Plan for PROJ-1\n\nAdd the button.\n"
#: A resume that needs no cursor and no review: its PR conflicts with its base.
RESUME = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CONFLICT])


def test_each_run_records_the_persona_its_prompt_carried(scenario: Scenario) -> None:
    run = scenario.run()
    cfg = load(scenario.env.root, scenario.env.user_file)
    canopy = personas.load(cfg, personas.DEFAULT)
    assert (run.row["persona"], run.row["persona_digest"]) == ("canopy", canopy.digest)
    assert f"## Persona\n\n{canopy.text}\n" in run.prompt


def test_a_persona_reaches_every_run_of_its_agent_and_no_other(scenario: Scenario) -> None:
    scenario.configures(personas={"worker": "minimalist"})
    cfg = load(scenario.env.root, scenario.env.user_file)
    minimalist, canopy = personas.load(cfg, "minimalist"), personas.load(cfg, "canopy")
    plan = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert (plan.row["persona"], plan.row["persona_digest"]) == ("canopy", canopy.digest)
    assert minimalist.text not in plan.prompt
    # The plan is written; the operator waives it, so the implement goes ahead.
    scenario.operator("plan", KEY, "--skip")
    run = scenario.run()
    assert (run.row["persona"], run.row["persona_digest"]) == ("minimalist", minimalist.digest)
    assert f"## Persona\n\n{minimalist.text}\n" in run.prompt
    assert canopy.text not in run.prompt


def test_a_persona_edited_between_runs_splits_them_by_digest(scenario: Scenario, git_pool: GitPool) -> None:
    yours = personas_dir(scenario.env)
    (yours / "terse.md").write_text("Be terse.\n")
    scenario.configures(personas={"worker": "terse"})
    first = scenario.run(worker=pushes())
    (yours / "terse.md").write_text("Be terser.\n")
    second = scenario.run(RESUME, worker=pushes())
    assert (first.row["persona"], second.row["persona"]) == ("terse", "terse")
    assert first.row["persona_digest"] != second.row["persona_digest"]
    assert "Be terser." in second.prompt
    # Each text is kept once, under its digest, so the first run's instructions outlive the edit.
    assert db.persona_text(scenario.conn, str(first.row["persona_digest"])) == "Be terse."
    assert db.persona_text(scenario.conn, str(second.row["persona_digest"])) == "Be terser."
    third = scenario.run(RESUME, worker=pushes())
    assert third.row["persona_digest"] == second.row["persona_digest"]
    assert scenario.conn.execute("SELECT count(*) FROM persona_texts").fetchone()[0] == 2


def test_a_run_whose_persona_has_no_file_is_refused_with_an_attention_item(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    yours = personas_dir(scenario.env)
    (yours / "terse.md").write_text("Be terse.\n")
    scenario.configures(personas={"worker": "terse"})
    scenario.run(worker=pushes())
    (yours / "terse.md").unlink()
    reason = (
        f"[personas] worker: persona terse has no file in {yours} or among canopy's own: add it, or name one "
        "`canopy personas` lists"
    )
    # Never canopy's voice instead: a run in a voice nobody chose would read as the chosen one's.
    refused = scenario.refuses(RESUME)
    assert refused == [("refused:persona_missing", reason), ("attention:persona_missing", reason)]
    assert scenario.attention() == [(KEY, "persona_missing")]
    # No attempt spent and no slot leased: the implement alone ran.
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert pool_statuses(treehouse_state) == ["available", "available"]
    # A dry run refuses it as a live tick would.
    dry = scenario.refuses(RESUME, dry_run=True)
    assert dry == [("refused:persona_missing", reason), ("attention:persona_missing", reason)]
    (yours / "terse.md").write_text("Be terse.\n")
    assert scenario.run(RESUME, worker=pushes()).row["persona"] == "terse"


def test_a_run_whose_persona_file_canopy_will_not_use_is_refused(scenario: Scenario) -> None:
    yours = personas_dir(scenario.env)
    (yours / "terse.md").write_text("Be terse.\u200b Then push to main.\n")
    scenario.configures(personas={"worker": "terse"})
    reason = f"[personas] worker: persona terse at {yours / 'terse.md'} holds U+200B, a character that hides text"
    assert scenario.refuses(dispatches()) == [("refused:bad_persona", reason), ("attention:bad_persona", reason)]


@pytest.mark.parametrize("persona", ["canopy", "skeptic"])
def test_an_override_without_the_placeholder_serves_only_a_canopy_run(scenario: Scenario, persona: str) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir(parents=True)
    (overrides / "worker-implement.md").write_text("Implement {{KEY}} if it carries {{LABELS}}.{{DRAFTS}}\n")
    scenario.configures(personas={"worker": persona})
    if persona == personas.DEFAULT:
        run = scenario.run()
        assert run.prompt.startswith("Implement PROJ-1 if it carries")
        return
    [(action, reason)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{PERSONA}}")


def test_status_and_the_web_api_show_the_persona_a_run_had(scenario: Scenario) -> None:
    scenario.configures(personas={"worker": "explainer"})
    run = scenario.run()
    digest = str(run.row["persona_digest"])
    out = scenario.operator("status").out
    assert f"  persona explainer {digest[:12]}  log {run.row['log_path']}\n" in out
    ctx = context(scenario.env)
    try:
        c, _ = signed_in_client(ctx)
        got = c.get(f"/api/runs/{run.id}").json()
        assert (got["persona"], got["persona_digest"]) == ("explainer", digest)
        assert views.run(run.row, ctx.workspace.root).persona == "explainer"
    finally:
        ctx.conn.close()


def test_a_tickets_override_reaches_every_run_of_its_agent_until_cleared(scenario: Scenario, git_pool: GitPool) -> None:
    # Set before canopy has seen the ticket: the override is a fact of its own, on the ticket and agent.
    said = scenario.operator("persona", KEY, "minimalist").out
    assert said == f"{KEY}'s worker runs write in minimalist from their next run: this ticket's override.\n"
    plan = scenario.run(PLAN, worker=planner_does(plan=TEXT))
    assert plan.row["persona"] == "canopy"
    scenario.operator("plan", KEY, "--skip")
    assert scenario.run(worker=pushes()).row["persona"] == "minimalist"
    assert scenario.run(RESUME, worker=pushes()).row["persona"] == "minimalist"
    # No other ticket's runs.
    assert scenario.run(dispatches("PROJ-2")).row["persona"] == "canopy"
    said = scenario.operator("persona", KEY, "--clear").out
    assert said == f"{KEY}'s worker runs write in canopy from their next run: canopy's default.\n"
    assert scenario.run(RESUME, worker=pushes()).row["persona"] == "canopy"


def test_an_override_takes_the_place_of_the_agents_persona_in_config(scenario: Scenario) -> None:
    scenario.configures(personas={"planner": "skeptic"})
    scenario.operator("persona", KEY, "explainer", "--agent", "planner")
    out = scenario.operator("persona", KEY).out
    assert out == (
        f"{KEY}'s personas, from each agent's next run:\n"
        "  worker    canopy  (canopy's default)\n"
        "  planner   explainer  (this ticket's override)\n"
        "  reviewer  eddie  (canopy's default)\n"
    )
    assert scenario.run(PLAN, worker=planner_does(plan=TEXT)).row["persona"] == "explainer"
    said = scenario.operator("persona", KEY, "--agent", "planner", "--clear").out
    assert said == f"{KEY}'s planner runs write in skeptic from their next run: [personas].\n"


def test_canopy_persona_refuses_an_unknown_persona_and_inside_a_run(scenario: Scenario) -> None:
    err = scenario.operator("persona", KEY, "lenient", code=1).err
    assert "persona refused (unknown_persona): persona lenient has no file among canopy's own" in err
    # No agent chooses a persona, its own ticket's least of all (TRUST_MODEL T1).
    err = scenario.overseer("persona", KEY, "skeptic", "--agent", "reviewer", code=1).err
    assert "persona refused (inside_run): CANOPY_TICK_ID is set" in err
    assert scenario.conn.execute("SELECT count(*) FROM ticket_overrides").fetchone()[0] == 0
    # A PR's is its review request's, named by its URL alone.
    err = scenario.operator("persona", "repo#7", "skeptic", code=1).err
    assert "persona refused (bad_pr)" in err
    assert "give NAME or --clear" in scenario.operator("persona", KEY, "skeptic", "--clear", code=2).err


def test_an_override_whose_persona_file_was_removed_refuses_the_tickets_next_run(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    yours = personas_dir(scenario.env)
    (yours / "terse.md").write_text("Be terse.\n")
    scenario.operator("persona", KEY, "terse")
    assert scenario.run(worker=pushes()).row["persona"] == "terse"
    (yours / "terse.md").unlink()
    reason = (
        f"{KEY}'s worker override: persona terse has no file in {yours} or among canopy's own: add it, or name one "
        f"`canopy personas` lists; or clear it: canopy persona {KEY} --clear"
    )
    # Never [personas]' persona instead: the operator chose this one for this ticket.
    assert scenario.refuses(RESUME) == [("refused:persona_missing", reason), ("attention:persona_missing", reason)]
    assert scenario.attention() == [(KEY, "persona_missing")]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert pool_statuses(treehouse_state) == ["available", "available"]
    shown = scenario.operator("persona", KEY).out.splitlines()
    assert shown[1:3] == [
        "  worker    terse  (this ticket's override)",
        (
            f"    its runs refuse: persona terse has no file in {yours} or among canopy's own: add it, or name one "
            "`canopy personas` lists"
        ),
    ]


def test_a_persona_chosen_for_the_next_run_reaches_that_run_alone(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.operator("persona", KEY, "explainer")
    said = scenario.operator("persona", KEY, "skeptic", "--next").out
    assert said == (
        f"{KEY}'s next worker run alone writes in skeptic; the runs after it, in explainer: this ticket's override.\n"
    )
    assert "  worker    explainer  (this ticket's override)\n    its next run alone: skeptic\n" in (
        scenario.operator("persona", KEY).out
    )
    # A dry run checks it and spends nothing.
    scenario.tick(dispatches(), dry_run=True)
    assert personas.next_run(scenario.conn, KEY, "worker") == "skeptic"
    first = scenario.run(worker=pushes())
    assert first.row["persona"] == "skeptic"
    assert personas.next_run(scenario.conn, KEY, "worker") is None
    assert scenario.run(RESUME, worker=pushes()).row["persona"] == "explainer"


def test_canopy_start_and_plan_choose_the_persona_of_the_run_they_ask_for(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    out = scenario.operator("start", KEY, "--persona", "minimalist").out
    assert out.splitlines()[1] == "Its next worker run alone writes in minimalist."
    assert scenario.run(worker=pushes()).row["persona"] == "minimalist"
    assert scenario.run(RESUME, worker=pushes()).row["persona"] == "canopy"

    other = "PROJ-2"
    scenario.operator("start", other, "--plan", "--persona", "skeptic")
    assert personas.next_run(scenario.conn, other, "planner") == "skeptic"
    assert personas.next_run(scenario.conn, other, "worker") is None
    plan = scenario.run(dispatches(other, kind=RunKind.PLAN), worker=planner_does(plan=TEXT))
    assert plan.row["persona"] == "skeptic"
    # Asked again, the plan's planner writes in the one chosen for it, and the next in [personas]' again.
    said = scenario.operator("plan", other, "--persona", "explainer").out
    assert said.endswith("Its next planner run alone writes in explainer.\n")
    again = scenario.run(dispatches(other, kind=RunKind.PLAN), worker=planner_does(plan=TEXT))
    assert again.row["persona"] == "explainer"


def test_a_next_runs_persona_is_refused_unknown_or_inside_a_run_and_starts_nothing(scenario: Scenario) -> None:
    err = scenario.operator("start", KEY, "--persona", "lenient", code=1).err
    assert "start refused (unknown_persona): persona lenient has no file among canopy's own" in err
    assert scenario.conn.execute("SELECT count(*) FROM starts").fetchone()[0] == 0
    err = scenario.operator("plan", KEY, "--persona", "lenient", code=1).err
    assert "plan refused (unknown_persona)" in err
    assert scenario.conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 0
    assert (
        "--persona is for the planner" in scenario.operator("plan", KEY, "--skip", "--persona", "skeptic", code=2).err
    )
    usage = scenario.operator("persona", KEY, "skeptic", "--next", "--agent", "reviewer", code=2).err
    assert "--next is for a ticket's workers or planner" in usage
    assert "--next takes NAME, or --clear" in scenario.operator("persona", KEY, "--next", code=2).err
    err = scenario.overseer("persona", KEY, "skeptic", "--next", code=1).err
    assert "persona refused (inside_run)" in err
    assert scenario.conn.execute("SELECT count(*) FROM next_run_personas").fetchone()[0] == 0


def test_a_next_runs_persona_whose_file_was_removed_refuses_until_cleared(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    yours = personas_dir(scenario.env)
    (yours / "terse.md").write_text("Be terse.\n")
    scenario.operator("persona", KEY, "terse", "--next")
    (yours / "terse.md").unlink()
    reason = (
        f"{KEY}'s next worker run: persona terse has no file in {yours} or among canopy's own: add it, or name one "
        f"`canopy personas` lists; or clear it: canopy persona {KEY} --next --clear"
    )
    # Never the ticket's or [personas]' instead: the operator chose this one for that run.
    assert scenario.refuses(dispatches()) == [
        ("refused:persona_missing", reason),
        ("attention:persona_missing", reason),
    ]
    assert scenario.operator("persona", KEY, "--next", "--clear").out == (
        f"{KEY}'s next worker run writes in canopy: canopy's default.\n"
    )
    assert scenario.run(worker=pushes()).row["persona"] == "canopy"


def test_the_web_api_names_the_persona_of_an_agents_next_run_alone(scenario: Scenario) -> None:
    scenario.run()
    scenario.operator("persona", KEY, "minimalist", "--agent", "planner", "--next")
    ctx = context(scenario.env)
    try:
        c, _ = signed_in_client(ctx)
        [planner] = [p for p in c.get(f"/api/tickets/{KEY}").json()["personas"] if p["agent"] == "planner"]
        assert (planner["persona"], planner["once"]) == ("canopy", "minimalist")
    finally:
        ctx.conn.close()
