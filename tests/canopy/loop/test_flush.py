"""The loop delivers to its sinks between ticks, with no overseer run (DESIGN §20, issue 2386).

Each story runs the loop for two ticks thirty minutes apart, idle pacing off, and a `chore.ended` event is recorded as
its first wait begins, as a chore run that ends while the loop idles records one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, outbox
from canopy.core.vocab import ChoreRunStatus
from tests.canopy.helpers import context, messages, present
from tests.canopy.scenario_helpers import loops

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario

#: Ticks thirty minutes apart, idle pacing off.
PACE = {"interval_minutes": 30, "idle_max_minutes": 30, "min_gap_minutes": 5}


def listens(scenario: Scenario, cmd: str) -> None:
    """Set the pace, and the sink `mine`, which runs `cmd` and takes what chores do."""
    scenario.configures(loop=PACE, notify={"sinks": {"mine": {"cmd": cmd, "format": "text", "events": ["chores"]}}})


def chore_ends(scenario: Scenario) -> None:
    """A run of the chore `briefing` ends, which records its event for the sinks that take it."""
    config = context(scenario.env).config
    event = outbox.chore_ended(config, "briefing", 7, ChoreRunStatus.OK, '{"summary": "all quiet"}')
    db.record_event(scenario.conn, present(event))


def test_an_event_recorded_while_the_loop_waits_reaches_its_sink_within_a_minute(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "sink.txt"
    listens(scenario, f"{sink_script} {out}")
    heard: list[str] = []
    written: list[int] = []
    listed = context(scenario.env).state_dir / "attention.md"

    def ends() -> None:
        written.append(listed.stat().st_mtime_ns)
        chore_ends(scenario)

    def hears() -> None:
        written.append(listed.stat().st_mtime_ns)
        heard.extend(messages(out))

    looped = loops(scenario, at={0: ends, 1: hears})
    # Told by the first minute of the wait, and once: the tick at minute 30 has nothing left to say of it.
    assert len(heard) == 1
    assert "briefing" in heard[0]
    assert sum("briefing" in m for m in messages(out)) == 1
    # The list the message points to was written again with it.
    assert written[0] < written[1]
    # No tick was started to deliver it.
    assert (looped.woken_by, looped.started) == (["start", "timer"], [0, 30])


def test_a_quiet_wait_leaves_the_attention_list_as_the_tick_wrote_it(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    listens(scenario, f"{sink_script} {tmp_path / 'sink.txt'}")
    listed = context(scenario.env).state_dir / "attention.md"
    written: list[int] = []
    loops(scenario, at={m: lambda: written.append(listed.stat().st_mtime_ns) for m in (0, 29)})
    assert written[0] == written[1]


def test_a_failing_sink_is_left_to_the_next_tick(scenario: Scenario, sink_script: Path, tmp_path: Path) -> None:
    out = tmp_path / "sink.txt"
    listens(scenario, f"{sink_script} {out} {out}.exit")
    (tmp_path / "sink.txt.exit").write_text("1")
    tried: list[int] = []
    loops(scenario, at={0: lambda: chore_ends(scenario), 29: lambda: tried.append(len(messages(out)))})
    # The first delivery of the wait failed; none of the 57 after it ran the sink, and the second tick did.
    assert tried == [1]
    assert len(messages(out)) == 2
    assert scenario.conn.execute("SELECT failures FROM notify_sinks WHERE name = 'mine'").fetchone()[0] == 2
