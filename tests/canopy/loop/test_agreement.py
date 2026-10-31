"""Tests for how the derivation agreed with the overseer over a window, per row (`canopy agreement`, §30, §37)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.cli import agreement as agreement_cli
from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import Decider, Phase, TickStatus
from canopy.loop import agreement, phases
from tests.canopy.helpers import in_tick, in_zone

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

#: Who decided what about each ticket in one tick: the action, its rationale, and who recorded it.
type Decided = Mapping[str, Sequence[tuple[str, str, Decider]]]


def ticked(
    env: CanopyEnv,
    conn: sqlite3.Connection,
    derived: Sequence[phases.Derived],
    decided: Decided,
    *,
    left: Mapping[str, Phase] | None = None,
    status: TickStatus = TickStatus.OK,
    dry_run: bool = False,
    ran: bool = True,
) -> int:
    """A tick that derived `derived`, recorded `decided`, and closed `status` with each ticket at its phase in `left`.

    Returns:
        The tick's id.
    """
    with in_tick(conn, dry_run=dry_run) as tick_id:
        phases.record(conn, tick_id, derived)
        db.set_tick_overseer(conn, tick_id, ran=ran)
        for key, decisions in decided.items():
            for action, rationale, by in decisions:
                db.record_decision(conn, tick_id, key, action, rationale, decider=by)
        for key, phase in (left or {}).items():
            db.set_ticket(conn, key, str(env.root), phase=phase)
        phases.record_overseer(conn, tick_id)
        db.finish_tick(conn, tick_id, status, "test")
    return tick_id


def ran_source(conn: sqlite3.Connection, tick_id: int | None, source: str, seconds: int, status: str = "ok") -> None:
    """A run of `source`, in tick `tick_id` or a poll, that took `seconds` and ended `status`, just now."""
    start = datetime.now(UTC) - timedelta(seconds=seconds)
    missed = None if status == "ok" else "it read nothing"
    conn.execute(
        "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, "
        "stderr, missed) VALUES (?, ?, 'tracker', ?, ?, ?, '{}', '{}', '{}', '', ?)",
        (tick_id, source, db.format_time(start), db.format_time(start + timedelta(seconds=seconds)), status, missed),
    )
    conn.commit()


def journal(env: CanopyEnv, conn: sqlite3.Connection) -> tuple[int, int, int]:
    """A window's ticks: PROJ-1's `ready` dispatched twice and waited once, PROJ-2's `ci_red` waited on twice.

    PROJ-3 is closed and marked done, and PROJ-4 is stale. Then three ticks the report reads nothing of: a dry run, one
    whose overseer failed, and one that ran no overseer, each of which would disagree.

    Returns:
        The three ticks read, oldest first.
    """
    ready = phases.Derived("PROJ-1", None, (Phase.READY,), candidate=True, closed=False)
    red = phases.Derived("PROJ-2", None, (), candidate=True, closed=False)
    red_unit = phases.Derived("PROJ-2", "repo", (Phase.CI_RED,))
    closed = phases.Derived("PROJ-3", None, candidate=False, closed=True)
    stale = phases.Derived("PROJ-4", None, stale="PROJ-4 never observed")
    db.set_unit(conn, "PROJ-2", str(env.root), "repo", phase=Phase.CI_RED)
    overseer = Decider.OVERSEER
    first = ticked(
        env,
        conn,
        [ready, red, red_unit, closed, stale],
        {
            "PROJ-1": [("dispatch:implement", "ready", overseer)],
            "PROJ-2": [("wait", "the build is down", overseer)],
            "PROJ-3": [("done", "closed", overseer)],
            "PROJ-4": [("wait", "stale", overseer)],
        },
        left={"PROJ-1": Phase.RUNNING},
    )
    second = ticked(
        env,
        conn,
        [ready, red, red_unit],
        {"PROJ-1": [("dispatch:implement", "ready", overseer)], "PROJ-2": [("wait", "still down", overseer)]},
        left={"PROJ-1": Phase.RUNNING},
    )
    third = ticked(
        env,
        conn,
        [ready],
        {"PROJ-1": [("wait", "no capacity", overseer), ("attention:repo_missing", "gone", Decider.HARNESS)]},
        left={"PROJ-1": Phase.READY},
    )
    wrong = {"PROJ-1": [("wait", "ignored", overseer)]}
    ticked(env, conn, [ready], wrong, left={"PROJ-1": Phase.READY}, dry_run=True)
    ticked(env, conn, [ready], wrong, left={"PROJ-1": Phase.READY}, status=TickStatus.OVERSEER_FAILED)
    ticked(env, conn, [ready], {}, left={"PROJ-1": Phase.READY}, ran=False)
    return first, second, third


def test_each_row_counts_its_decisions_and_its_distinct_tickets(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """Only live ticks that closed ok and ran their overseer are read; a stale ticket is counted apart, not in a row."""
    journal(canopy_env, conn)
    found = agreement.agreement(conn, datetime.now(UTC), 1)
    assert (found.ticks, found.decisions, found.stale, found.stale_tickets) == (3, 7, 1, 1)
    assert [(r.row, r.decisions, r.agrees, r.disagrees, r.situations, r.disagreeing) for r in found.rows] == [
        ("ready", 3, 2, 1, 1, 1),
        ("ci_red", 2, 2, 0, 1, 0),
        ("closed", 1, 1, 0, 1, 0),
    ]


def test_a_disagreement_is_listed_once_per_ticket_and_reason_with_the_overseers_rationale(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """The harness's own rationale is not the overseer's, so it is left out."""
    _, _, third = journal(canopy_env, conn)
    [found] = agreement.agreement(conn, datetime.now(UTC), 1).disagreements
    assert (found.ticket_key, found.rows, found.ticks, found.first_tick, found.last_tick) == (
        "PROJ-1",
        ("ready",),
        1,
        third,
        third,
    )
    assert found.why.startswith("decided wait, allowed ")
    assert found.rationale == "no capacity"


def test_the_same_disagreement_across_ticks_is_one_entry_with_its_span(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """A PR decided again each tick is one situation, with the ticks it held across and the latest rationale."""
    ready = phases.Derived("PROJ-1", None, (Phase.READY,), candidate=True, closed=False)
    ticks = [
        ticked(canopy_env, conn, [ready], {"PROJ-1": [("wait", said, Decider.OVERSEER)]}, left={"PROJ-1": Phase.READY})
        for said in ("busy", "busier")
    ]
    [found] = agreement.agreement(conn, datetime.now(UTC), 1).disagreements
    assert (found.ticks, found.first_tick, found.last_tick, found.rationale) == (2, *ticks, "busier")


def test_each_source_counts_its_runs_and_seconds(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """A poll's run is counted apart from a tick's, and the seconds per tick are over the ticks that ran the source."""
    first, second, _ = journal(canopy_env, conn)
    ran_source(conn, first, "jira", 4)
    ran_source(conn, first, "jira", 2)
    ran_source(conn, second, "jira", 3, status="failed")
    ran_source(conn, None, "jira", 1)
    [jira] = agreement.agreement(conn, datetime.now(UTC), 1).sources
    assert (jira.source, jira.kind, jira.tick_runs, jira.poll_runs, jira.failed) == ("jira", "tracker", 3, 1, 1)
    assert (jira.median_seconds, jira.seconds_per_tick) == (2.5, 4.5)


def test_an_empty_window_says_so(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """With nothing compared, the report says so rather than printing empty tables."""
    del canopy_env
    with in_zone("UTC"):
        lines = agreement_cli.render(agreement.agreement(conn, datetime(2026, 10, 8, 12, tzinfo=UTC), 1))
    assert lines == [
        "The derivation against the overseer over 1 day, since 2026-10-08 UTC: 0 ticks compared, 0 ticket decisions.",
        "",
        "No live tick of the window that ran its overseer derived a ticket.",
        "",
        "No disagreement.",
        "",
        "No connector ran in the window.",
    ]


def test_the_agreement_is_printed_as_tables(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    snapshot: SnapshotAssertion,
) -> None:
    """The rows, each disagreement with the overseer's rationale under it, then the sources."""
    first, _, _ = journal(canopy_env, conn)
    ran_source(conn, first, "jira", 4)
    found = agreement.agreement(conn, datetime.now(UTC), 1)
    lines = agreement_cli.render(found)
    # The window's day and the ticks' ids differ from run to run; the rest is the snapshot.
    assert lines[0].startswith("The derivation against the overseer over 1 day, since ")
    assert (
        "\n".join(line.replace(f"tick {found.disagreements[0].last_tick}", "tick N") for line in lines[1:]) == snapshot
    )


def test_canopy_agreement_prints_the_last_days(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """`--json` prints it as data, and `--days` must be at least one."""
    journal(canopy_env, canopy_env.journal())
    assert main(["agreement", "--days", "1"]) == 0
    assert "ready" in capsys.readouterr().out
    assert main(["agreement", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["days"], found["ticks"], found["stale"]) == (7, 3, 1)
    assert found["rows"][0] == {
        "row": "ready",
        "decisions": 3,
        "agrees": 2,
        "disagrees": 1,
        "situations": 1,
        "disagreeing": 1,
    }
    assert found["disagreements"][0]["rows"] == ["ready"]
    assert main(["agreement", "--days", "0"]) == 2
