"""The loop's poll ends its wait when a tick would record or list something new (DESIGN §39, ROADMAP M39).

Each story runs the loop with a `tracker` and a `vcs` source, both the fake connector, polled every two minutes, ticks
thirty minutes apart with idle pacing off, and five minutes the least gap between them. The tracker's answer changes
during the first wait, from the loop's clock's minute 0 on, so the poll at minute 2 reads it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from canopy.core.vocab import Decider, TickStatus
from tests.canopy.helpers import KEY, LABEL, waits
from tests.canopy.scenario_helpers import dispatches, loops

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario

#: Both sources, the fake connector playing each under its own name.
SOURCES = {
    "every_minutes": 2,
    "sources": {
        "jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1},
        "github": {"kind": "vcs", "cmd": "connector github", "timeout_minutes": 1},
    },
}
#: Ticks thirty minutes apart, idle pacing off, and at least five minutes between one's end and the next's start.
PACE = {"interval_minutes": 30, "idle_max_minutes": 30, "min_gap_minutes": 5}
#: An authorized replier's comment on KEY.
REPLY: dict[str, object] = {
    "kind": "comment",
    "ticket": KEY,
    "id": "10001",
    "author": "acc-1",
    "time": "2026-10-20T10:00Z",
    "body": "Go.",
}


def ticket(
    *,
    labels: Sequence[dict[str, object]] = (),
    state: str = "open",
    title: str = "Fix the build",
) -> dict[str, object]:
    """KEY's `ticket` line, as the tracker shows it."""
    return {"kind": "ticket", "key": KEY, "title": title, "state": state, "labels": list(labels)}


def labeled(*more: dict[str, object], state: str = "open", title: str = "Fix the build") -> dict[str, object]:
    """KEY's `ticket` line with the queue label, and `more` labels after it."""
    return ticket(labels=[{"name": LABEL}, *more], state=state, title=title)


@pytest.fixture
def polled(scenario: Scenario, connector_state: Path) -> Path:
    """The two sources and the pace configured, and KEY seen. Yields the connector's state."""
    scenario.configures("private", connect=SOURCES)
    scenario.configures(loop=PACE, trust={"authorized_repliers": ["acc-1"]})
    scenario.seen(KEY)
    return connector_state


@pytest.mark.usefixtures("git_pool")
def test_a_poll_that_changes_a_harness_decision_ends_the_wait_no_sooner_than_the_minimum_gap(
    scenario: Scenario,
    polled: Path,
) -> None:
    tracker_shows(polled, labeled())
    scenario.polls()
    scenario.starts(dispatches())
    # The label is off KEY as the loop starts, so the overseer is left KEY; once back on, the harness waits on its run.
    tracker_shows(polled, ticket())
    looped = loops(scenario, *waits(KEY), at={0: lambda: tracker_shows(polled, labeled())})
    assert looped.woken_by == ["start", "poll"]
    assert looped.started == [0, 5]  # the poll at minute 2 ended the wait, which the gap held to minute 5
    first, second = looped.ticks
    assert (first.overseer_ran, second.overseer_ran, second.status) == (True, False, TickStatus.OK)
    assert 'msg="wait ended" by=poll' in looped.printed
    decided = scenario.conn.execute(
        "SELECT ticket_key, action FROM decisions WHERE tick_id = ? AND decider = ? AND ticket_key IS NOT NULL",
        (second.id, Decider.HARNESS),
    ).fetchall()
    assert [tuple(r) for r in decided] == [(KEY, "wait")]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param([labeled()], [labeled(), REPLY], id="a new comment"),
        pytest.param([labeled()], [labeled({"name": "needs-human"})], id="a row"),
    ],
)
def test_a_poll_that_lists_something_new_to_the_overseer_ends_the_wait(
    scenario: Scenario,
    polled: Path,
    before: Sequence[dict[str, object]],
    after: Sequence[dict[str, object]],
) -> None:
    tracker_shows(polled, *before)
    looped = loops(scenario, *waits(KEY), at={0: lambda: tracker_shows(polled, *after)})
    assert (looped.woken_by, looped.started) == (["start", "poll"], [0, 5])


@pytest.mark.usefixtures("git_pool")
def test_a_poll_that_newly_lists_a_ticket_the_harness_waited_on_ends_the_wait(
    scenario: Scenario,
    polled: Path,
) -> None:
    tracker_shows(polled, labeled())
    scenario.polls()
    scenario.starts(dispatches())
    # The harness waits on KEY's run until the tracker shows KEY closed, which leaves it to the overseer.
    looped = loops(scenario, *waits(KEY), at={0: lambda: tracker_shows(polled, labeled(state="closed"))})
    assert (looped.woken_by, looped.started) == (["start", "poll"], [0, 5])
    assert [t.overseer_ran for t in looped.ticks] == [False, True]


@pytest.mark.parametrize(
    "again",
    [
        pytest.param(lambda: [labeled(), REPLY], id="the same"),
        pytest.param(lambda: [labeled(title="Fix the build, again"), {**REPLY, "body": "Edited."}], id="an edit"),
    ],
)
def test_a_poll_that_reads_only_what_the_latest_tick_saw_ends_no_wait(
    scenario: Scenario,
    polled: Path,
    again: Callable[[], list[dict[str, object]]],
) -> None:
    tracker_shows(polled, labeled(), REPLY)
    looped = loops(scenario, *waits(KEY), at={0: lambda: tracker_shows(polled, *again())})
    assert (looped.woken_by, looped.started) == (["start", "timer"], [0, 30])


def test_a_tick_a_poll_woke_is_not_idle_so_the_wait_after_it_is_not_lengthened(
    scenario: Scenario,
    polled: Path,
) -> None:
    scenario.configures(loop={"idle_max_minutes": 120})
    tracker_shows(polled, labeled())
    looped = loops(scenario, *waits(KEY), ticks=3, at={0: lambda: tracker_shows(polled, labeled(), REPLY)})
    # The comment wakes the loop at minute 5; the overseer's look at it is no second look, so the timer comes 30
    # minutes on, not 60, and the tick it brings, which finds nothing new, is idle.
    assert (looped.woken_by, looped.started) == (["start", "poll", "timer"], [0, 5, 35])
    assert [t.idle for t in looped.ticks] == [False, False, True]


def test_a_failed_poll_ends_the_wait_once_and_the_first_whole_read_ends_it_again(
    scenario: Scenario,
    polled: Path,
) -> None:
    tracker_shows(polled, labeled())
    looped = loops(
        scenario,
        *waits(KEY),
        ticks=3,
        at={0: lambda: tracker_fails(polled), 16: lambda: tracker_shows(polled, labeled())},
    )
    # Failed from minute 0: the poll at 2 ends the wait, and the tick at 5 reads it failed and raises it. The polls at
    # 7 to 15 fail too and end nothing; the one at 17 reads it whole again.
    assert (looped.woken_by, looped.started) == (["start", "poll", "poll"], [0, 5, 17])
    raised = [
        [str(r[0]) for r in scenario.conn.execute("SELECT action FROM decisions WHERE tick_id = ?", (t.id,))]
        for t in looped.ticks
    ]
    assert ["attention:connector_failed" in actions for actions in raised] == [False, True, False]


def tracker_shows(state: Path, *lines: dict[str, object]) -> None:
    """Have the `tracker` source read `lines` whole, its query finding KEY; the `vcs` source reads all it is asked."""
    state.write_text(json.dumps({"jira": {"lines": list(lines), "query": [KEY]}}))


def tracker_fails(state: Path) -> None:
    """Have the `tracker` source fail, printing nothing and exiting 1."""
    state.write_text(json.dumps({"jira": {"end": None, "exit": 1}}))
