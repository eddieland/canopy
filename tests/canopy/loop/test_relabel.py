"""A queue label added after a `not authorized:` failure lifts its hold (`loop.relabel`, DESIGN §14)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from canopy.core import db
from tests.canopy.helpers import KEY, LABEL, minute, waits
from tests.canopy.scenario_helpers import Scenario, fails

if TYPE_CHECKING:
    from pathlib import Path

#: What a worker that found its ticket without a queue label reports, as its prompt asks (D051).
NOT_AUTHORIZED: Final = f"not authorized: {KEY} carries none of the labels `{LABEL}`"
#: How many hours after the run ended the operator adds the label.
LATER: Final = 20


@pytest.mark.usefixtures("git_pool")
def test_a_queue_label_added_after_a_not_authorized_failure_lifts_its_hold(
    scenario: Scenario,
    connector_state: Path,
) -> None:
    """The failure's item goes the tick the source observes the label, and the run in the state block says when."""
    scenario.run(worker=fails(NOT_AUTHORIZED))
    scenario.tick(*waits(KEY))
    assert scenario.attention() == [(KEY, "worker_failed")]
    assert "relabeled_at" not in scenario.ticket_state()["last_run"]

    scenario.time_passes(hours=LATER)
    added = db.format_time(datetime.now(UTC) - timedelta(minutes=5))
    tracker_shows(connector_state, added)
    scenario.tick(*waits(KEY))

    assert scenario.attention() == []
    assert scenario.ticket_state()["last_run"]["relabeled_at"] == minute(added)


@pytest.mark.parametrize(
    ("summary", "added_before"),
    [
        pytest.param(NOT_AUTHORIZED, timedelta(hours=LATER + 1), id="label-added-before-the-run-ended"),
        pytest.param(NOT_AUTHORIZED, None, id="label-with-no-add-time"),
        pytest.param("could not build", timedelta(minutes=5), id="another-failure"),
    ],
)
@pytest.mark.usefixtures("git_pool")
def test_the_hold_stands_without_a_queue_label_added_after_a_not_authorized_failure(
    scenario: Scenario,
    connector_state: Path,
    summary: str,
    added_before: timedelta | None,
) -> None:
    """A label added before the run ended, one with no add time, or any other failure: the item stays."""
    scenario.run(worker=fails(summary))
    scenario.time_passes(hours=LATER)
    added = None if added_before is None else db.format_time(datetime.now(UTC) - added_before)
    tracker_shows(connector_state, added)
    scenario.tick(*waits(KEY))

    assert scenario.attention() == [(KEY, "worker_failed")]
    assert "relabeled_at" not in scenario.ticket_state()["last_run"]


def tracker_shows(state: Path, added_at: str | None) -> None:
    """Have the `tracker` source read KEY open with the queue label, added at `added_at`, None for no add time."""
    line = {
        "kind": "ticket",
        "key": KEY,
        "title": KEY,
        "state": "open",
        "labels": [{"name": LABEL, "added_at": added_at}],
    }
    state.write_text(json.dumps({"jira": {"lines": [line], "query": [KEY]}}))
