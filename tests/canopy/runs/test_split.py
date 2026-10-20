"""Splits are retired (DESIGN §18, ROADMAP M46): a request to split a ticket is guidance to its next run, whose worker
files the pieces as follow-ups, and a split run from before reads as history and holds nothing back."""

from pathlib import Path

import pytest

from canopy.core import db
from canopy.core.vocab import Phase, RunKind, RunStatus
from canopy.runs import dispatch
from tests.canopy.helpers import LABEL, canopy, context, in_tick, pool_statuses, present, waits
from tests.canopy.scenario_helpers import Scenario, dispatches

BOTH = ("api", "web")
RETIRED = (
    "split is retired: a request to split a ticket is guidance to its next implement or resume, whose worker files "
    "the pieces as follow-up tickets"
)


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_split_is_refused_naming_follow_ups(ws_scenario: Scenario, treehouse_state: Path, mode: str) -> None:
    split = canopy("dispatch", "PROJ-12", "--label", LABEL, "--kind", "split", "--repo", "api", "--repo", "web")
    assert ws_scenario.refuses(split, dry_run=mode == "dry run") == [("refused:bad_kind", RETIRED)]
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_request_is_no_option_any_more(ws_scenario: Scenario) -> None:
    implement = ("dispatch", "PROJ-12", "--label", LABEL, "--kind", "implement", "--repo", "api")
    printed = ws_scenario.overseer(*implement, "--request", "1", code=2)
    assert "No such option '--request'" in printed.err


def test_the_split_phase_is_no_phase_to_record(ws_scenario: Scenario) -> None:
    printed = ws_scenario.overseer("ticket", "set", "PROJ-12", "--phase", "split", code=2)
    assert "'split' is not one of" in printed.err


def test_an_old_split_reads_as_history_and_holds_nothing_back(ws_scenario: Scenario) -> None:
    conn = ws_scenario.conn
    ctx = context(ws_scenario.env)
    # PROJ-12 was split into PROJ-13, for api, before splits were retired; its run, phase, and child stay as they were.
    with in_tick(conn, ends_ok=True) as tick_id:
        db.set_ticket(conn, "PROJ-12", ctx.repo, phase=Phase.SPLIT)
        split = db.insert_run(
            conn,
            tick_id=tick_id,
            key="PROJ-12",
            kind=RunKind.SPLIT,
            branch="",
            slots=[],
            runs_dir=dispatch.runs_dir(ctx),
            works_units=False,
        )
        db.finish_run(conn, "runs", split, RunStatus.DONE, None)
        conn.execute(
            "INSERT INTO split_children (child_key, parent_key, repo, run_id) VALUES ('PROJ-13', 'PROJ-12', 'api', ?)",
            (split,),
        )

    # The parent and its child are ordinary tickets: neither is refused, and the child may work in any repository.
    ticked = ws_scenario.tick(dispatches("PROJ-12", repo="api"), dispatches("PROJ-13", repo=BOTH), dry_run=True)
    assert [d.action for d in ticked.decisions if d.ticket_key in {"PROJ-12", "PROJ-13"}] == [
        "dispatch:implement",
        "dispatch:implement",
    ]
    ws_scenario.tick(*waits("PROJ-12", "PROJ-13"), dry_run=True)
    state = ws_scenario.state()
    assert "split_children" not in state
    assert "max_split_attempts" not in state["policy"]
    ticket = ws_scenario.ticket_state("PROJ-12")
    assert (ticket["phase"], ticket["last_run"]["kind"], ticket["units"]) == ("split", "split", [])
    assert "split_attempts" not in ticket

    # Nor does it stop the operator forgetting the parent's work.
    ws_scenario.operator("forget", "PROJ-12")
    assert present(db.get_ticket(conn, "PROJ-12")).forgotten_at is not None
