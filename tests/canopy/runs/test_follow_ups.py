"""Follow-up tickets (DESIGN §18, ROADMAP M46): what a worker reports filing, recorded and put to the operator."""

import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from canopy.core import contract, conversation, db, outbox, records, sql
from canopy.loop import attention
from canopy.notify import message
from canopy.runs import follow_ups
from tests.canopy.helpers import (
    KEY,
    agent_runs,
    commit_and_push,
    in_tick,
    present,
    private_worker_does,
    ticket_sets,
    waits,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import GitPool

#: The follow-up the parent's worker files, and its repository.
FOLLOW_UP = "PROJ-14"
#: A private worker's result: done, and nothing filed.
DONE: dict[str, object] = {"status": "done", "summary": "did it"}


def recorded(conn: sqlite3.Connection) -> list[tuple[str, str, int, str | None]]:
    return [(f.key, f.parent_key, f.run_id, f.repo) for f in records_of(conn)]


def records_of(conn: sqlite3.Connection) -> list[records.FollowUp]:
    return records.fetch_all(conn, records.FollowUp, sql.frag("SELECT * FROM follow_ups ORDER BY at, key"))


def told(scenario: Scenario) -> list[dict[str, object]]:
    """The fields of each `follow_ups.filed` event in the outbox, in order."""
    rows = scenario.conn.execute("SELECT fields FROM notify_events WHERE kind = 'follow_ups.filed' ORDER BY id")
    return [json.loads(str(r["fields"])) for r in rows]


def takes_runs(scenario: Scenario) -> None:
    """Configure a sink that takes the `runs` events, so they are recorded."""
    scenario.configures(notify={"sinks": {"slack": {"cmd": "true", "events": ["runs"]}}})


def note_of(row: sqlite3.Row) -> str:
    return str(contract.stored_object(row["result_json"]).get("harness") or "")


def test_an_implement_records_each_follow_up_it_reports_with_its_repository(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    run = scenario.run(worker=pushes(created={FOLLOW_UP: "repo", "PROJ-15": None}))
    assert run.status == "done"
    assert recorded(scenario.conn) == [(FOLLOW_UP, KEY, run.id, "repo"), ("PROJ-15", KEY, run.id, None)]
    assert note_of(run.row) == ""
    # The worker was told it may file them, how, and how to report them.
    assert "You may file follow-up tickets" in run.prompt
    assert '"created":{"<key>":"<repository or null>"}' in run.prompt
    assert "File at most 5" in run.prompt


def test_a_blocked_or_failed_run_records_what_it_filed_too(scenario: Scenario, git_pool: GitPool) -> None:
    result = {"status": "failed", "summary": "could not build", "created": {FOLLOW_UP: None}}
    run = scenario.run(worker=worker_does(result=json.dumps(result)))
    assert run.status == "failed"
    assert recorded(scenario.conn) == [(FOLLOW_UP, KEY, run.id, None)]


def test_each_refused_entry_is_recorded_nowhere_named_in_the_note_and_on_the_attention_list(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.seen("PROJ-9")
    created = {
        "not a key!": "repo",
        KEY: None,
        "PROJ-9": None,
        "OTHER-3": None,
        "PROJ-16": "nowhere",
        FOLLOW_UP: "repo",
    }
    run = scenario.run(worker=pushes(created=created))
    # A side output never costs the run its status, nor its PR.
    assert run.status == "done"
    assert recorded(scenario.conn) == [(FOLLOW_UP, KEY, run.id, "repo")]
    note = note_of(run.row)
    assert note.startswith("follow-ups not recorded, so each is an ordinary ticket: ")
    assert f"{KEY}: the run's own ticket" in note
    assert "PROJ-9: not a new ticket: the journal already knows it" in note
    assert "OTHER-3: not in PROJ-1's project" in note
    assert "PROJ-16: its repository is not one in this workspace" in note
    assert "1 more entry, not named" in note
    assert "not a key!" not in note
    assert contract.stored_object(run.row["result_json"])[follow_ups.STORED] == {
        "keys": [KEY, "PROJ-9", "OTHER-3", "PROJ-16"],
        "others": 1,
    }

    # The harness raises it about the run's ticket, every tick, until the ticket is done or forgotten.
    scenario.tick(*waits(KEY, "PROJ-9"))
    [item] = [i for i in attention.current(scenario.conn) if i.reason == follow_ups.REASON]
    assert item.ticket_key == KEY
    assert item.detail.startswith(f"run:{run.id} reported PROJ-1, PROJ-9, OTHER-3, PROJ-16, 1 other entry, which")
    assert "worked only with a queue label" in item.detail
    scenario.overseer(ticket_sets(KEY, done=True))
    scenario.tick(*waits("PROJ-9"))
    assert (KEY, follow_ups.REASON) not in scenario.attention()


def test_a_run_records_at_most_max_follow_ups_the_first_in_its_order(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"max_follow_ups": 1})
    run = scenario.run(worker=pushes(created={FOLLOW_UP: None, "PROJ-15": None}))
    assert recorded(scenario.conn) == [(FOLLOW_UP, KEY, run.id, None)]
    assert "PROJ-15: past policy.max_follow_ups, 1 from one run" in note_of(run.row)
    assert "File at most 1" in run.prompt


def test_at_zero_workers_file_none_and_nothing_is_recorded(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", policy={"max_follow_ups": 0})
    run = scenario.run(worker=pushes(created={FOLLOW_UP: None}))
    assert recorded(scenario.conn) == []
    assert f"{FOLLOW_UP}: policy.max_follow_ups is 0" in note_of(run.row)
    assert "File no tickets in the tracker: the operator set policy.max_follow_ups to 0." in run.prompt


def test_a_follow_ups_runs_file_none(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes(created={FOLLOW_UP: "repo"}))
    run = scenario.run(dispatches(FOLLOW_UP), worker=pushes(created={"PROJ-20": None}))
    assert run.status == "done"
    assert [f.key for f in records_of(scenario.conn)] == [FOLLOW_UP]
    assert f"PROJ-20: {FOLLOW_UP} is itself a follow-up, and a follow-up's runs file none" in note_of(run.row)
    assert f"File no tickets in the tracker: {FOLLOW_UP} is itself a follow-up of {KEY}" in run.prompt


def test_a_follow_up_authorizes_nothing_and_canopy_tells_the_operator_once(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    takes_runs(scenario)
    run = scenario.run(worker=pushes(created={FOLLOW_UP: "repo", "PROJ-15": None}))
    assert "A follow-up is a request, not work you start" in run.prompt
    # The run's close tells the sinks, once: filing is an event, not a state.
    [fields] = told(scenario)
    assert fields == {"ticket": KEY, "run": run.id, "follow_ups": {FOLLOW_UP: "repo", "PROJ-15": None}, "count": 2}
    assert message.event_line("follow_ups.filed", fields) == (
        f"? {KEY} run {run.id} filed follow-ups {FOLLOW_UP} (repo), PROJ-15: "
        "label or `canopy start` each one you want worked"
    )
    # The overseer owes it nothing, and nothing about it stands on the attention list: a tick that decides only the
    # parent, whose PR no source reads, ends ok, records no item about the follow-ups, and tells the sinks nothing more.
    scenario.tick(*waits(KEY))
    scenario.tick(*waits(KEY))
    assert [(i.ticket_key, i.reason) for i in attention.current(scenario.conn)] == [(KEY, "unobserved_pr")]
    assert len(told(scenario)) == 1
    # Nothing dispatches it without a label: it is a request.
    assert scenario.refuses(dispatches(FOLLOW_UP, label=None)) == [
        ("refused:unauthorized", f"label is required: name the queue label you read on {FOLLOW_UP}"),
    ]


def test_a_run_that_files_nothing_tells_the_sinks_nothing(scenario: Scenario, git_pool: GitPool) -> None:
    takes_runs(scenario)
    scenario.run(worker=pushes(created={KEY: None}))
    assert told(scenario) == []


def test_with_no_sink_taking_runs_no_event_is_recorded(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.run(worker=pushes(created={FOLLOW_UP: "repo"}))
    assert [f.key for f in records_of(scenario.conn)] == [FOLLOW_UP]
    assert told(scenario) == []


def test_the_event_names_at_most_its_bound_and_counts_the_rest(scenario: Scenario, git_pool: GitPool) -> None:
    takes_runs(scenario)
    more = outbox.MAX_FOLLOW_UPS + 3
    scenario.configures(policy={"max_follow_ups": more})
    scenario.run(worker=pushes(created={f"PROJ-{n}": None for n in range(100, 100 + more)}))
    [fields] = told(scenario)
    assert list(cast("dict[str, object]", fields["follow_ups"])) == [f"PROJ-{n}" for n in range(100, 120)]
    assert fields["count"] == more
    assert message.event_line("follow_ups.filed", fields).endswith(
        "PROJ-119, 3 more: label or `canopy start` each one you want worked",
    )


def test_a_private_run_records_its_follow_up_which_waits_for_the_operator(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.operator("start", KEY)
    result: dict[str, object] = {"status": "done", "summary": "did it", "created": {FOLLOW_UP: "repo"}}
    run = scenario.run(
        dispatches(label=None),
        worker=private_worker_does(*commit_and_push(f"agent/{KEY}-work"), result=result),
    )
    assert run.row["private"] == 1
    assert recorded(scenario.conn) == [(FOLLOW_UP, KEY, run.id, "repo")]
    # Its worker was told creating it is the one thing it writes to the tracker, and that it is a request.
    assert "Creating them is the one thing you write to the tracker" in run.prompt
    assert "A follow-up is a request, not work you start" in run.prompt
    # canopy starts nothing for it: no start record, so no private dispatch without the operator's start.
    assert conversation.start_of(scenario.conn, FOLLOW_UP) is None
    scenario.tick(*waits(KEY))
    [(action, _)] = scenario.refuses(dispatches(FOLLOW_UP, label=None))
    assert action == "refused:unauthorized"

    # The operator's start makes it a private ticket of its own, worked by the private worker.
    scenario.operator("start", FOLLOW_UP)
    followed = scenario.run(
        dispatches(FOLLOW_UP, label=None),
        worker=private_worker_does(*commit_and_push(f"agent/{FOLLOW_UP}-work"), result=DONE),
    )
    assert (followed.status, followed.row["private"]) == ("done", 1)
    assert followed.prompt.startswith("# canopy private worker: implement")
    [worker] = [r for r in agent_runs(scenario.agent_log) if FOLLOW_UP in str(r["argv"])]
    assert "canopy-worker-private" in str(worker["argv"])


def test_a_ticket_no_run_recorded_still_needs_a_label(scenario: Scenario) -> None:
    [(action, _)] = scenario.refuses(dispatches(FOLLOW_UP, label=None))
    assert action == "refused:unauthorized"


def test_a_run_that_rewrites_its_slots_git_records_no_follow_up(
    scenario: Scenario,
    git_pool: GitPool,
    worktree_pool: tuple[Path, list[Path]],
) -> None:
    del worktree_pool
    result = json.dumps({"status": "done", "summary": "did it", "created": {FOLLOW_UP: "repo"}})
    run = scenario.run(worker=worker_does(["sh", "-c", "printf 'gitdir: /somewhere/else\\n' > .git"], result=result))
    assert run.status == "crashed"
    assert recorded(scenario.conn) == []
    assert f"{FOLLOW_UP}: the run rewrote its slot's git" in note_of(run.row)
    assert contract.stored_object(run.row["result_json"])[follow_ups.STORED] == {"keys": [FOLLOW_UP], "others": 0}


def test_a_key_another_run_recorded_first_is_named_as_refused(scenario: Scenario) -> None:
    # Two runs reporting one key: the second's check passed it, and the transaction found it taken.
    runs = scenario.env.state_dir / "runs"
    with in_tick(scenario.conn) as tick_id:
        with db.transaction(scenario.conn):
            db.touch_ticket(scenario.conn, KEY, "/ws")
            db.touch_ticket(scenario.conn, "PROJ-2", "/ws")
        first = db.insert_run(
            scenario.conn,
            tick_id=tick_id,
            key=KEY,
            kind="implement",
            branch="b",
            slots=(),
            runs_dir=runs,
        )
        second = db.insert_run(
            scenario.conn,
            tick_id=tick_id,
            key="PROJ-2",
            kind="implement",
            branch="c",
            slots=(),
            runs_dir=runs,
        )
        with db.transaction(scenario.conn):
            follow_ups.record_follow_up(scenario.conn, FOLLOW_UP, KEY, first, None)
        scenario.conn.execute(
            "UPDATE runs SET result_json = ? WHERE id = ?",
            (json.dumps({"summary": "did it"}), second),
        )
        checked = follow_ups.Checked(recorded={FOLLOW_UP: None, "PROJ-15": None})
        with db.transaction(scenario.conn):
            done = follow_ups.record(scenario.conn, checked, parent="PROJ-2", run_id=second)
    assert done == ["PROJ-15"]
    stored = contract.stored_object(present(db.get_run(scenario.conn, second))["result_json"])
    assert stored["harness"] == f"follow-ups not recorded: {FOLLOW_UP}: another run recorded it first"
    assert stored[follow_ups.STORED] == {"keys": [FOLLOW_UP], "others": 0}


@pytest.mark.parametrize("created", ["PROJ-14", ["PROJ-14"], 7])
def test_a_created_field_that_is_not_an_object_is_one_refused_entry(
    scenario: Scenario,
    git_pool: GitPool,
    created: object,
) -> None:
    run = scenario.run(worker=pushes(created=created))
    assert run.status == "done"
    assert recorded(scenario.conn) == []
    assert contract.stored_object(run.row["result_json"])[follow_ups.STORED] == {"keys": [], "others": 1}
